"""vkn —— video knowledge notes."""

from __future__ import annotations

import os
from pathlib import Path

__version__ = "0.1.0"


def _setup_cuda_dlls() -> None:
    """把 pip 安装的 cuDNN/cuBLAS DLL 目录注册给 Windows。

    ctranslate2 自带的 cudnn64_9.dll 只是入口，真正的子 DLL 在
    nvidia-cudnn-cu12 / nvidia-cublas-cu12 包里。Python 3.8+ 不再默认
    搜索 PATH，必须显式 add_dll_directory，且要在导入 ctranslate2 之前。
    """
    if os.name != "nt":
        return
    try:
        import site

        roots = site.getsitepackages()
    except Exception:
        return

    for root in roots:
        for sub in ("nvidia/cudnn/bin", "nvidia/cublas/bin"):
            path = Path(root) / sub
            if not path.is_dir():
                continue
            try:
                os.add_dll_directory(str(path))
            except OSError:
                pass
            os.environ["PATH"] = str(path) + os.pathsep + os.environ.get("PATH", "")


_setup_cuda_dlls()
