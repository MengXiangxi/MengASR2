"""MengASR2 Worker 进程 — 模型推理服务。"""

from __future__ import annotations

# ⚠️ HF 环境变量必须在导入 pyannote 之前设置
import os as _os
from .config_schema import get_worker_config as _get_wc
_wc = _get_wc()
if _wc.get("hf_endpoint"):
    _os.environ.setdefault("HF_ENDPOINT", _wc["hf_endpoint"])
# HF_HUB_OFFLINE：本地已有模型权重时禁止联网检查（医院网络不通）
_os.environ.setdefault("HF_HUB_OFFLINE", "1")
# 缩短 HF 下载超时，避免网络不可用时长时间阻塞
_os.environ.setdefault("HF_HUB_DOWNLOAD_TIMEOUT", "10")

import logging
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI, File, Form, HTTPException, UploadFile

from .backends.base import ASRBackend, SegmentResult
from .config_schema import get_worker_config, load_config

# ── 日志 ───────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("mengasr.worker")

# ── 配置 ───────────────────────────────────────────────────
cfg = get_worker_config()

# ── 后端实例（延迟初始化） ─────────────────────────────────
_backend: ASRBackend | None = None
_diarizer: Any = None
_diarizer_loaded: bool = False


def _create_backend() -> ASRBackend:
    """根据配置创建 ASR 后端实例。"""
    backend_name = cfg["backend"]

    if backend_name == "mimo":
        # 修改 config module 中的 settings（Worker 进程独享的 settings）
        from . import config
        config.settings.mimo_model_path = cfg["mimo_model_path"]
        config.settings.mimo_tokenizer_path = cfg["mimo_tokenizer_path"]
        config.settings.mimo_code_path = cfg["mimo_code_path"]
        config.settings.hf_token = cfg["hf_token"]
        config.settings.hf_endpoint = cfg["hf_endpoint"]
        config.settings.tmp_dir = Path(cfg["tmp_dir"])
        config.settings.tmp_dir.mkdir(parents=True, exist_ok=True)

        from .backends.mimo import MiMoBackend
        logger.info("创建 MiMoBackend: %s", cfg["mimo_model_path"])
        return MiMoBackend()

    if backend_name == "qwen3-asr":
        from .backends.qwen3 import Qwen3ASRBackend
        logger.info("创建 Qwen3ASRBackend: %s", cfg["qwen3_model_id"])
        return Qwen3ASRBackend(model_path=cfg["qwen3_model_id"])

    raise ValueError(f"未知后端: {backend_name}")


async def _load_diarizer() -> bool:
    """加载说话人分离 pipeline。幂等，多次调用安全。"""
    global _diarizer, _diarizer_loaded  # noqa: PLW0603

    # 已标记为成功
    if _diarizer_loaded:
        return True

    # 检查是否有后台线程已加载完成（_load_diarizer 被 asyncio 超时取消后，
    # 线程仍可能继续运行并成功加载）
    if _diarizer is not None and _diarizer.is_loaded():
        _diarizer_loaded = True
        logger.info("说话人分离已在后台加载完成")
        return True

    # 无权重配置
    if not cfg["hf_token"]:
        logger.info("未配置 HF Token，跳过说话人分离加载")
        _diarizer_loaded = True
        return False

    # 清理上一次失败的残留
    if _diarizer is not None:
        _diarizer = None

    from .diarization.pyannote_engine import PyannoteDiarizer

    try:
        _diarizer = PyannoteDiarizer(
            hf_token=cfg["hf_token"],
            hf_endpoint=cfg["hf_endpoint"],
        )
        await _diarizer.load()
        _diarizer_loaded = True
        logger.info("说话人分离加载成功")
        return True
    except Exception as e:
        logger.warning("说话人分离加载失败（网络不可用？将在下次推理时重试）: %s", e)
        _diarizer = None
        return False


# ── 生命周期 ───────────────────────────────────────────────


@asynccontextmanager
async def lifespan(app: FastAPI):
    """启动时加载模型，关闭时释放。"""
    global _backend  # noqa: PLW0603
    logger.info("MengASR2 Worker 启动中……")
    logger.info("后端: %s", cfg["backend"])

    try:
        _backend = _create_backend()
        await _backend.load()
        logger.info("ASR 模型加载成功")
    except Exception as e:
        logger.error("ASR 模型加载失败: %s", e, exc_info=True)
        raise

    # 非阻塞加载：超时 15s，失败不阻止启动，推理时按需重试
    import asyncio as _asyncio
    try:
        await _asyncio.wait_for(_load_diarizer(), timeout=15.0)
    except _asyncio.TimeoutError:
        logger.warning("Diarization 加载超时（网络不可用？），将在首次推理时重试")
    except Exception as e:
        logger.warning("Diarization 加载跳过: %s", e)

    yield

    if _backend:
        await _backend.unload()
    logger.info("MengASR2 Worker 已关闭")


# ── FastAPI 实例 ───────────────────────────────────────────

app = FastAPI(
    title="MengASR2 Worker",
    description="内部推理服务 — 仅供 Listener 调用",
    version="0.3.0",
    lifespan=lifespan,
)


# ── 路由 ───────────────────────────────────────────────────


@app.get("/health")
async def health():
    """Worker 健康检查。"""
    import torch

    # 同步 diarization 后台加载状态
    global _diarizer_loaded  # noqa: PLW0603
    if not _diarizer_loaded and _diarizer is not None and _diarizer.is_loaded():
        _diarizer_loaded = True

    diar_state = "disabled"
    if _diarizer_loaded:
        diar_state = "loaded"
    elif cfg["hf_token"]:
        diar_state = "configured"

    features = ["transcription", "segment_timestamps"]
    if _diarizer_loaded:
        features.append("diarization")

    return {
        "status": "ok",
        "model": _backend.model_id() if _backend else "unknown",
        "backend": cfg["backend"],
        "model_loaded": _backend.is_loaded() if _backend else False,
        "gpu_available": torch.cuda.is_available(),
        "diarization": diar_state,
        "features": features,
    }


@app.post("/infer")
async def infer(
    file: UploadFile = File(..., description="16kHz mono WAV"),
    language: str = Form("auto", description="语言"),
    timestamps: str = Form("none", description="none / segment"),
    diarization: str = Form("false", description="true / false"),
    num_speakers: str = Form("0", description="说话人数量，0=自动"),
):
    """执行推理。接收已预处理的 WAV，返回转写结果。

    参数：
    - file: 16kHz mono WAV（Listener 已用 FFmpeg 预处理）
    - language: auto / chinese / english
    - timestamps: none / segment
    - diarization: true / false
    - num_speakers: 0=自动检测
    """
    if _backend is None or not _backend.is_loaded():
        raise HTTPException(status_code=503, detail="模型未加载")

    enable_diarization = diarization.lower() in ("true", "1", "yes")
    num_spk = int(num_speakers) if num_speakers else 0

    # ── 保存上传的 WAV ────────────────────────────────────
    from .config_schema import get_worker_config as _get_cfg_local

    _cfg_local = _get_cfg_local()
    tmp_dir = Path(_cfg_local["tmp_dir"])
    tmp_dir.mkdir(parents=True, exist_ok=True)

    import uuid as _uuid

    tmp_wav = tmp_dir / f"worker_infer_{_uuid.uuid4().hex}.wav"
    content = await file.read()
    tmp_wav.write_bytes(content)
    logger.info("收到推理请求: %s, size=%d bytes, lang=%s, ts=%s, diar=%s",
                 file.filename, len(content), language, timestamps, enable_diarization)

    try:
        # ── 推理 ──────────────────────────────────────────
        start = time.monotonic()
        segments: list[dict[str, Any]] | None = None

        if timestamps == "segment":
            seg_results = await _backend.transcribe_segments(tmp_wav, language=language)
            text = " ".join(s.text for s in seg_results)
            segments = [
                {"start": s.start, "end": s.end, "text": s.text}
                for s in seg_results
            ]
        else:
            text = await _backend.transcribe(tmp_wav, language=language)

        # ── 说话人分离（按需重试加载，带超时保护） ────────
        use_diarization = False
        if enable_diarization and segments:
            if not _diarizer_loaded:
                logger.info("Diarization 未加载，尝试按需加载……")
                import asyncio as _asyncio
                try:
                    await _asyncio.wait_for(_load_diarizer(), timeout=10.0)
                except _asyncio.TimeoutError:
                    logger.warning("Diarization 加载超时，降级为不分离")
            if _diarizer_loaded and _diarizer:
                use_diarization = True
            else:
                logger.warning("Diarization 不可用，降级为不分离")

        if use_diarization and _diarizer:
            from .diarization.pyannote_engine import assign_speakers_to_segments
            from .schemas import Segment

            ns = num_spk if num_spk > 0 else None
            speaker_turns = await _diarizer.diarize(str(tmp_wav), num_speakers=ns)
            seg_models = [Segment(**s) for s in segments]
            speakers = assign_speakers_to_segments(seg_models, speaker_turns)
            for seg_dict, spk in zip(segments, speakers):
                seg_dict["speaker"] = spk
            logger.info("说话人分离完成: %d 段, 说话人=%s",
                        len(segments), sorted(set(speakers)))

        elapsed = time.monotonic() - start
        logger.info("推理完成: %.2fs, 文本长度=%d", elapsed, len(text))

        import torch as _torch

        return {
            "text": text,
            "duration": None,
            "model": _backend.model_id(),
            "backend": cfg["backend"],
            "inference_time": round(elapsed, 2),
            "gpu_available": _torch.cuda.is_available(),
            "segments": segments,
        }

    except Exception as e:
        logger.error("推理失败: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        tmp_wav.unlink(missing_ok=True)


# ── 直接运行 ───────────────────────────────────────────────
def main():
    import uvicorn
    uvicorn.run(
        "mengasr_server.worker:app",
        host=cfg["host"],
        port=cfg["port"],
        log_level="info",
    )


if __name__ == "__main__":
    main()
