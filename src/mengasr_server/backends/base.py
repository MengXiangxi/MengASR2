"""ASR 后端抽象基类。"""

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path
from typing import NamedTuple


class SegmentResult(NamedTuple):
    """带时间戳的转写结果。"""
    start: float
    end: float
    text: str


class ASRBackend(ABC):
    """所有 ASR 后端的抽象接口。"""

    @abstractmethod
    async def load(self) -> None:
        """加载模型到 GPU / 内存。"""
        ...

    @abstractmethod
    async def transcribe(
        self,
        audio_path: Path,
        language: str = "auto",
    ) -> str:
        """转写音频文件，返回纯文本。"""
        ...

    async def transcribe_segments(
        self,
        audio_path: Path,
        language: str = "auto",
    ) -> list[SegmentResult]:
        """带 VAD 时间戳的转写。默认降级为整体转写。"""
        text = await self.transcribe(audio_path, language)
        return [SegmentResult(start=0.0, end=0.0, text=text)]

    @abstractmethod
    def is_loaded(self) -> bool:
        """模型是否已加载。"""
        ...

    @abstractmethod
    def model_id(self) -> str:
        """模型标识（用于 /v1/models）。"""
        ...

    @abstractmethod
    async def unload(self) -> None:
        """释放模型资源。"""
        ...
