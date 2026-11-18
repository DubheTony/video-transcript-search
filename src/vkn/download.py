"""链接取回：yt-dlp 为主。yt-dlp 覆盖不了时提示用 videodl 手动取回。"""

from __future__ import annotations

import json
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

DEFAULT_PROXY = "http://127.0.0.1:9674"
SUB_SUFFIXES = {".json3", ".vtt", ".srt", ".json"}


class DownloadError(Exception):
    pass


@dataclass
class LinkMeta:
    id: str
    title: str
    duration: float
    platform: str
    url: str
    language: str | None
    uploader: str | None
    manual_langs: list[str]
    auto_langs: list[str]


def _ytdlp() -> str:
    exe = shutil.which("yt-dlp")
    if not exe:
        raise DownloadError("找不到 yt-dlp，请确认它在 PATH 上")
    return exe


def _run(cmd: list[str]) -> str:
    proc = subprocess.run(
        cmd, capture_output=True, text=True, encoding="utf-8", errors="replace"
    )
    if proc.returncode != 0:
        raise DownloadError(
            (proc.stderr or proc.stdout).strip()[:800] or "yt-dlp 执行失败"
        )
    return proc.stdout


def _proxy_args(proxy: str | None) -> list[str]:
    return ["--proxy", proxy] if proxy else []


def _extractor_args(url: str) -> list[str]:
    """YouTube 用 tv_embedded 客户端，避免『确认你不是机器人』。"""
    if "youtube.com" in url or "youtu.be" in url:
        return ["--extractor-args", "youtube:player_client=tv_embedded"]
    return []


def probe(url: str, proxy: str | None = DEFAULT_PROXY) -> LinkMeta:
    cmd = [
        _ytdlp(), "--dump-single-json", "--no-playlist", "--no-warnings",
        "--socket-timeout", "20", *_proxy_args(proxy), url,
    ]
    data = json.loads(_run(cmd))
    subs = data.get("subtitles") or {}
    autos = data.get("automatic_captions") or {}
    return LinkMeta(
        id=str(data.get("id") or "video"),
        title=str(data.get("title") or "video"),
        duration=float(data.get("duration") or 0),
        platform=str(data.get("extractor_key") or data.get("extractor") or "unknown"),
        url=str(data.get("webpage_url") or url),
        language=data.get("language"),
        uploader=data.get("uploader"),
        manual_langs=list(subs.keys()),
        auto_langs=list(autos.keys()),
    )


def pick_lang(langs: list[str], wanted: list[str]) -> str | None:
    """按期望顺序选语言；先精确匹配，再前缀匹配（zh-Hans 匹配 zh）。"""
    lowered = {lang.lower(): lang for lang in langs}
    for want in wanted:
        if want.lower() in lowered:
            return lowered[want.lower()]
    for lang in langs:
        for want in wanted:
            if lang.lower().startswith(want.lower()):
                return lang
    return None


def download_subs(
    url: str,
    out_dir: Path,
    lang: str,
    proxy: str | None = DEFAULT_PROXY,
    auto: bool = False,
) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    cmd = [
        _ytdlp(), "--skip-download", "--no-playlist", "--no-warnings",
        "--write-auto-subs" if auto else "--write-subs",
        "--sub-langs", lang, "--sub-format", "json3/vtt/srt/best",
        "-o", str(out_dir / "%(id)s.%(ext)s"),
        *_proxy_args(proxy), url,
    ]
    _run(cmd)

    files = [
        p for p in out_dir.iterdir()
        if p.suffix.lower() in SUB_SUFFIXES and not p.name.endswith(".info.json")
    ]
    # 优先带语言名的文件
    for p in files:
        if lang.lower() in p.name.lower():
            return p
    if files:
        return sorted(files)[0]
    raise DownloadError(f"yt-dlp 没有产出 {lang} 字幕文件")


def _has_audio(path: Path) -> bool:
    exe = shutil.which("ffprobe")
    if not exe:
        return True
    proc = subprocess.run(
        [exe, "-v", "error", "-show_entries", "stream=codec_type",
         "-of", "csv=p=0", str(path)],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    return "audio" in proc.stdout


def _download_with_videodl(url: str, out_dir: Path, timeout: int = 300) -> Path | None:
    """用 videodl 下载。返回带音频的文件；只有画面或失败则返回 None。"""
    exe = shutil.which("videodl")
    if not exe:
        return None
    out_dir.mkdir(parents=True, exist_ok=True)
    try:
        subprocess.run(
            [exe, "-i", url],
            cwd=out_dir,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
        )
    except Exception:
        return None

    root = out_dir / "videodl_outputs"
    if not root.is_dir():
        return None
    media = [
        p for p in root.rglob("*")
        if p.is_file() and p.suffix.lower() in {".mp4", ".mkv", ".webm", ".m4a", ".mp3"}
    ]
    for path in media:
        if _has_audio(path):
            return path
    return None


def download_audio(
    url: str, out_dir: Path, proxy: str | None = DEFAULT_PROXY
) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)

    # 非 YouTube 平台先试 videodl；它下载的视频经常没有音轨，用 ffprobe 检查
    if "youtube.com" not in url and "youtu.be" not in url:
        media = _download_with_videodl(url, out_dir)
        if media is not None:
            return media

    cmd = [
        _ytdlp(), "-f", "bestaudio/best", "--no-playlist", "--no-warnings",
        "-o", str(out_dir / "original.%(ext)s"),
        *_extractor_args(url), *_proxy_args(proxy), url,
    ]
    _run(cmd)
    for p in out_dir.glob("original.*"):
        if p.suffix.lower() not in {".part", ".ytdl"}:
            return p
    raise DownloadError("yt-dlp 没有产出音频文件；可改用 videodl 手动下载后给本地文件")
