"""清理源媒体：删除 _源材料/<id>/ 和 data/<id>/audio.wav，保留文字稿。"""

from __future__ import annotations

import shutil
from pathlib import Path

from . import config


def _size(path: Path) -> int:
    if path.is_file():
        return path.stat().st_size
    total = 0
    for item in path.rglob("*"):
        if item.is_file():
            total += item.stat().st_size
    return total


def _human(num: int) -> str:
    value = float(num)
    for unit in ("B", "KB", "MB", "GB"):
        if value < 1024 or unit == "GB":
            return f"{value:.1f} {unit}"
        value /= 1024
    return f"{value:.1f} GB"


def collect(video_id: str | None, all_: bool) -> list[Path]:
    targets: list[Path] = []
    if video_id:
        src = config.SOURCE_DIR / video_id
        wav = config.DATA_DIR / video_id / "audio.wav"
        targets.extend(p for p in (src, wav) if p.exists())
        return targets

    if all_:
        if config.SOURCE_DIR.is_dir():
            targets.extend(p for p in config.SOURCE_DIR.iterdir() if p.is_dir())
        targets.extend(config.DATA_DIR.glob("*/audio.wav"))
    return targets


def clean(video_id: str | None, *, all_: bool = False, dry_run: bool = False) -> int:
    targets = collect(video_id, all_)
    if not targets:
        print("没有可清理的源媒体")
        return 0

    total = 0
    for path in targets:
        size = _size(path)
        total += size
        print(f"{'将删除' if dry_run else '删除'}  {path}  ({_human(size)})")
        if not dry_run:
            if path.is_dir():
                shutil.rmtree(path)
            else:
                path.unlink(missing_ok=True)

    print(f"{'预计释放' if dry_run else '已释放'} {_human(total)}")
    if dry_run:
        print("这是预览，去掉 --dry-run 才会真正删除")
    return 0
