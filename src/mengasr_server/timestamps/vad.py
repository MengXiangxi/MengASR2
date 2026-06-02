"""Silero VAD 语音活动检测 → 音频分段。

使用 torch.hub 加载 Silero VAD 模型（snakers4/silero-vad）。
返回语音片段的时间边界（秒）。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

import torch
import torchaudio

logger = logging.getLogger("mengasr.vad")


@dataclass
class SpeechSegment:
    """一个语音片段。"""
    start: float  # 起始时间（秒）
    end: float    # 结束时间（秒）


class VADSegmenter:
    """Silero VAD 语音分段器。"""

    def __init__(self, sample_rate: int = 16000):
        self.sample_rate = sample_rate
        self._model: Any = None

    def _ensure_model(self) -> None:
        """延迟加载 Silero VAD 模型。"""
        if self._model is not None:
            return
        logger.info("加载 Silero VAD 模型……")
        self._model, _ = torch.hub.load(
            repo_or_dir="snakers4/silero-vad",
            model="silero_vad",
            trust_repo=True,
        )
        logger.info("Silero VAD 模型加载完成")

    def detect_speech(
        self,
        audio_path: str,
        threshold: float = 0.5,
        min_speech_ms: int = 250,
        min_silence_ms: int = 100,
        speech_pad_ms: int = 30,
    ) -> list[SpeechSegment]:
        """检测音频中的语音片段。

        Args:
            audio_path: WAV 文件路径（应为 16kHz mono）
            threshold: VAD 概率阈值
            min_speech_ms: 最短语音段（过短则丢弃）
            min_silence_ms: 最短静音间隔（用于分段）
            speech_pad_ms: 语音段两端填充

        Returns:
            SpeechSegment 列表，按时间排序
        """
        self._ensure_model()

        # 加载音频
        wav, sr = torchaudio.load(audio_path)
        if wav.ndim == 2:
            wav = wav.mean(dim=0)

        # 重采样到目标采样率
        if sr != self.sample_rate:
            wav = torchaudio.functional.resample(wav, sr, self.sample_rate)

        # 获取语音时间戳
        from silero_vad import get_speech_timestamps

        speech_timestamps = get_speech_timestamps(
            wav,
            self._model,
            threshold=threshold,
            min_speech_duration_ms=min_speech_ms,
            min_silence_duration_ms=min_silence_ms,
            speech_pad_ms=speech_pad_ms,
            return_seconds=True,
            sampling_rate=self.sample_rate,
        )

        segments = [
            SpeechSegment(start=ts["start"], end=ts["end"])
            for ts in speech_timestamps
        ]

        logger.info(
            "VAD 检测到 %d 个语音段，总时长 %.1fs",
            len(segments),
            sum(s.end - s.start for s in segments),
        )

        return segments
