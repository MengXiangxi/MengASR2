"""MengASR2 Listener 进程 — 对外 HTTP API 网关。

职责：
- 对外提供 HTTP API（兼容 OpenAI Whisper 格式）
- 鉴权、文件上传、FFmpeg 预处理
- 异步任务队列管理
- 结果格式化（JSON / text / SRT / VTT）
- 通过 WorkerClient 将推理委托给 Worker 进程

不加载任何模型，不导入 backends/timestamps/diarization。
"""

from __future__ import annotations

import logging
import sys
import time
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, File, Form, HTTPException, UploadFile

from .auth import verify_token
from .audio import get_audio_duration, normalize_to_wav, save_upload_streaming
from .config import settings
from .config_schema import get_listener_config, load_config
from .jobs import JobStore, JobStatus, JobWorker
from .schemas import (
    ErrorResponse,
    HealthResponse,
    JobCreate,
    JobList,
    JobStatus as JobStatusModel,
    ModelInfo,
    ModelList,
    Segment,
    TranscriptionResult,
)
from .worker_client import WorkerClient

# ── 日志 ───────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("mengasr.listener")

# ── Worker 客户端 ─────────────────────────────────────────
listener_cfg = get_listener_config()
worker = WorkerClient(worker_url=listener_cfg["worker_url"])

# ── 任务队列 ──────────────────────────────────────────────
job_store = JobStore()
job_worker = JobWorker(job_store, worker)


# ── 生命周期 ───────────────────────────────────────────────


@asynccontextmanager
async def lifespan(app: FastAPI):
    """启动时检查 Worker 健康，启动任务 Worker。"""
    logger.info("MengASR2 Listener 启动中……")
    logger.info("Worker URL: %s", worker.worker_url)

    try:
        wh = await worker.ahealth()
        logger.info("Worker 健康状态: model=%s, gpu=%s",
                    wh.get("model"), wh.get("gpu_available"))
    except Exception as e:
        logger.error("Worker 连接失败: %s", e)

    await job_worker.start()
    yield
    await job_worker.stop()
    logger.info("MengASR2 Listener 已关闭")


# ── FastAPI 实例 ──────────────────────────────────────────

app = FastAPI(
    title="MengASR2",
    description="本地 ASR HTTP 服务 — MiMo-V2.5-ASR on RTX 3090 Ti",
    version="0.3.0",
    lifespan=lifespan,
)


# ── 辅助：Worker 健康状态缓存 ──────────────────────────────

_worker_info_cache: dict | None = None
_worker_info_ts: float = 0.0


async def _worker_info(refresh: bool = False) -> dict:
    """获取 Worker 信息（带缓存，30s 过期）。"""
    global _worker_info_cache, _worker_info_ts  # noqa: PLW0603
    now = time.monotonic()
    if not refresh and _worker_info_cache and (now - _worker_info_ts) < 30:
        return _worker_info_cache
    try:
        _worker_info_cache = await worker.ahealth()
        _worker_info_ts = now
    except Exception:
        if _worker_info_cache is None:
            _worker_info_cache = {"model_loaded": False, "gpu_available": False, "model": "unknown"}
    return _worker_info_cache


# ── 路由 ───────────────────────────────────────────────────


@app.get("/health", response_model=HealthResponse)
async def health():
    """健康检查（聚合 Listener + Worker 状态）。"""
    wi = await _worker_info()
    return HealthResponse(
        status="ok",
        model_loaded=wi.get("model_loaded", False),
        gpu_available=wi.get("gpu_available", False),
    )


@app.get("/v1/models", response_model=ModelList)
async def list_models(
    _token: str = Depends(verify_token),
):
    """列出可用模型（兼容 OpenAI 风格）。"""
    wi = await _worker_info(refresh=True)
    models = [
        ModelInfo(id=wi.get("model", "mimo-v2.5-asr"), owned_by="mengasr"),
    ]
    return ModelList(data=models)


@app.post(
    "/v1/audio/transcriptions",
    response_model=TranscriptionResult,
    responses={400: {"model": ErrorResponse}, 503: {"model": ErrorResponse}},
)
async def transcribe(
    file: UploadFile = File(..., description="音频或视频文件"),
    model: str = Form("mimo-v2.5-asr", description="模型标识"),
    language: str = Form("auto", description="语言：auto / chinese / english"),
    response_format: str = Form("json", description="响应格式：json / text / srt / vtt"),
    timestamps: str = Form("none", description="时间戳：none / segment"),
    diarization: str = Form("false", description="说话人分离：true / false"),
    num_speakers: int = Form(0, description="说话人数量（0=自动检测）"),
    _token: str = Depends(verify_token),
):
    """转写音频文件（同步接口）。

    预处理后委托给 Worker 进程做推理。
    """
    wi = await _worker_info()
    if not wi.get("model_loaded"):
        raise HTTPException(status_code=503, detail="模型未加载，请稍后重试")

    enable_diarization = diarization.lower() in ("true", "1", "yes")

    # Worker diarization 不可用时降级
    dia_state = wi.get("diarization", "disabled")
    if enable_diarization and dia_state != "loaded":
        logger.warning("Worker diarization 状态=%s，降级为不分离", dia_state)
        enable_diarization = False
    if enable_diarization and timestamps != "segment":
        timestamps = "segment"

    if file.size and file.size > settings.max_upload_bytes:
        max_mb = settings.max_upload_bytes // (1024 * 1024)
        raise HTTPException(status_code=400, detail=f"文件过大，最大允许 {max_mb} MB")

    valid_languages = {"auto", "chinese", "english"}
    if language not in valid_languages:
        raise HTTPException(status_code=400, detail=f"无效语言: {language}，可选值: {valid_languages}")

    # ── 流式保存 + FFmpeg 预处理 ──────────────────────────
    suffix = _guess_suffix(file.filename or "audio.wav")
    tmp_input = await save_upload_streaming(file, suffix=suffix)
    tmp_wav = None

    try:
        logger.info("收到文件: %s (size=%s)", file.filename, file.size or "unknown")
        tmp_wav = await normalize_to_wav(tmp_input)
        duration = await get_audio_duration(tmp_wav)

        # ── 委托 Worker 推理 ──────────────────────────────
        start = time.monotonic()
        result = await worker.ainfer(
            tmp_wav,
            language=language,
            timestamps=timestamps,
            diarization=enable_diarization,
            num_speakers=num_speakers,
        )
        elapsed = time.monotonic() - start
        text = result.get("text", "")
        raw_segments = result.get("segments")
        segments = [Segment(**s) for s in raw_segments] if raw_segments else None
        logger.info("转写完成: %.2fs (Worker infer=%s), 文本长度=%d",
                    elapsed, result.get("inference_time"), len(text))

        # ── 格式化返回 ────────────────────────────────────
        if response_format == "text":
            from fastapi.responses import PlainTextResponse
            return PlainTextResponse(content=text)

        if response_format == "srt":
            if segments is None:
                raise HTTPException(status_code=400, detail="srt 格式需要 timestamps=segment")
            from .formatters.srt import format_srt
            from fastapi.responses import PlainTextResponse
            return PlainTextResponse(content=format_srt(segments), media_type="text/plain")

        if response_format == "vtt":
            if segments is None:
                raise HTTPException(status_code=400, detail="vtt 格式需要 timestamps=segment")
            from .formatters.vtt import format_vtt
            from fastapi.responses import PlainTextResponse
            return PlainTextResponse(content=format_vtt(segments), media_type="text/vtt")

        return TranscriptionResult(
            text=text,
            language=language if language != "auto" else None,
            duration=duration,
            model=result.get("model", "mimo-v2.5-asr"),
            segments=segments,
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error("转写失败: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail=f"转写失败: {e}")
    finally:
        _cleanup(tmp_input)
        if tmp_wav:
            _cleanup(tmp_wav)


# ── 异步任务接口 ───────────────────────────────────────────


@app.post(
    "/v1/jobs",
    response_model=JobCreate,
    responses={400: {"model": ErrorResponse}, 503: {"model": ErrorResponse}},
)
async def create_job(
    file: UploadFile = File(..., description="音频或视频文件"),
    language: str = Form("auto", description="语言：auto / chinese / english"),
    response_format: str = Form("json", description="响应格式：json / text / srt / vtt"),
    timestamps: str = Form("none", description="时间戳：none / segment"),
    diarization: str = Form("false", description="说话人分离：true / false"),
    num_speakers: int = Form(0, description="说话人数量（0=自动检测）"),
    _token: str = Depends(verify_token),
):
    """创建异步转写任务。"""
    wi = await _worker_info()
    if not wi.get("model_loaded"):
        raise HTTPException(status_code=503, detail="模型未加载，请稍后重试")

    if job_store.queued_count() >= settings.job_max_queue:
        raise HTTPException(status_code=429, detail="队列已满，请稍后重试")

    if file.size and file.size > settings.max_upload_bytes:
        max_mb = settings.max_upload_bytes // (1024 * 1024)
        raise HTTPException(status_code=400, detail=f"文件过大，最大允许 {max_mb} MB")

    valid_languages = {"auto", "chinese", "english"}
    if language not in valid_languages:
        raise HTTPException(status_code=400, detail=f"无效语言: {language}")

    enable_diarization = diarization.lower() in ("true", "1", "yes")
    if enable_diarization and wi.get("diarization", "disabled") != "loaded":
        enable_diarization = False
    if enable_diarization:
        timestamps = "segment"

    suffix = _guess_suffix(file.filename or "audio.wav")
    job = job_store.create(
        language=language,
        response_format=response_format,
        filename=file.filename,
        timestamps=timestamps,
        diarization=enable_diarization,
        num_speakers=num_speakers,
    )
    tmp_path = await save_upload_streaming(file, suffix=f"_{job.job_id}{suffix}")
    final_path = settings.tmp_dir / f"job_{job.job_id}{suffix}"
    tmp_path.rename(final_path)
    logger.info("任务 %s 创建，文件: %s (size=%s)", job.job_id, file.filename, file.size or "unknown")

    await job_worker.enqueue(job.job_id)

    return JobCreate(
        job_id=job.job_id,
        status=job.status.value,
        created_at=job.created_at,
    )


@app.get(
    "/v1/jobs/{job_id}",
    response_model=JobStatusModel,
    responses={404: {"model": ErrorResponse}},
)
async def get_job(
    job_id: str,
    _token: str = Depends(verify_token),
):
    """查询任务状态。"""
    job = job_store.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail=f"任务 {job_id} 不存在")
    public = job.to_public()
    if public.get("segments"):
        public["segments"] = [Segment(**s) for s in public["segments"]]
    return JobStatusModel(**public)


@app.get(
    "/v1/jobs/{job_id}/result",
    responses={404: {"model": ErrorResponse}, 409: {"model": ErrorResponse}},
)
async def get_job_result(
    job_id: str,
    response_format: str = "json",
    _token: str = Depends(verify_token),
):
    """下载任务结果。"""
    job = job_store.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail=f"任务 {job_id} 不存在")

    if job.status in (JobStatus.queued, JobStatus.running):
        raise HTTPException(status_code=202, detail=f"任务尚未完成，当前状态: {job.status.value}")

    if job.status == JobStatus.failed:
        raise HTTPException(status_code=500, detail=f"任务失败: {job.error}")

    if job.status == JobStatus.cancelled:
        raise HTTPException(status_code=410, detail="任务已取消")

    if response_format == "text":
        from fastapi.responses import PlainTextResponse
        return PlainTextResponse(content=job.text or "")

    if response_format == "srt" and job.segments:
        from .formatters.srt import format_srt
        srt_segments = [Segment(**s) for s in job.segments]
        from fastapi.responses import PlainTextResponse
        return PlainTextResponse(content=format_srt(srt_segments), media_type="text/plain")

    if response_format == "vtt" and job.segments:
        from .formatters.vtt import format_vtt
        vtt_segments = [Segment(**s) for s in job.segments]
        from fastapi.responses import PlainTextResponse
        return PlainTextResponse(content=format_vtt(vtt_segments), media_type="text/vtt")

    wi = await _worker_info()
    return {
        "job_id": job.job_id,
        "text": job.text,
        "language": job.language,
        "duration": job.duration,
        "model": wi.get("model", "mimo-v2.5-asr"),
    }


@app.get(
    "/v1/jobs",
    response_model=JobList,
)
async def list_jobs(
    limit: int = 20,
    _token: str = Depends(verify_token),
):
    """列出最近的任务。"""
    jobs = job_store.list_jobs(limit=limit)
    return JobList(data=[JobStatusModel(**j) for j in jobs])


@app.delete(
    "/v1/jobs/{job_id}",
    responses={404: {"model": ErrorResponse}},
)
async def cancel_or_delete_job(
    job_id: str,
    _token: str = Depends(verify_token),
):
    """取消（queued）或删除（completed/failed）任务。"""
    job = job_store.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail=f"任务 {job_id} 不存在")

    if job.status in (JobStatus.queued,):
        ok = job_store.cancel(job_id)
        return {"job_id": job_id, "status": "cancelled" if ok else job.status.value}

    ok = job_store.delete(job_id)
    return {"job_id": job_id, "status": "deleted" if ok else "error"}


# ── 辅助函数 ───────────────────────────────────────────────


def _guess_suffix(filename: str) -> str:
    if "." in filename:
        return "." + filename.rsplit(".", 1)[-1].lower()
    return ".wav"


def _cleanup(path: Path | None) -> None:
    try:
        if path and path.exists():
            path.unlink()
    except OSError:
        pass


# ── 直接运行 ───────────────────────────────────────────────
def main():
    import uvicorn
    uvicorn.run(
        "mengasr_server.listener:app",
        host=settings.host,
        port=settings.port,
        log_level="info",
    )


if __name__ == "__main__":
    main()
