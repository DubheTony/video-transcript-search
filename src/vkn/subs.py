"""字幕解析：srt / vtt / YouTube json3 / B站 json。

统一输出与 ASR 相同的 Segment，后面的切章、索引、导出不用关心来源。
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path


@dataclass
class Segment:
    start: float
    end: float
    text: str


_TIME_RE = re.compile(
    r"(\d{1,2}):(\d{2}):(\d{2})[,.](\d{1,3})\s*-->\s*(\d{1,2}):(\d{2}):(\d{2})[,.](\d{1,3})"
)


def _to_seconds(h: str, m: str, s: str, ms: str) -> float:
    return int(h) * 3600 + int(m) * 60 + int(s) + int(ms.ljust(3, "0")) / 1000


def parse_srt(path: Path) -> list[Segment]:
    text = path.read_text(encoding="utf-8-sig", errors="replace")
    blocks = re.split(r"\n\s*\n", text.strip())
    out: list[Segment] = []
    for block in blocks:
        m = _TIME_RE.search(block)
        if not m:
            continue
        start = _to_seconds(*m.groups()[:4])
        end = _to_seconds(*m.groups()[4:])
        body = _clean(block[m.end():])
        if body:
            out.append(Segment(start, end, body))
    return out


def parse_vtt(path: Path) -> list[Segment]:
    text = path.read_text(encoding="utf-8-sig", errors="replace")
    blocks = re.split(r"\n\s*\n", text.strip())
    out: list[Segment] = []
    for block in blocks:
        if block.startswith("WEBVTT"):
            continue
        m = _TIME_RE.search(block)
        if not m:
            continue
        start = _to_seconds(*m.groups()[:4])
        end = _to_seconds(*m.groups()[4:])
        body = block[m.end():]
        body = _clean(re.sub(r"<[^>]+>", "", body))
        if body:
            out.append(Segment(start, end, body))
    return _dedupe(out)


def parse_json3(path: Path) -> list[Segment]:
    data = json.loads(path.read_text(encoding="utf-8-sig", errors="replace"))
    out: list[Segment] = []
    for event in data.get("events", []):
        if "segs" not in event:
            continue
        body = _clean("".join(seg.get("utf8", "") for seg in event["segs"]))
        if not body:
            continue
        start = event.get("tStartMs", 0) / 1000
        end = (event.get("tStartMs", 0) + event.get("dDurationMs", 0)) / 1000
        out.append(Segment(start, end, body))
    return _dedupe(out)


def parse_bilibili_json(path: Path) -> list[Segment]:
    data = json.loads(path.read_text(encoding="utf-8-sig", errors="replace"))
    body = data.get("body") or data.get("subtitle", {}).get("body") or []
    out: list[Segment] = []
    for item in body:
        text = _clean(str(item.get("content", "")))
        if text:
            out.append(
                Segment(float(item.get("from", 0)), float(item.get("to", 0)), text)
            )
    return out


def parse_subtitle(path: Path) -> list[Segment]:
    suffix = path.suffix.lower()
    if suffix == ".srt":
        return parse_srt(path)
    if suffix == ".vtt":
        return parse_vtt(path)
    if suffix == ".json3":
        return parse_json3(path)
    if suffix == ".json":
        return parse_bilibili_json(path)
    raise ValueError(f"不支持的字幕格式：{path.suffix}")


def _clean(text: str) -> str:
    text = text.replace("​", "").replace("\xa0", " ")
    text = re.sub(r"<[^>]+>", "", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def _dedupe(segments: list[Segment]) -> list[Segment]:
    """YouTube vtt 会滚动重复上一行，这里去掉相邻完全相同的文本。"""
    out: list[Segment] = []
    for seg in segments:
        if out and out[-1].text == seg.text:
            out[-1] = Segment(out[-1].start, seg.end, seg.text)
        else:
            out.append(seg)
    return out
