"""切章：按静音间隔或时长上限把相邻段落分组。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class Chapter:
    index: int
    start: float
    end: float
    title: str
    segments: list[Any] = field(default_factory=list)


def _title(segments: list[Any], limit: int = 30) -> str:
    text = segments[0].text.strip() if segments else ""
    text = text.split("。")[0].split("！")[0].split("？")[0]
    return text[:limit] or "未命名"


def cut_chapters(
    segments: list[Any],
    *,
    silence_gap: float = 1.2,
    max_seconds: float = 480.0,
) -> list[Chapter]:
    """静音间隔超过 silence_gap 或累计超过 max_seconds 就断章。

    SenseVoice 的块级段落天然接近 5 分钟，会按 max_seconds 断；
    Whisper 的句级段落会按静音断得更细。
    """
    chapters: list[Chapter] = []
    current: list[Any] = []
    start = end = 0.0

    def flush() -> None:
        if current:
            chapters.append(
                Chapter(
                    index=len(chapters) + 1,
                    start=start,
                    end=end,
                    title=_title(current),
                    segments=list(current),
                )
            )

    for seg in segments:
        if not current:
            current = [seg]
            start, end = seg.start, seg.end
            continue
        if seg.start - end > silence_gap or seg.end - start > max_seconds:
            flush()
            current = [seg]
            start, end = seg.start, seg.end
        else:
            current.append(seg)
            end = seg.end

    flush()
    return chapters
