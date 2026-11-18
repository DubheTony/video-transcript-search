"""项目路径与默认参数。"""

from __future__ import annotations

import os
from pathlib import Path

# src/vkn/config.py -> 项目根
PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = PROJECT_ROOT / "数据"
TEMP_DIR = PROJECT_ROOT / "_临时"
SOURCE_DIR = PROJECT_ROOT / "_源材料"

DEFAULT_MODEL = "large-v3-turbo"
DEFAULT_LANGUAGE = "zh"
SENSEVOICE_DIR = PROJECT_ROOT / "模型" / "sensevoice"
DIARIZATION_DIR = PROJECT_ROOT / "模型" / "diarization"

# 视频扩展名；音频也接受，方便直接转写录音
MEDIA_SUFFIXES = {
    ".mp4", ".mkv", ".mov", ".flv", ".avi", ".webm", ".ts",
    ".mp3", ".m4a", ".wav", ".flac", ".aac", ".ogg",
}


def ensure_dirs() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)


def resolve_model(model: str) -> str:
    """模型名或本地目录。本地目录必须存在，名字交给 faster-whisper 查缓存。"""
    path = Path(model).expanduser()
    if path.is_dir():
        return str(path.resolve())
    return model


def device() -> str:
    """有可用的 CUDA 设备就用 GPU，否则退 CPU。"""
    if os.environ.get("VKN_DEVICE"):
        return os.environ["VKN_DEVICE"]
    try:
        import ctranslate2

        return "cuda" if ctranslate2.get_cuda_device_count() > 0 else "cpu"
    except Exception:
        return "cpu"


def compute_type(dev: str) -> str:
    return "float16" if dev == "cuda" else "int8"
