"""Qwen3-ASR 后端实现。

使用 qwen-asr 官方包 (transformers >= 4.57.0)。
支持原生时间戳（通过 return_time_stamps=True）。
部署在独立的 .venv-qwen3asr 中（transformers 4.57 vs MiMo 的 4.49 不兼容）。
"""

from __future__ import annotations

import asyncio
import logging
import os
from pathlib import Path

from .base import ASRBackend, SegmentResult

logger = logging.getLogger("mengasr.backends.qwen3")


class Qwen3ASRBackend(ASRBackend):
    """Qwen3-ASR-1.7B 后端。

    使用 qwen_asr.Qwen3ASRModel，支持：
    - 52 种语言的自动检测
    - 原生 segment/word 级时间戳
    - BF16 推理，约 4-5GB VRAM
    """

    def __init__(self, model_path: str = "/srv/mengasr/models/Qwen/Qwen3-ASR-1___7B"):
        self._model_path = model_path
        self._model = None
        self._loaded = False
        self._gpu_lock = asyncio.Lock()

    # ── 生命周期 ───────────────────────────────────────────

    async def load(self) -> None:
        if self._loaded:
            return

        loop = asyncio.get_running_loop()

        def _load():
            import torch
            from qwen_asr import Qwen3ASRModel

            logger.info("加载 Qwen3-ASR 模型: %s", self._model_path)
            model = Qwen3ASRModel.from_pretrained(
                self._model_path,
                dtype=torch.bfloat16,
                device_map="auto",
            )
            logger.info("Qwen3-ASR 模型加载完成")
            return model

        self._model = await loop.run_in_executor(None, _load)
        self._loaded = True

    async def unload(self) -> None:
        if self._model is not None:
            del self._model
            self._model = None
            self._loaded = False
            import torch
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
            logger.info("Qwen3-ASR 模型已释放")

    def is_loaded(self) -> bool:
        return self._loaded

    def model_id(self) -> str:
        return "qwen3-asr-1.7b"

    # ── 推理 ───────────────────────────────────────────────

    async def transcribe(
        self,
        audio_path: Path,
        language: str = "auto",
    ) -> str:
        """整体转写，返回纯文本。"""
        if not self._loaded or self._model is None:
            raise RuntimeError("Qwen3-ASR 模型未加载")

        lang = None if language == "auto" else language

        async with self._gpu_lock:
            loop = asyncio.get_running_loop()

            def _run():
                result = self._model.transcribe(
                    audio=str(audio_path),
                    language=lang,
                    return_time_stamps=False,
                )
                return result[0].text if isinstance(result, list) else result.text

            text = await loop.run_in_executor(None, _run)

        return text

    async def transcribe_segments(
        self,
        audio_path: Path,
        language: str = "auto",
    ) -> list[SegmentResult]:
        """带时间戳的转写（Silero VAD 分段）。

        Qwen3-ASR 原生时间戳需要 ForcedAligner-0.6B（~1.2GB，待后续下载）。
        当前使用 Silero VAD 降级方案。
        """
        if not self._loaded or self._model is None:
            raise RuntimeError("Qwen3-ASR 模型未加载")

        from ..timestamps.vad import VADSegmenter
        import torchaudio

        # 1. VAD 检测语音段
        vad = VADSegmenter()
        loop = asyncio.get_running_loop()
        segments = await loop.run_in_executor(None, vad.detect_speech, str(audio_path))

        if not segments:
            text = await self.transcribe(audio_path, language)
            return [SegmentResult(start=0.0, end=0.0, text=text)]

        # 2. 加载音频用于切片
        wav, sr = await loop.run_in_executor(None, torchaudio.load, str(audio_path))
        if wav.ndim == 2:
            wav = wav.mean(dim=0, keepdim=True)
        target_sr = 16000
        if sr != target_sr:
            import torchaudio.functional as F
            wav = F.resample(wav, sr, target_sr)
            sr = target_sr

        lang_tag = None if language == "auto" else language

        # 3. 逐段推理
        results: list[SegmentResult] = []
        async with self._gpu_lock:
            for i, seg in enumerate(segments):
                start_sample = int(seg.start * sr)
                end_sample = int(seg.end * sr)
                chunk = wav[:, start_sample:end_sample]
                if chunk.shape[1] < sr * 0.1:
                    continue

                import tempfile, uuid
                tmp_path = Path(tempfile.gettempdir()) / f"q3_{uuid.uuid4().hex}.wav"
                torchaudio.save(str(tmp_path), chunk, sr)

                try:
                    seg_text = await loop.run_in_executor(
                        None,
                        lambda p=tmp_path: self._model.transcribe(
                            audio=str(p), language=lang_tag,
                            return_time_stamps=False,
                        )[0].text,
                    )
                    seg_text = seg_text.strip()
                    if seg_text:
                        results.append(SegmentResult(
                            start=seg.start, end=seg.end, text=seg_text,
                        ))
                finally:
                    tmp_path.unlink(missing_ok=True)

        logger.info("Qwen3+VAD: %d 段 → %d 结果", len(segments), len(results))
        return results
