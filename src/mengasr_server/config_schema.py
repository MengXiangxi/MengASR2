"""MengASR2 配置加载器 — YAML 配置文件 + 环境变量覆盖。

配置文件路径：/srv/mengasr/mengasr.yaml（可通过 MENGASR_CONFIG 覆盖）

优先级：环境变量 > YAML 配置文件 > 默认值
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml


# ── 默认值 ──────────────────────────────────────────────────

DEFAULTS: dict[str, Any] = {
    "worker": {
        "backend": "mimo",
        "host": "127.0.0.1",
        "port": 8789,
        "mimo_model_path": "/srv/mengasr/models/XiaomiMiMo/MiMo-V2.5-ASR",
        "mimo_tokenizer_path": "/srv/mengasr/models/XiaomiMiMo/MiMo-Audio-Tokenizer",
        "mimo_code_path": "/srv/mengasr/MiMo-V2.5-ASR-code",
        "qwen3_model_id": "/srv/mengasr/models/Qwen/Qwen3-ASR-1___7B",
    },
    "listener": {
        "host": "0.0.0.0",
        "port": 8787,
        "max_upload_mb": 2000,
        "tmp_dir": "/tmp/mengasr",
    },
    "auth": {
        "api_key": "",
    },
    "jobs": {
        "ttl_hours": 24,
        "max_queue": 20,
    },
    "diarization": {
        "hf_token": "",
        "hf_endpoint": "https://hf-mirror.com",
    },
    "ffmpeg": {
        "bin": "ffmpeg",
        "ffprobe": "ffprobe",
    },
}


# ── YAML 加载 ───────────────────────────────────────────────

def _config_path() -> Path | None:
    """查找配置文件。"""
    # 1. 显式指定路径
    if path := os.getenv("MENGASR_CONFIG"):
        p = Path(path)
        if p.exists():
            return p
    # 2. 默认路径
    for candidate in [
        Path("/srv/mengasr/mengasr.yaml"),
        Path("mengasr.yaml"),
    ]:
        if candidate.exists():
            return candidate
    return None


def _load_yaml() -> dict[str, Any]:
    """加载 YAML 配置文件。"""
    path = _config_path()
    if not path:
        return {}
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def _deep_merge(base: dict, override: dict) -> dict:
    """深度合并两个字典。"""
    result = dict(base)
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def _env_overrides() -> dict[str, Any]:
    """从环境变量提取覆盖值。"""
    overrides: dict[str, Any] = {}

    def _set(path: list[str], env_var: str, convert=None):
        val = os.getenv(env_var)
        if val is not None:
            d = overrides
            for key in path[:-1]:
                d = d.setdefault(key, {})
            d[path[-1]] = convert(val) if convert else val

    _set(["auth", "api_key"], "MENGASR_API_KEY")
    _set(["worker", "backend"], "MENGASR_BACKEND")
    _set(["worker", "port"], "MENGASR_WORKER_PORT", int)
    _set(["worker", "mimo_model_path"], "MENGASR_MIMO_MODEL")
    _set(["worker", "mimo_tokenizer_path"], "MENGASR_MIMO_TOKENIZER")
    _set(["worker", "mimo_code_path"], "MENGASR_MIMO_CODE")
    _set(["listener", "host"], "MENGASR_HOST")
    _set(["listener", "port"], "MENGASR_PORT", int)
    _set(["listener", "max_upload_mb"], "MENGASR_MAX_UPLOAD_MB", int)
    _set(["listener", "tmp_dir"], "MENGASR_TMP_DIR")
    _set(["jobs", "ttl_hours"], "MENGASR_JOB_TTL_HOURS", int)
    _set(["jobs", "max_queue"], "MENGASR_JOB_MAX_QUEUE", int)
    _set(["diarization", "hf_token"], "MENGASR_HF_TOKEN")
    _set(["diarization", "hf_endpoint"], "HF_ENDPOINT")
    _set(["ffmpeg", "bin"], "MENGASR_FFMPEG")
    _set(["ffmpeg", "ffprobe"], "MENGASR_FFPROBE")

    return overrides


# ── 公开接口 ─────────────────────────────────────────────────

def load_config() -> dict[str, Any]:
    """加载完整配置（YAML + 环境变量覆盖）。"""
    config = dict(DEFAULTS)
    config = _deep_merge(config, _load_yaml())
    config = _deep_merge(config, _env_overrides())
    return config


def get_listener_config(config: dict[str, Any] | None = None) -> dict[str, Any]:
    """提取 Listener 进程需要的配置。"""
    if config is None:
        config = load_config()
    worker = config["worker"]
    return {
        **config["listener"],
        "api_key": config["auth"]["api_key"],
        "tmp_dir": config["listener"]["tmp_dir"],
        "max_upload_bytes": config["listener"]["max_upload_mb"] * 1024 * 1024,
        "ffmpeg_bin": config["ffmpeg"]["bin"],
        "ffprobe_bin": config["ffmpeg"]["ffprobe"],
        "job_ttl_seconds": config["jobs"]["ttl_hours"] * 3600,
        "job_max_queue": config["jobs"]["max_queue"],
        "worker_url": f"http://{worker['host']}:{worker['port']}",
    }


def get_worker_config(config: dict[str, Any] | None = None) -> dict[str, Any]:
    """提取 Worker 进程需要的配置。"""
    if config is None:
        config = load_config()
    worker = config["worker"]
    return {
        "backend": worker["backend"],
        "host": worker["host"],
        "port": worker["port"],
        "mimo_model_path": worker["mimo_model_path"],
        "mimo_tokenizer_path": worker["mimo_tokenizer_path"],
        "mimo_code_path": worker["mimo_code_path"],
        "qwen3_model_id": worker["qwen3_model_id"],
        "hf_token": config["diarization"]["hf_token"],
        "hf_endpoint": config["diarization"]["hf_endpoint"],
        "ffmpeg_bin": config["ffmpeg"]["bin"],
        "ffprobe_bin": config["ffmpeg"]["ffprobe"],
        "tmp_dir": config["listener"]["tmp_dir"],
    }
