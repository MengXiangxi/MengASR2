"""请求 / 响应 Pydantic 模型。"""

from __future__ import annotations

from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


# ── 语言 ───────────────────────────────────────────────────
class Language(str, Enum):
    auto = "auto"
    chinese = "chinese"
    english = "english"


# ── 响应格式 ───────────────────────────────────────────────
class ResponseFormat(str, Enum):
    json_ = "json"
    text = "text"
    verbose_json = "verbose_json"


# ── POST /v1/audio/transcriptions 请求 ─────────────────────
# multipart/form-data，字段由 FastAPI Form() 声明


# ── 响应模型 ───────────────────────────────────────────────
class Segment(BaseModel):
    """一个带时间戳的转写片段。"""
    start: float = Field(..., description="起始时间（秒）")
    end: float = Field(..., description="结束时间（秒）")
    text: str = Field(..., description="片段文本")
    speaker: Optional[str] = Field(None, description="说话人标签（需 diarization=true）")


class TranscriptionResult(BaseModel):
    text: str = Field(..., description="转写文本")
    language: Optional[str] = Field(None, description="检测到的语言")
    duration: Optional[float] = Field(None, description="音频时长（秒）")
    model: str = Field("mimo-v2.5-asr", description="使用的模型")
    segments: Optional[list[Segment]] = Field(None, description="句段时间戳（需 timestamps=segment）")


class ModelInfo(BaseModel):
    id: str
    object: str = "model"
    owned_by: str = "mengasr"


class ModelList(BaseModel):
    object: str = "list"
    data: list[ModelInfo]


class HealthResponse(BaseModel):
    status: str = "ok"
    model_loaded: bool = False
    gpu_available: bool = False


class ErrorResponse(BaseModel):
    error: str
    detail: Optional[str] = None


# ── 异步任务 ───────────────────────────────────────────────

class JobCreate(BaseModel):
    """POST /v1/jobs 响应。"""
    job_id: str = Field(..., description="任务 ID")
    status: str = Field("queued", description="任务状态")
    created_at: str = Field(..., description="创建时间 (ISO 8601)")


class JobStatus(BaseModel):
    """GET /v1/jobs/{id} 响应。"""
    job_id: str
    status: str
    created_at: str
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    language: Optional[str] = None
    filename: Optional[str] = None
    duration: Optional[float] = Field(None, description="音频时长（秒）")
    text: Optional[str] = Field(None, description="转写结果（completed 时有值）")
    segments: Optional[list[Segment]] = Field(None, description="句段时间戳")
    diarization: Optional[bool] = Field(None, description="是否启用说话人分离")
    error: Optional[str] = Field(None, description="错误信息（failed 时有值）")


class JobList(BaseModel):
    """GET /v1/jobs 响应。"""
    object: str = "list"
    data: list[JobStatus]
