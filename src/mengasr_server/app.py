"""MengASR2 FastAPI 服务入口。

启动方式：
    uvicorn mengasr_server.app:app --host 0.0.0.0 --port 8787

或使用项目脚本：
    python -m mengasr_server.app
"""

from __future__ import annotations

import logging
import sys
import time
from contextlib import asynccontextmanager

import torch
from fastapi import Depends, FastAPI, File, Form, HTTPException, UploadFile

from .auth import verify_token
from .audio import get_audio_duration, normalize_to_wav, save_upload_streaming
from .backends.mimo import MiMoBackend
from .config import settings
from .diarization.pyannote_engine import PyannoteDiarizer, assign_speakers_to_segments
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

# ── 日志 ───────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("mengasr")

# ── 后端实例 ───────────────────────────────────────────────
backend = MiMoBackend()
diarizer = PyannoteDiarizer(hf_token=settings.hf_token, hf_endpoint=settings.hf_endpoint) if settings.hf_token else None
job_store = JobStore()
job_worker = JobWorker(job_store, backend)


# ── 生命周期 ───────────────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    """启动时加载模型 + 启动任务 Worker，关闭时释放。"""
    logger.info("MengASR2 服务启动中……")
    logger.info("模型路径: %s", settings.mimo_model_path)
    logger.info("Tokenizer: %s", settings.mimo_tokenizer_path)
    try:
        await backend.load()
        logger.info("模型加载成功 ✅")
    except Exception as e:
        logger.error("模型加载失败: %s", e, exc_info=True)

    if diarizer:
        try:
            await diarizer.load()
            logger.info("说话人分离模型加载成功 ✅")
        except Exception as e:
            logger.error("说话人分离模型加载失败: %s", e, exc_info=True)

    await job_worker.start()
    yield
    await job_worker.stop()
    await backend.unload()
    logger.info("MengASR2 服务已关闭")


# ── FastAPI 实例 ──────────────────────────────────────────
app = FastAPI(
    title="MengASR2",
    description="本地 ASR HTTP 服务 — MiMo-V2.5-ASR on RTX 3090 Ti",
    version="0.1.0",
    lifespan=lifespan,
)


# ── 路由 ───────────────────────────────────────────────────


@app.get("/health", response_model=HealthResponse)
async def health():
    """健康检查。"""
    return HealthResponse(
        status="ok",
        model_loaded=backend.is_loaded(),
        gpu_available=torch.cuda.is_available(),
    )


@app.get("/v1/models", response_model=ModelList)
async def list_models(
    _token: str = Depends(verify_token),
):
    """列出可用模型（兼容 OpenAI 风格）。"""
    models = [
        ModelInfo(id=backend.model_id(), owned_by="mengasr"),
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

    兼容 OpenAI Whisper API 的 multipart/form-data 格式。
    """
    # ── 前置检查 ───────────────────────────────────────────
    if not backend.is_loaded():
        raise HTTPException(status_code=503, detail="模型未加载，请稍后重试")

    enable_diarization = diarization.lower() in ("true", "1", "yes")
    if enable_diarization and diarizer is None:
        raise HTTPException(status_code=503, detail="说话人分离未配置（缺少 HF Token）")
    if enable_diarization and not diarizer.is_loaded():
        raise HTTPException(status_code=503, detail="说话人分离模型未加载")
    if enable_diarization and timestamps != "segment":
        # diarization 需要时间戳才能对齐
        timestamps = "segment"

    if file.size and file.size > settings.max_upload_bytes:
        max_mb = settings.max_upload_bytes // (1024 * 1024)
        raise HTTPException(
            status_code=400,
            detail=f"文件过大，最大允许 {max_mb} MB",
        )

    valid_languages = {"auto", "chinese", "english"}
    if language not in valid_languages:
        raise HTTPException(
            status_code=400,
            detail=f"无效语言: {language}，可选值: {valid_languages}",
        )

    # ── 流式保存上传文件（避免内存尖峰） ────────────────────
    suffix = _guess_suffix(file.filename or "audio.wav")
    tmp_input = await save_upload_streaming(file, suffix=suffix)
    tmp_wav = None

    try:
        # ── FFmpeg 标准化 ──────────────────────────────────
        logger.info("收到文件: %s (size=%s)", file.filename, file.size or "unknown")
        tmp_wav = await normalize_to_wav(tmp_input)
        duration = await get_audio_duration(tmp_wav)

        # ── 推理 ───────────────────────────────────────────
        start = time.monotonic()
        segments: list[Segment] | None = None

        if timestamps == "segment":
            seg_results = await backend.transcribe_segments(tmp_wav, language=language)
            text = " ".join(s.text for s in seg_results)
            segments = [Segment(start=s.start, end=s.end, text=s.text) for s in seg_results]
        else:
            text = await backend.transcribe(tmp_wav, language=language)

        # ── 说话人分离 ────────────────────────────────────
        if enable_diarization and segments:
            ns = num_speakers if num_speakers > 0 else None
            speaker_turns = await diarizer.diarize(str(tmp_wav), num_speakers=ns)
            speakers = assign_speakers_to_segments(segments, speaker_turns)
            for seg, spk in zip(segments, speakers):
                seg.speaker = spk
            logger.info("说话人分离完成: %d 段, 说话人=%s",
                        len(segments), sorted(set(speakers)))

        elapsed = time.monotonic() - start
        logger.info("转写完成: %.2fs, 文本长度=%d", elapsed, len(text))

        # ── 返回 ───────────────────────────────────────────
        if response_format == "text":
            from fastapi.responses import PlainTextResponse
            return PlainTextResponse(content=text)

        if response_format == "srt":
            from .formatters.srt import format_srt
            if segments is None:
                raise HTTPException(status_code=400, detail="srt 格式需要 timestamps=segment")
            from fastapi.responses import PlainTextResponse
            return PlainTextResponse(content=format_srt(segments), media_type="text/plain")

        if response_format == "vtt":
            from .formatters.vtt import format_vtt
            if segments is None:
                raise HTTPException(status_code=400, detail="vtt 格式需要 timestamps=segment")
            from fastapi.responses import PlainTextResponse
            return PlainTextResponse(content=format_vtt(segments), media_type="text/vtt")

        return TranscriptionResult(
            text=text,
            language=language if language != "auto" else None,
            duration=duration,
            model=backend.model_id(),
            segments=segments,
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error("转写失败: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail=f"转写失败: {e}")
    finally:
        # 清理临时文件
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
    """创建异步转写任务。

    返回 job_id，客户端可通过 GET /v1/jobs/{job_id} 轮询状态。
    """
    if not backend.is_loaded():
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
    if enable_diarization:
        timestamps = "segment"  # diarization 需要时间戳

    # 流式保存上传文件
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
    # 重命名为 job_id 格式，便于 worker 查找
    final_path = settings.tmp_dir / f"job_{job.job_id}{suffix}"
    tmp_path.rename(final_path)
    logger.info("任务 %s 创建，文件: %s (size=%s)", job.job_id, file.filename, file.size or "unknown")

    # 入队
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
    # 转换 segments 为 Segment 模型
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
    """下载任务结果。

    - response_format=json → 返回 JSON
    - response_format=text → 返回纯文本
    - response_format=srt → 返回 SRT（需阶段 4 支持）
    """
    job = job_store.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail=f"任务 {job_id} 不存在")

    if job.status == JobStatus.queued or job.status == JobStatus.running:
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

    return {
        "job_id": job.job_id,
        "text": job.text,
        "language": job.language,
        "duration": job.duration,
        "model": backend.model_id(),
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
    """从文件名推断后缀。"""
    if "." in filename:
        return "." + filename.rsplit(".", 1)[-1].lower()
    return ".wav"


def _cleanup(path: Path | None) -> None:
    """安全删除临时文件。"""
    try:
        if path and path.exists():
            path.unlink()
    except OSError:
        pass


# ── 直接运行 ───────────────────────────────────────────────
if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "mengasr_server.app:app",
        host=settings.host,
        port=settings.port,
        log_level="info",
    )
