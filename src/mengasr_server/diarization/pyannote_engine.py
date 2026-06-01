"""pyannote.audio 说话人分离引擎。

使用 pyannote/speaker-diarization-community-1 pipeline。
通过 torchaudio 加载音频（绕过 torchcodec 兼容问题）。
"""

from __future__ import annotations

import asyncio
import logging
import os
from dataclasses import dataclass

import torch
import torchaudio

logger = logging.getLogger("mengasr.diarization")


@dataclass
class SpeakerTurn:
    """一个说话人片段。"""
    start: float
    end: float
    speaker: str


class PyannoteDiarizer:
    """pyannote 说话人分离器（延迟加载）。"""

    def __init__(self, hf_token: str, hf_endpoint: str = "https://hf-mirror.com"):
        self._hf_token = hf_token
        self._hf_endpoint = hf_endpoint
        self._pipeline = None
        self._loaded = False
        self._gpu_lock = asyncio.Lock()

    async def load(self) -> None:
        if self._loaded:
            return

        loop = asyncio.get_running_loop()

        def _load():
            os.environ["HF_ENDPOINT"] = self._hf_endpoint
            from pyannote.audio import Pipeline

            logger.info("加载 pyannote diarization pipeline……")
            pipeline = Pipeline.from_pretrained(
                "pyannote/speaker-diarization-community-1",
                token=self._hf_token,
            )
            pipeline.to(torch.device("cuda" if torch.cuda.is_available() else "cpu"))
            logger.info("pyannote pipeline 加载完成")
            return pipeline

        self._pipeline = await loop.run_in_executor(None, _load)
        self._loaded = True

    def is_loaded(self) -> bool:
        return self._loaded

    async def diarize(
        self,
        audio_path: str,
        num_speakers: int | None = None,
    ) -> list[SpeakerTurn]:
        """执行说话人分离。

        Args:
            audio_path: 音频文件路径（16kHz mono WAV）
            num_speakers: 可选，指定说话人数量

        Returns:
            SpeakerTurn 列表，按时间排序
        """
        if not self._loaded or self._pipeline is None:
            raise RuntimeError("pyannote pipeline 未加载")

        async with self._gpu_lock:
            loop = asyncio.get_running_loop()

            def _run():
                # 用 torchaudio 加载（绕过 torchcodec）
                wav, sr = torchaudio.load(audio_path)
                if sr != 16000:
                    wav = torchaudio.functional.resample(wav, sr, 16000)
                if wav.shape[0] > 1:
                    wav = wav.mean(dim=0, keepdim=True)
                audio_input = {"waveform": wav, "sample_rate": 16000}

                kwargs = {}
                if num_speakers is not None:
                    kwargs["num_speakers"] = num_speakers

                result = self._pipeline(audio_input, **kwargs)
                annotation = result.speaker_diarization

                turns = []
                for turn, _, speaker in annotation.itertracks(yield_label=True):
                    turns.append(SpeakerTurn(
                        start=turn.start,
                        end=turn.end,
                        speaker=speaker,
                    ))
                return turns

            turns = await loop.run_in_executor(None, _run)

        logger.info("说话人分离完成：%d 个片段", len(turns))
        return turns


def assign_speakers_to_segments(
    segments: list,
    speaker_turns: list[SpeakerTurn],
) -> list[str]:
    """将说话人标签分配给 ASR segments。

    使用时间重叠投票：对每个 ASR segment，找到与其时间重叠最大的说话人。

    Args:
        segments: ASR segments（需有 start/end 属性）
        speaker_turns: 说话人片段列表

    Returns:
        与 segments 等长的 speaker 标签列表
    """
    speakers = []
    for seg in segments:
        seg_start = seg.start
        seg_end = seg.end

        # 统计每个说话人与当前 segment 的重叠时长
        overlap: dict[str, float] = {}
        for turn in speaker_turns:
            # 计算重叠
            overlap_start = max(seg_start, turn.start)
            overlap_end = min(seg_end, turn.end)
            if overlap_start < overlap_end:
                duration = overlap_end - overlap_start
                overlap[turn.speaker] = overlap.get(turn.speaker, 0.0) + duration

        if overlap:
            # 选择重叠最大的说话人
            best_speaker = max(overlap, key=overlap.get)
            speakers.append(best_speaker)
        else:
            speakers.append("unknown")

    return speakers
