"""抽音轨：ffmpeg → 16kHz 单声道 PCM wav。"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path


class AudioError(Exception):
    pass


def _ffmpeg() -> str:
    exe = shutil.which("ffmpeg")
    if not exe:
        raise AudioError("找不到 ffmpeg，请先将 ffmpeg 加入 PATH")
    return exe


def _ffprobe() -> str:
    exe = shutil.which("ffprobe")
    if not exe:
        raise AudioError("找不到 ffprobe，请先将 ffprobe 加入 PATH")
    return exe


def probe_duration(media: Path) -> float:
    """返回媒体时长（秒）。取不到时返回 0。"""
    cmd = [
        _ffprobe(), "-v", "error",
        "-show_entries", "format=duration",
        "-of", "json", str(media),
    ]
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, check=True).stdout
        return float(json.loads(out)["format"]["duration"])
    except Exception:
        return 0.0


def extract_audio(media: Path, out_wav: Path) -> None:
    """抽成 Whisper 需要的格式；已存在则跳过，由调用方决定是否 --force。"""
    if out_wav.exists():
        return
    cmd = [
        _ffmpeg(), "-y", "-loglevel", "error",
        "-i", str(media),
        "-vn", "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le",
        str(out_wav),
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise AudioError(f"ffmpeg 抽音轨失败：{proc.stderr.strip()[:500]}")
