"""SRT 字幕格式输出。"""

from __future__ import annotations

from ..schemas import Segment


def format_srt(segments: list[Segment]) -> str:
    """将 segments 列表转换为 SRT 格式字符串。

    SRT 格式：
        序号
        00:00:01,000 --> 00:00:05,000
        文本内容

    """
    lines: list[str] = []
    for i, seg in enumerate(segments, start=1):
        start = _format_srt_time(seg.start)
        end = _format_srt_time(seg.end)
        lines.append(str(i))
        lines.append(f"{start} --> {end}")
        text = f"[{seg.speaker}] {seg.text}" if seg.speaker else seg.text
        lines.append(text)
        lines.append("")  # 空行分隔

    return "\n".join(lines)


def _format_srt_time(seconds: float) -> str:
    """将秒数转换为 SRT 时间格式 HH:MM:SS,mmm。"""
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    ms = int((seconds % 1) * 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"
