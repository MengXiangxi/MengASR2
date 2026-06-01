"""环境变量与路径配置。"""

from __future__ import annotations

import os
from pathlib import Path


class Settings:
    # ── 鉴权 ──────────────────────────────────────────────
    api_key: str = os.getenv("MENGASR_API_KEY", "")

    # ── 模型路径 ──────────────────────────────────────────
    model_dir: Path = Path(os.getenv("MENGASR_MODEL_DIR", "/srv/mengasr/models"))
    mimo_model_path: str = os.getenv(
        "MENGASR_MIMO_MODEL",
        str(Path("/srv/mengasr/models/XiaomiMiMo/MiMo-V2.5-ASR")),
    )
    mimo_tokenizer_path: str = os.getenv(
        "MENGASR_MIMO_TOKENIZER",
        str(Path("/srv/mengasr/models/XiaomiMiMo/MiMo-Audio-Tokenizer")),
    )

    # ── MiMo 推理代码（sys.path 注入） ─────────────────────
    mimo_code_path: str = os.getenv(
        "MENGASR_MIMO_CODE",
        "/srv/mengasr/MiMo-V2.5-ASR-code",
    )

    # ── 服务端口 ──────────────────────────────────────────
    host: str = os.getenv("MENGASR_HOST", "0.0.0.0")
    port: int = int(os.getenv("MENGASR_PORT", "8787"))

    # ── 文件限制 ──────────────────────────────────────────
    max_upload_bytes: int = int(os.getenv("MENGASR_MAX_UPLOAD_MB", "2000")) * 1024 * 1024
    tmp_dir: Path = Path(os.getenv("MENGASR_TMP_DIR", "/tmp/mengasr"))
    tmp_dir.mkdir(parents=True, exist_ok=True)

    # ── FFmpeg ────────────────────────────────────────────
    ffmpeg_bin: str = os.getenv("MENGASR_FFMPEG", "ffmpeg")
    ffprobe_bin: str = os.getenv("MENGASR_FFPROBE", "ffprobe")

    # ── 任务队列 ──────────────────────────────────────────
    job_ttl_seconds: int = int(os.getenv("MENGASR_JOB_TTL_HOURS", "24")) * 3600
    job_max_queue: int = int(os.getenv("MENGASR_JOB_MAX_QUEUE", "20"))

    # ── 说话人分离 ──────────────────────────────────────────
    hf_token: str = os.getenv("MENGASR_HF_TOKEN", "")
    hf_endpoint: str = os.getenv("HF_ENDPOINT", "https://hf-mirror.com")


settings = Settings()
