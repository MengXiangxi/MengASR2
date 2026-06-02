"""异步任务队列：JobStore + JobWorker。

设计：
- JobStore：内存 dict + JSON 持久化，管理任务生命周期
- JobWorker：后台协程，从 asyncio.Queue 取任务执行推理
- GPU 推理串行：复用 backend 的 gpu_lock
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Optional

from .config import settings

logger = logging.getLogger("mengasr.jobs")


# ── 任务状态 ───────────────────────────────────────────────

class JobStatus(str, Enum):
    queued = "queued"
    running = "running"
    completed = "completed"
    failed = "failed"
    cancelled = "cancelled"
    expired = "expired"


# ── 任务数据 ───────────────────────────────────────────────

@dataclass
class Job:
    job_id: str
    status: JobStatus = JobStatus.queued
    created_at: str = ""
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    language: str = "auto"
    response_format: str = "json"
    timestamps: str = "none"
    diarization: bool = False
    num_speakers: int = 0
    filename: Optional[str] = None
    duration: Optional[float] = None        # 音频时长
    text: Optional[str] = None              # 转写结果
    segments: Optional[list[dict]] = None   # 段落时间戳
    error: Optional[str] = None             # 失败原因
    result_path: Optional[str] = None       # 结果文件路径

    def __post_init__(self):
        if not self.created_at:
            self.created_at = _now_iso()

    def to_public(self) -> dict:
        """返回公开视图（不含内部路径）。"""
        d = asdict(self)
        d.pop("result_path", None)
        return d


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ── 任务存储 ───────────────────────────────────────────────

class JobStore:
    """内存任务存储 + JSON 文件持久化。"""

    def __init__(self, persist_path: Path | None = None):
        self._jobs: dict[str, Job] = {}
        self._persist_path = persist_path or (settings.tmp_dir / "jobs.json")
        self._load()

    def create(self, language: str, response_format: str, filename: str | None, timestamps: str = "none", diarization: bool = False, num_speakers: int = 0) -> Job:
        job_id = uuid.uuid4().hex[:12]
        job = Job(
            job_id=job_id,
            language=language,
            response_format=response_format,
            timestamps=timestamps,
            diarization=diarization,
            num_speakers=num_speakers,
            filename=filename,
        )
        self._jobs[job_id] = job
        self._save()
        logger.info("任务创建: %s (%s)", job_id, filename)
        return job

    def get(self, job_id: str) -> Job | None:
        return self._jobs.get(job_id)

    def list_jobs(self, limit: int = 50) -> list[dict]:
        jobs = sorted(self._jobs.values(), key=lambda j: j.created_at, reverse=True)
        return [j.to_public() for j in jobs[:limit]]

    def update(self, job: Job) -> None:
        self._jobs[job.job_id] = job
        self._save()

    def cancel(self, job_id: str) -> bool:
        job = self._jobs.get(job_id)
        if not job:
            return False
        if job.status in (JobStatus.queued,):
            job.status = JobStatus.cancelled
            job.completed_at = _now_iso()
            self._save()
            return True
        return False

    def delete(self, job_id: str) -> bool:
        job = self._jobs.pop(job_id, None)
        if job:
            # 清理结果文件
            if job.result_path:
                p = Path(job.result_path)
                if p.exists():
                    p.unlink(missing_ok=True)
            self._save()
            return True
        return False

    def expire_old(self, ttl_seconds: int = 86400) -> int:
        """过期并清理超过 TTL 的已完成/失败任务。"""
        now = time.time()
        expired = []
        for job_id, job in list(self._jobs.items()):
            if job.status in (JobStatus.completed, JobStatus.failed, JobStatus.cancelled, JobStatus.expired):
                if job.completed_at:
                    try:
                        ct = datetime.fromisoformat(job.completed_at).timestamp()
                        if now - ct > ttl_seconds:
                            expired.append(job_id)
                    except (ValueError, OSError):
                        pass
        for jid in expired:
            self.delete(jid)
        if expired:
            logger.info("过期清理 %d 个任务", len(expired))
        return len(expired)

    def queued_count(self) -> int:
        return sum(1 for j in self._jobs.values() if j.status == JobStatus.queued)

    # ── 持久化 ─────────────────────────────────────────────

    def _save(self) -> None:
        try:
            data = {jid: asdict(job) for jid, job in self._jobs.items()}
            self._persist_path.write_text(json.dumps(data, ensure_ascii=False, indent=2))
        except OSError as e:
            logger.warning("持久化失败: %s", e)

    def _load(self) -> None:
        if not self._persist_path.exists():
            return
        try:
            data = json.loads(self._persist_path.read_text())
            for jid, d in data.items():
                d["status"] = JobStatus(d["status"])
                self._jobs[jid] = Job(**d)
            logger.info("从持久化加载 %d 个任务", len(self._jobs))
        except (json.JSONDecodeError, TypeError) as e:
            logger.warning("持久化文件损坏，忽略: %s", e)


# ── 后台 Worker ────────────────────────────────────────────

class JobWorker:
    """后台协程：从队列取任务执行推理。"""

    def __init__(self, store: JobStore, worker: Any):
        """worker 可以是 WorkerClient（listener 模式）或 ASRBackend（单体模式）。"""
        self.store = store
        self.worker = worker  # WorkerClient | ASRBackend
        self.queue: asyncio.Queue[str] = asyncio.Queue()
        self._task: asyncio.Task | None = None
        self._stop = False

    async def start(self) -> None:
        self._stop = False
        self._task = asyncio.create_task(self._run(), name="job-worker")
        logger.info("任务 Worker 已启动")

    async def stop(self) -> None:
        self._stop = True
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("任务 Worker 已停止")

    async def enqueue(self, job_id: str) -> None:
        await self.queue.put(job_id)

    async def _run(self) -> None:
        while not self._stop:
            try:
                job_id = await asyncio.wait_for(self.queue.get(), timeout=5.0)
            except asyncio.TimeoutError:
                # 空闲时清理过期任务
                self.store.expire_old()
                continue

            job = self.store.get(job_id)
            if not job or job.status == JobStatus.cancelled:
                continue

            await self._process(job)

    async def _process(self, job: Job) -> None:
        from .audio import get_audio_duration, normalize_to_wav
        from .worker_client import WorkerClient

        job.status = JobStatus.running
        job.started_at = _now_iso()
        self.store.update(job)
        logger.info("开始处理任务: %s (%s)", job.job_id, job.filename)

        tmp_input: Path | None = None
        tmp_wav: Path | None = None

        try:
            # 查找上传的临时文件
            tmp_input = settings.tmp_dir / f"job_{job.job_id}"
            if not tmp_input.exists():
                for suffix in (".wav", ".mp3", ".m4a", ".ogg", ".flac", ".mp4", ".webm"):
                    candidate = settings.tmp_dir / f"job_{job.job_id}{suffix}"
                    if candidate.exists():
                        tmp_input = candidate
                        break
                else:
                    raise FileNotFoundError(f"任务 {job.job_id} 的音频文件不存在")

            # FFmpeg 标准化
            tmp_wav = await normalize_to_wav(tmp_input)
            job.duration = await get_audio_duration(tmp_wav)

            # 推理：WorkerClient（新架构）或 ASRBackend（旧架构）
            if isinstance(self.worker, WorkerClient):
                # ── 新架构：委托给 Worker 进程 ──────────────
                result = await self.worker.ainfer(
                    tmp_wav,
                    language=job.language,
                    timestamps=job.timestamps,
                    diarization=job.diarization,
                    num_speakers=job.num_speakers,
                )
                text = result.get("text", "")
                if result.get("segments"):
                    job.segments = result["segments"]
                logger.info("任务 %s Worker 推理完成: infer=%ss",
                            job.job_id, result.get("inference_time"))
            else:
                # ── 旧架构：直接调用 backend ──────────────
                start = time.monotonic()
                if job.timestamps == "segment":
                    seg_results = await self.worker.transcribe_segments(tmp_wav, language=job.language)
                    text = " ".join(s.text for s in seg_results)
                    job.segments = [{"start": s.start, "end": s.end, "text": s.text} for s in seg_results]
                else:
                    text = await self.worker.transcribe(tmp_wav, language=job.language)
                elapsed = time.monotonic() - start
                logger.info("任务 %s 推理完成: %.2fs", job.job_id, elapsed)

            # 保存结果
            job.text = text
            if job.response_format == "srt" and job.segments:
                from .formatters.srt import format_srt
                from .schemas import Segment
                srt_segments = [Segment(**s) for s in job.segments]
                result_content = format_srt(srt_segments)
                ext = ".srt"
            elif job.response_format == "vtt" and job.segments:
                from .formatters.vtt import format_vtt
                from .schemas import Segment
                vtt_segments = [Segment(**s) for s in job.segments]
                result_content = format_vtt(vtt_segments)
                ext = ".vtt"
            else:
                result_content = text
                ext = ".txt"
            result_path = settings.tmp_dir / f"result_{job.job_id}{ext}"
            result_path.write_text(result_content, encoding="utf-8")
            job.result_path = str(result_path)

            job.status = JobStatus.completed
            job.completed_at = _now_iso()
            self.store.update(job)

        except Exception as e:
            logger.error("任务 %s 失败: %s", job.job_id, e, exc_info=True)
            job.status = JobStatus.failed
            job.error = str(e)
            job.completed_at = _now_iso()
            self.store.update(job)

        finally:
            if tmp_input and tmp_input.exists():
                tmp_input.unlink(missing_ok=True)
            if tmp_wav and tmp_wav.exists():
                tmp_wav.unlink(missing_ok=True)
