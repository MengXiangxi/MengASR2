"""MiMo-V2.5-ASR 后端实现。"""

from __future__ import annotations

import asyncio
import logging
import sys
import time
from pathlib import Path

from .base import ASRBackend, SegmentResult
from ..config import settings

logger = logging.getLogger("mengasr.backends.mimo")

# 语言标签映射
_LANGUAGE_TAGS = {
    "auto": "",
    "chinese": "<chinese>",
    "english": "<english>",
}


class MiMoBackend(ASRBackend):
    """MiMo-V2.5-ASR 官方 PyTorch BF16 后端。"""

    def __init__(self) -> None:
        self._model = None  # MimoAudio 实例
        self._loaded = False
        self._gpu_lock = asyncio.Lock()  # 串行推理锁

    # ── 生命周期 ───────────────────────────────────────────

    async def load(self) -> None:
        """在后台线程中加载模型（避免阻塞事件循环）。"""
        if self._loaded:
            return

        # 将 MiMo 官方代码加入 sys.path
        code_path = settings.mimo_code_path
        if code_path not in sys.path:
            sys.path.insert(0, code_path)

        loop = asyncio.get_running_loop()
        start = time.monotonic()

        def _load():
            from src.mimo_audio.mimo_audio import MimoAudio  # type: ignore

            return MimoAudio(
                model_path=settings.mimo_model_path,
                mimo_audio_tokenizer_path=settings.mimo_tokenizer_path,
            )

        logger.info("开始加载 MiMo 模型……")
        self._model = await loop.run_in_executor(None, _load)
        elapsed = time.monotonic() - start
        logger.info("MiMo 模型加载完成，耗时 %.1fs", elapsed)
        self._loaded = True

    async def unload(self) -> None:
        if self._model is not None:
            del self._model
            self._model = None
            self._loaded = False
            import torch
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
            logger.info("MiMo 模型已释放")

    def is_loaded(self) -> bool:
        return self._loaded

    def model_id(self) -> str:
        return "mimo-v2.5-asr"

    # ── 推理 ───────────────────────────────────────────────

    async def transcribe(
        self,
        audio_path: Path,
        language: str = "auto",
    ) -> str:
        if not self._loaded or self._model is None:
            raise RuntimeError("MiMo 模型未加载")

        audio_tag = _LANGUAGE_TAGS.get(language, "")

        async with self._gpu_lock:
            loop = asyncio.get_running_loop()
            start = time.monotonic()

            text = await loop.run_in_executor(
                None,
                self._model.asr_sft,
                str(audio_path),
                audio_tag,
            )
            elapsed = time.monotonic() - start
            logger.info("推理耗时 %.2fs，语言=%s", elapsed, language)

        return text

    async def transcribe_segments(
        self,
        audio_path: Path,
        language: str = "auto",
    ) -> list[SegmentResult]:
        """VAD 分段 → 逐段 ASR → 带时间戳结果。"""
        from ..timestamps.vad import VADSegmenter
        import torchaudio

        # 1. VAD 检测语音段
        vad = VADSegmenter()
        loop = asyncio.get_running_loop()
        segments = await loop.run_in_executor(
            None, vad.detect_speech, str(audio_path)
        )

        if not segments:
            # 无语音段 → 整体转写降级
            logger.warning("VAD 未检测到语音，降级为整体转写")
            text = await self.transcribe(audio_path, language)
            return [SegmentResult(start=0.0, end=0.0, text=text)]

        # 2. 加载音频用于切片
        wav, sr = await loop.run_in_executor(
            None, torchaudio.load, str(audio_path)
        )
        if wav.ndim == 2:
            wav = wav.mean(dim=0, keepdim=True)

        # 重采样到 16kHz（如果需要）
        target_sr = 16000
        if sr != target_sr:
            import torchaudio.functional as F
            wav = F.resample(wav, sr, target_sr)
            sr = target_sr

        # 3. 逐段提取 + 转写
        results: list[SegmentResult] = []
        audio_tag = _LANGUAGE_TAGS.get(language, "")

        async with self._gpu_lock:
            for i, seg in enumerate(segments):
                start_sample = int(seg.start * sr)
                end_sample = int(seg.end * sr)
                chunk = wav[:, start_sample:end_sample]

                if chunk.shape[1] < sr * 0.1:  # 跳过 <100ms 的片段
                    continue

                # 保存临时 WAV
                import tempfile, uuid
                tmp_path = settings.tmp_dir / f"seg_{uuid.uuid4().hex[:8]}.wav"
                torchaudio.save(str(tmp_path), chunk, sr)

                try:
                    seg_start = time.monotonic()
                    text = await loop.run_in_executor(
                        None,
                        self._model.asr_sft,
                        str(tmp_path),
                        audio_tag,
                    )
                    seg_elapsed = time.monotonic() - seg_start
                    logger.info(
                        "段 %d/%d: %.1f-%.1fs, 推理 %.2fs",
                        i + 1, len(segments), seg.start, seg.end, seg_elapsed,
                    )

                    text = text.strip()
                    if text:
                        results.append(SegmentResult(
                            start=seg.start,
                            end=seg.end,
                            text=text,
                        ))
                finally:
                    tmp_path.unlink(missing_ok=True)

        logger.info("分段转写完成：%d 段 → %d 个有效结果", len(segments), len(results))
        return results
