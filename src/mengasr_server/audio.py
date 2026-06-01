"""FFmpeg 音频标准化与时长探测。"""

from __future__ import annotations

import asyncio
import logging
import subprocess
import tempfile
import uuid
from pathlib import Path

from .config import settings

logger = logging.getLogger("mengasr.audio")


async def normalize_to_wav(input_path: str | Path) -> Path:
    """将任意音频/视频文件转换为 16kHz mono WAV。

    Returns: 转换后的 WAV 文件路径（在 tmp_dir 中）。
    """
    output_path = settings.tmp_dir / f"{uuid.uuid4().hex}.wav"
    cmd = [
        settings.ffmpeg_bin,
        "-y",
        "-i", str(input_path),
        "-ac", "1",              # mono
        "-ar", "16000",          # 16kHz
        "-acodec", "pcm_s16le",  # 16-bit PCM
        "-f", "wav",
        str(output_path),
    ]

    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    _, stderr = await proc.communicate()

    if proc.returncode != 0:
        err = stderr.decode("utf-8", errors="replace")
        logger.error("ffmpeg 转换失败: %s", err)
        raise RuntimeError(f"FFmpeg conversion failed: {err}")

    return output_path


async def get_audio_duration(path: str | Path) -> float:
    """用 ffprobe 获取音频时长（秒）。"""
    cmd = [
        settings.ffprobe_bin,
        "-v", "error",
        "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1",
        str(path),
    ]
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate()

    if proc.returncode != 0:
        logger.warning("ffprobe 失败，跳过时长计算")
        return 0.0

    try:
        return float(stdout.decode().strip())
    except ValueError:
        return 0.0


def save_upload(upload_bytes: bytes, suffix: str = ".wav") -> Path:
    """将上传的文件字节保存到临时目录。"""
    path = settings.tmp_dir / f"{uuid.uuid4().hex}{suffix}"
    path.write_bytes(upload_bytes)
    return path


async def save_upload_streaming(file, suffix: str = ".wav") -> Path:
    """流式保存上传文件（避免将整个文件读入内存）。

    使用 shutil.copyfileobj 从 FastAPI 的临时文件直接写入磁盘，
    内存占用仅为一个 chunk 大小（默认 ~1MB），与文件大小无关。
    """
    import shutil

    path = settings.tmp_dir / f"{uuid.uuid4().hex}{suffix}"
    loop = asyncio.get_running_loop()

    def _copy():
        file.file.seek(0)
        with open(path, "wb") as out:
            shutil.copyfileobj(file.file, out, length=1024 * 1024)  # 1MB chunks

    await loop.run_in_executor(None, _copy)
    return path
