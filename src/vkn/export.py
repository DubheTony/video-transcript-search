"""导出片段为纯文本，供主对话直接使用。"""

from __future__ import annotations

from pathlib import Path

from . import index
from .asr import fmt_clock


def export_at(
    video_id: str,
    at: float,
    span_minutes: float = 3,
    db_path: Path = index.DB_PATH,
) -> str:
    hits = index.show(video_id, at, span=span_minutes * 60, db_path=db_path)
    if not hits:
        return ""
    lines = [f"# {hits[0]['title']}  ({video_id})", ""]
    for hit in hits:
        lines.append(
            f"[{fmt_clock(hit['start'])}-{fmt_clock(hit['end'])}] {hit['text']}"
        )
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def export_search(
    query: str,
    top_k: int = 5,
    db_path: Path = index.DB_PATH,
) -> str:
    hits = index.search(query, top_k=top_k, db_path=db_path)
    if not hits:
        return ""
    lines = [f"# 检索：{query}", ""]
    for hit in hits:
        lines.append(
            f"## {hit['title']}  [{fmt_clock(hit['start'])}-{fmt_clock(hit['end'])}]"
        )
        lines.append(hit["text"])
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"
