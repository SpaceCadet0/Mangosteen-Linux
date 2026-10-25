"""What this machine can do: which optional programs and libraries are present.

Everything is probed lazily and cached, so importing the app stays fast and a missing optional piece only
removes the segments that need it from the wheels."""

from __future__ import annotations

import functools
import importlib.util

from . import external


@functools.lru_cache(maxsize=None)
def has_ffmpeg() -> bool:
    return external.locate("ffmpeg") is not None and external.locate("ffprobe") is not None


@functools.lru_cache(maxsize=None)
def has_heic() -> bool:
    """HEIC comes from pillow-heif (libheif with x265)."""
    return importlib.util.find_spec("pillow_heif") is not None


@functools.lru_cache(maxsize=None)
def has_avif() -> bool:
    """AVIF is built into Pillow 11.3 and later."""
    try:
        from PIL import features

        return bool(features.check("avif"))
    except Exception:  # noqa: BLE001 - an old or broken Pillow just means no AVIF
        return False


@functools.lru_cache(maxsize=None)
def has_tesseract() -> bool:
    return external.locate("tesseract") is not None


@functools.lru_cache(maxsize=None)
def has_onnxruntime() -> bool:
    return importlib.util.find_spec("onnxruntime") is not None


def reset() -> None:
    """Forgets what was probed; for tests that change PATH."""
    for function in (has_ffmpeg, has_heic, has_avif, has_tesseract, has_onnxruntime):
        function.cache_clear()
