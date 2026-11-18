"""SQLite FTS5 索引：jieba 分词 + 拼音，支持同音字检索。

转写稿原样不动；索引里另存一份分词和拼音，搜"锚链"也能命中
被识别成"猫链"的段落。
"""

from __future__ import annotations

import json
import re
import sqlite3
from pathlib import Path

import jieba
from pypinyin import lazy_pinyin

from . import config
from .asr import Segment
from .segment import cut_chapters

DB_PATH = config.PROJECT_ROOT / "索引" / "knowledge.db"

_SCHEMA = """
CREATE VIRTUAL TABLE IF NOT EXISTS chunks USING fts5(
    video_id UNINDEXED,
    title UNINDEXED,
    start UNINDEXED,
    end UNINDEXED,
    chapter UNINDEXED,
    text,
    text_tokens,
    text_pinyin,
    tokenize='unicode61'
)
"""


def _connect(db_path: Path = DB_PATH) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.execute(_SCHEMA)
    return conn


def _tokens(text: str) -> str:
    return " ".join(t for t in jieba.cut(text) if t.strip())


def _pinyin(text: str) -> str:
    return " ".join(p for p in lazy_pinyin(text) if p.isalnum())


def _split_long(seg: Segment, max_chars: int = 180) -> list[Segment]:
    """SenseVoice 的块可能 5 分钟一大段，按句切成检索友好的小段。

    时间戳按字符数比例分配，仍是块内估算，不是精确对齐。
    """
    text = seg.text.strip()
    if len(text) <= max_chars or seg.end <= seg.start:
        return [seg]

    sentences = [s for s in re.split(r"(?<=[。！？；])", text) if s.strip()]
    pieces: list[str] = []
    current = ""
    for sentence in sentences:
        if current and len(current) + len(sentence) > max_chars:
            pieces.append(current)
            current = sentence
        else:
            current += sentence
    if current:
        pieces.append(current)
    if len(pieces) <= 1:
        return [seg]

    total = sum(len(p) for p in pieces) or 1
    out: list[Segment] = []
    cursor = seg.start
    for piece in pieces:
        span = (seg.end - seg.start) * len(piece) / total
        out.append(Segment(cursor, cursor + span, piece))
        cursor += span
    return out


def _load_segments(path: Path) -> list[Segment]:
    out: list[Segment] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        item = json.loads(line)
        out.append(Segment(float(item["start"]), float(item["end"]), item["text"]))
    return out


def build(data_dir: Path = config.DATA_DIR, db_path: Path = DB_PATH) -> tuple[int, int]:
    """重建整个索引。返回 (视频数, 片段数)。"""
    conn = _connect(db_path)
    conn.execute("DELETE FROM chunks")

    videos = 0
    chunks = 0
    for video_dir in sorted(p for p in data_dir.iterdir() if p.is_dir()):
        meta_path = video_dir / "meta.json"
        jsonl_path = video_dir / "transcript.jsonl"
        if not meta_path.exists() or not jsonl_path.exists():
            continue
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        segments = _load_segments(jsonl_path)
        for chapter in cut_chapters(segments):
            for seg in chapter.segments:
                for piece in _split_long(seg):
                    conn.execute(
                        "INSERT INTO chunks "
                        "(video_id, title, start, end, chapter, text, text_tokens, text_pinyin) "
                        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                        (
                            meta.get("id", video_dir.name),
                            meta.get("title", ""),
                            piece.start,
                            piece.end,
                            chapter.index,
                            piece.text,
                            _tokens(piece.text),
                            _pinyin(piece.text),
                        ),
                    )
                    chunks += 1
        videos += 1

    conn.commit()
    conn.close()
    return videos, chunks


def _match_expr(query: str) -> str:
    query = query.replace('"', " ").strip()
    tokens = [t for t in jieba.cut(query) if t.strip()]
    parts: list[str] = []
    if tokens:
        parts.append("text_tokens:(" + " ".join(tokens) + ")")
    py = _pinyin(query)
    if py:
        parts.append(f'text_pinyin:"{py}"')
    return " OR ".join(parts)


def search(query: str, top_k: int = 10, db_path: Path = DB_PATH) -> list[dict]:
    expr = _match_expr(query)
    if not expr:
        return []
    conn = _connect(db_path)
    rows = conn.execute(
        "SELECT video_id, title, start, end, chapter, text, bm25(chunks) AS score "
        "FROM chunks WHERE chunks MATCH ? ORDER BY score LIMIT ?",
        (expr, top_k),
    ).fetchall()
    conn.close()
    return [
        {
            "video_id": row[0],
            "title": row[1],
            "start": row[2],
            "end": row[3],
            "chapter": row[4],
            "text": row[5],
            "score": row[6],
        }
        for row in rows
    ]


def show(video_id: str, at: float, span: float = 180, db_path: Path = DB_PATH) -> list[dict]:
    conn = _connect(db_path)
    rows = conn.execute(
        "SELECT video_id, title, start, end, chapter, text FROM chunks "
        "WHERE video_id = ? AND end >= ? AND start <= ? "
        "ORDER BY start",
        (video_id, at - span, at + span),
    ).fetchall()
    conn.close()
    return [
        {
            "video_id": row[0],
            "title": row[1],
            "start": row[2],
            "end": row[3],
            "chapter": row[4],
            "text": row[5],
        }
        for row in rows
    ]
