"""取回：本地文件路径与视频 ID。

链接取回在 download.py；这里只负责本地文件校验和 ID 生成。
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime
from pathlib import Path

from .config import MEDIA_SUFFIXES


class FetchError(Exception):
    pass


def resolve_media(raw: str) -> Path:
    """校验本地输入并返回绝对路径。"""
    path = Path(raw).expanduser()
    if not path.exists():
        raise FetchError(f"文件不存在：{path}")
    if not path.is_file():
        raise FetchError(f"不是文件：{path}")
    if path.suffix.lower() not in MEDIA_SUFFIXES:
        raise FetchError(
            f"不支持的后缀 {path.suffix}；支持：{', '.join(sorted(MEDIA_SUFFIXES))}"
        )
    return path.resolve()


def is_url(raw: str) -> bool:
    return "://" in raw


def _slug(text: str, limit: int = 24) -> str:
    """文件名/标题 → 可读目录名。保留中文，去掉 Windows 非法字符。"""
    text = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "", text)
    text = re.sub(r"\s+", "_", text.strip())
    return text[:limit] or "video"


def make_id(title: str, key: str) -> str:
    """日期_标题_键哈希前8位。本地用路径，链接用平台 ID。"""
    digest = hashlib.sha1(key.encode("utf-8")).hexdigest()[:8]
    return f"{datetime.now():%Y%m%d}_{_slug(title)}_{digest}"


def make_video_id(media: Path) -> str:
    return make_id(media.stem, str(media))


def write_meta(path: Path, meta: dict) -> None:
    path.write_text(
        json.dumps(meta, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def read_meta(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))
