"""Listener → Worker HTTP 客户端。

Listener 通过此客户端与 Worker 进程通信。
Worker 运行在 localhost 上，暴露 /health 和 /infer 接口。
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import httpx

logger = logging.getLogger("mengasr.worker_client")


class WorkerClient:
    """Worker 进程的 HTTP 客户端。

    负责：
    - 健康检查
    - 发送已预处理的 WAV + 参数到 Worker 做推理
    """

    def __init__(self, worker_url: str, timeout: float = 600.0):
        self.worker_url = worker_url.rstrip("/")
        self.timeout = timeout

    # ── 健康检查 ─────────────────────────────────────────────

    def health(self) -> dict[str, Any]:
        """检查 Worker 健康状态。"""
        resp = httpx.get(
            f"{self.worker_url}/health",
            timeout=10.0,
        )
        resp.raise_for_status()
        return resp.json()

    async def ahealth(self) -> dict[str, Any]:
        """异步检查 Worker 健康状态。"""
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"{self.worker_url}/health",
                timeout=10.0,
            )
            resp.raise_for_status()
            return resp.json()

    # ── 推理 ─────────────────────────────────────────────────

    def infer(
        self,
        wav_path: str | Path,
        *,
        language: str = "auto",
        timestamps: str = "none",
        diarization: bool = False,
        num_speakers: int = 0,
    ) -> dict[str, Any]:
        """同步：提交已预处理的 WAV 到 Worker 做推理。

        Args:
            wav_path: 16kHz mono WAV 文件路径
            language: auto / chinese / english
            timestamps: none / segment
            diarization: 是否启用说话人分离
            num_speakers: 说话人数量（0=自动）

        Returns:
            {
                "text": "...",
                "duration": 72.1,
                "model": "mimo-v2.5-asr",
                "backend": "mimo",
                "inference_time": 9.31,
                "segments": [{"start": 0.1, "end": 1.5, "text": "...", "speaker": "SPEAKER_00"}]
            }
        """
        wav_path = Path(wav_path)
        data = {
            "language": language,
            "timestamps": timestamps,
            "diarization": "true" if diarization else "false",
            "num_speakers": str(num_speakers),
        }

        with open(wav_path, "rb") as f:
            resp = httpx.post(
                f"{self.worker_url}/infer",
                data=data,
                files={"file": (wav_path.name, f)},
                timeout=self.timeout,
            )

        resp.raise_for_status()
        return resp.json()

    async def ainfer(
        self,
        wav_path: str | Path,
        *,
        language: str = "auto",
        timestamps: str = "none",
        diarization: bool = False,
        num_speakers: int = 0,
    ) -> dict[str, Any]:
        """异步：提交已预处理的 WAV 到 Worker 做推理。"""
        wav_path = Path(wav_path)
        data = {
            "language": language,
            "timestamps": timestamps,
            "diarization": "true" if diarization else "false",
            "num_speakers": str(num_speakers),
        }

        async with httpx.AsyncClient() as client:
            with open(wav_path, "rb") as f:
                resp = await client.post(
                    f"{self.worker_url}/infer",
                    data=data,
                    files={"file": (wav_path.name, f)},
                    timeout=self.timeout,
                )

            resp.raise_for_status()
            return resp.json()
