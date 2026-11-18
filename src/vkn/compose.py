"""组装：把 transcript.jsonl 和章节写成可读的 notes.md。"""

from __future__ import annotations

import json
from pathlib import Path

from .asr import Segment, fmt_clock
from .segment import cut_chapters


def _load_segments(path: Path) -> list[Segment]:
    out: list[Segment] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        item = json.loads(line)
        out.append(Segment(float(item["start"]), float(item["end"]), item["text"]))
    return out


def compose_notes(video_dir: Path) -> Path:
    meta_path = video_dir / "meta.json"
    jsonl_path = video_dir / "transcript.jsonl"
    if not meta_path.exists() or not jsonl_path.exists():
        raise FileNotFoundError(f"缺少 meta.json 或 transcript.jsonl：{video_dir}")

    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    segments = _load_segments(jsonl_path)
    chapters = cut_chapters(segments)

    lines = [
        f"# {meta.get('title', video_dir.name)}",
        "",
        f"- 时长：{fmt_clock(float(meta.get('duration') or 0))}",
        f"- 来源：{meta.get('source', '')}",
        f"- 字幕来源：{meta.get('subtitle_source', '')}",
        f"- 引擎：{meta.get('engine') or meta.get('model') or meta.get('subtitle_source') or ''}",
        "",
    ]
    for chapter in chapters:
        lines.append(f"## {fmt_clock(chapter.start)} {chapter.title}")
        for seg in chapter.segments:
            lines.append(f"[{fmt_clock(seg.start)}] {seg.text}")
        lines.append("")

    out = video_dir / "notes.md"
    out.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    return out
