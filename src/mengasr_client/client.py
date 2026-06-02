"""MengASR2 服务端 HTTP 客户端。"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any, Optional

import httpx

logger = logging.getLogger("mengasr.client")


class MengASRClient:
    """MengASR2 服务端 HTTP 客户端。

    支持：
    - 同步转写（POST /v1/audio/transcriptions）
    - 异步任务（POST /v1/jobs → 轮询 → 下载结果）
    - 健康检查（GET /health）
    """

    def __init__(
        self,
        server_url: str = "http://localhost:8787",
        api_key: str = "",
        timeout: float = 600.0,
    ):
        self.server_url = server_url.rstrip("/")
        self.api_key = api_key
        self.timeout = timeout

    def _headers(self) -> dict[str, str]:
        headers = {}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    # ── 健康检查 ─────────────────────────────────────────────

    def health(self) -> dict:
        """检查服务端健康状态。"""
        resp = httpx.get(
            f"{self.server_url}/health",
            headers=self._headers(),
            timeout=10.0,
        )
        resp.raise_for_status()
        return resp.json()

    # ── 同步转写 ─────────────────────────────────────────────

    def transcribe(
        self,
        file_path: str | Path,
        *,
        language: str = "auto",
        response_format: str = "json",
        timestamps: str = "none",
        diarization: bool = False,
        num_speakers: int = 0,
        model: str = "mimo-v2.5-asr",
    ) -> dict | str:
        """同步转写音频文件。

        Args:
            file_path: 音频/视频文件路径
            language: 语言 (auto/chinese/english)
            response_format: 响应格式 (json/text/srt/vtt)
            timestamps: 时间戳 (none/segment)
            diarization: 是否启用说话人分离
            num_speakers: 说话人数量 (0=自动)
            model: 模型标识

        Returns:
            response_format=json → dict
            response_format=text/srt/vtt → str
        """
        file_path = Path(file_path)
        if not file_path.exists():
            raise FileNotFoundError(f"文件不存在: {file_path}")

        data = {
            "model": model,
            "language": language,
            "response_format": response_format,
            "timestamps": timestamps,
            "diarization": "true" if diarization else "false",
            "num_speakers": str(num_speakers),
        }

        logger.info("同步转写: %s (%.1f MB)", file_path.name, file_path.stat().st_size / 1024 / 1024)

        with open(file_path, "rb") as f:
            resp = httpx.post(
                f"{self.server_url}/v1/audio/transcriptions",
                headers=self._headers(),
                data=data,
                files={"file": (file_path.name, f)},
                timeout=self.timeout,
            )

        resp.raise_for_status()

        if response_format == "json":
            return resp.json()
        return resp.text

    # ── 异步任务 ─────────────────────────────────────────────

    def submit_job(
        self,
        file_path: str | Path,
        *,
        language: str = "auto",
        response_format: str = "json",
        timestamps: str = "none",
        diarization: bool = False,
        num_speakers: int = 0,
    ) -> str:
        """提交异步转写任务。

        Returns:
            job_id: 任务 ID
        """
        file_path = Path(file_path)
        if not file_path.exists():
            raise FileNotFoundError(f"文件不存在: {file_path}")

        data = {
            "language": language,
            "response_format": response_format,
            "timestamps": timestamps,
            "diarization": "true" if diarization else "false",
            "num_speakers": str(num_speakers),
        }

        logger.info("提交异步任务: %s (%.1f MB)", file_path.name, file_path.stat().st_size / 1024 / 1024)

        with open(file_path, "rb") as f:
            resp = httpx.post(
                f"{self.server_url}/v1/jobs",
                headers=self._headers(),
                data=data,
                files={"file": (file_path.name, f)},
                timeout=self.timeout,
            )

        resp.raise_for_status()
        result = resp.json()
        job_id = result["job_id"]
        logger.info("任务已创建: %s (status=%s)", job_id, result["status"])
        return job_id

    def get_job_status(self, job_id: str) -> dict:
        """查询任务状态。"""
        resp = httpx.get(
            f"{self.server_url}/v1/jobs/{job_id}",
            headers=self._headers(),
            timeout=30.0,
        )
        resp.raise_for_status()
        return resp.json()

    def get_job_result(
        self,
        job_id: str,
        *,
        response_format: str = "json",
    ) -> dict | str:
        """下载任务结果。

        Args:
            job_id: 任务 ID
            response_format: json / text / srt / vtt

        Returns:
            response_format=json → dict
            其他 → str
        """
        resp = httpx.get(
            f"{self.server_url}/v1/jobs/{job_id}/result",
            params={"response_format": response_format},
            headers=self._headers(),
            timeout=30.0,
        )
        resp.raise_for_status()

        if response_format == "json":
            return resp.json()
        return resp.text

    def list_jobs(self, limit: int = 20) -> dict:
        """列出最近的任务。"""
        resp = httpx.get(
            f"{self.server_url}/v1/jobs",
            params={"limit": str(limit)},
            headers=self._headers(),
            timeout=30.0,
        )
        resp.raise_for_status()
        return resp.json()

    def delete_job(self, job_id: str) -> dict:
        """取消或删除任务。"""
        resp = httpx.delete(
            f"{self.server_url}/v1/jobs/{job_id}",
            headers=self._headers(),
            timeout=30.0,
        )
        resp.raise_for_status()
        return resp.json()

    def wait_for_job(
        self,
        job_id: str,
        *,
        poll_interval: float = 2.0,
        max_wait: float = 600.0,
        on_status: Callable[[str, dict[str, Any]], None] | None = None,
    ) -> dict:
        """轮询等待任务完成。

        Args:
            job_id: 任务 ID
            poll_interval: 轮询间隔（秒）
            max_wait: 最大等待时间（秒）
            on_status: 状态回调函数，接收 (job_id, status_dict)

        Returns:
            最终任务状态 dict

        Raises:
            TimeoutError: 超过最大等待时间
            RuntimeError: 任务失败或取消
        """
        start = time.monotonic()
        while True:
            status = self.get_job_status(job_id)

            if on_status:
                on_status(job_id, status)

            job_status = status["status"]

            if job_status == "completed":
                logger.info("任务 %s 完成", job_id)
                return status

            if job_status == "failed":
                raise RuntimeError(f"任务 {job_id} 失败: {status.get('error', '未知错误')}")

            if job_status == "cancelled":
                raise RuntimeError(f"任务 {job_id} 已被取消")

            elapsed = time.monotonic() - start
            if elapsed > max_wait:
                raise TimeoutError(f"任务 {job_id} 等待超时 ({max_wait:.0f}s)")

            logger.debug(
                "任务 %s 状态: %s (已等待 %.0fs)",
                job_id, job_status, elapsed,
            )
            time.sleep(poll_interval)

    # ── 便捷方法 ─────────────────────────────────────────────

    def transcribe_file(
        self,
        file_path: str | Path,
        *,
        language: str = "auto",
        timestamps: str = "none",
        diarization: bool = False,
        num_speakers: int = 0,
        async_mode: bool = False,
        output_format: str = "json",
        output_path: Optional[str | Path] = None,
        poll_interval: float = 2.0,
    ) -> str | dict:
        """转写音频文件的便捷方法。

        自动选择同步/异步模式，可选择保存结果到文件。

        Args:
            file_path: 音频/视频文件路径
            language: 语言
            timestamps: 时间戳 (none/segment)
            diarization: 说话人分离
            num_speakers: 说话人数量
            async_mode: 使用异步任务模式
            output_format: 输出格式 (json/text/srt/vtt)
            output_path: 输出文件路径（为 None 时不保存文件）
            poll_interval: 异步模式轮询间隔

        Returns:
            如果 output_path 为 None: 返回结果文本或 dict
            如果 output_path 不为 None: 返回保存的文件路径
        """
        file_path = Path(file_path)

        if async_mode:
            # 异步模式：提交 → 等待 → 下载
            job_id = self.submit_job(
                file_path,
                language=language,
                response_format=output_format,
                timestamps=timestamps,
                diarization=diarization,
                num_speakers=num_speakers,
            )
            self.wait_for_job(job_id, poll_interval=poll_interval)
            result = self.get_job_result(job_id, response_format=output_format)
        else:
            # 同步模式
            result = self.transcribe(
                file_path,
                language=language,
                response_format=output_format,
                timestamps=timestamps,
                diarization=diarization,
                num_speakers=num_speakers,
            )

        # 保存到文件
        if output_path:
            output_path = Path(output_path)
            output_path.parent.mkdir(parents=True, exist_ok=True)

            if isinstance(result, dict):
                import json
                output_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
            else:
                output_path.write_text(result, encoding="utf-8")

            logger.info("结果已保存: %s", output_path)
            return str(output_path)

        return result
