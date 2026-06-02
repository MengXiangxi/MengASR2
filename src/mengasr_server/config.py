"""环境变量与路径配置。

此模块供单体模式（app.py）和向后兼容使用。
双进程模式请使用 config_schema.py（YAML 配置）。
"""

from __future__ import annotations

import os
from pathlib import Path

# 如有 YAML 配置，优先使用
_yaml_config = None
try:
    from .config_schema import load_config
    _yaml_config = load_config()
except Exception:
    pass


def _get(key_path: str, default, env_var: str = "", convert=None):
    """优先级：环境变量 > YAML 配置 > 默认值"""
    if env_var:
        val = os.getenv(env_var)
        if val is not None:
            return convert(val) if convert else val
    if _yaml_config:
        keys = key_path.split(".")
        val = _yaml_config
        for k in keys:
            if isinstance(val, dict):
                val = val.get(k)
            else:
                val = None
                break
        if val is not None:
            return convert(val) if convert else val
    return default


class Settings:
    # ── 鉴权 ──────────────────────────────────────────────
    api_key: str = _get("auth.api_key", "", "MENGASR_API_KEY")

    # ── 模型路径 ──────────────────────────────────────────
    model_dir: Path = Path(_get("listener.tmp_dir", "/srv/mengasr/models", ""))
    mimo_model_path: str = _get(
        "worker.mimo_model_path",
        "/srv/mengasr/models/XiaomiMiMo/MiMo-V2.5-ASR",
        "MENGASR_MIMO_MODEL",
    )
    mimo_tokenizer_path: str = _get(
        "worker.mimo_tokenizer_path",
        "/srv/mengasr/models/XiaomiMiMo/MiMo-Audio-Tokenizer",
        "MENGASR_MIMO_TOKENIZER",
    )

    # ── MiMo 推理代码（sys.path 注入） ─────────────────────
    mimo_code_path: str = _get(
        "worker.mimo_code_path",
        "/srv/mengasr/MiMo-V2.5-ASR-code",
        "MENGASR_MIMO_CODE",
    )

    # ── 服务端口 ──────────────────────────────────────────
    host: str = _get("listener.host", "0.0.0.0", "MENGASR_HOST")
    port: int = int(_get("listener.port", 8787, "MENGASR_PORT"))

    # ── 文件限制 ──────────────────────────────────────────
    max_upload_bytes: int = int(_get("listener.max_upload_mb", 2000, "MENGASR_MAX_UPLOAD_MB")) * 1024 * 1024
    tmp_dir: Path = Path(_get("listener.tmp_dir", "/tmp/mengasr", "MENGASR_TMP_DIR"))
    tmp_dir.mkdir(parents=True, exist_ok=True)

    # ── FFmpeg ────────────────────────────────────────────
    ffmpeg_bin: str = _get("ffmpeg.bin", "ffmpeg", "MENGASR_FFMPEG")
    ffprobe_bin: str = _get("ffmpeg.ffprobe", "ffprobe", "MENGASR_FFPROBE")

    # ── 任务队列 ──────────────────────────────────────────
    job_ttl_seconds: int = int(_get("jobs.ttl_hours", 24, "MENGASR_JOB_TTL_HOURS")) * 3600
    job_max_queue: int = int(_get("jobs.max_queue", 20, "MENGASR_JOB_MAX_QUEUE"))

    # ── 说话人分离 ──────────────────────────────────────────
    hf_token: str = _get("diarization.hf_token", "", "MENGASR_HF_TOKEN")
    hf_endpoint: str = _get("diarization.hf_endpoint", "https://hf-mirror.com", "HF_ENDPOINT")


settings = Settings()
