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
def has_heif() -> bool:
    """HEIC and AVIF come from pillow-heif."""
    return importlib.util.find_spec("pillow_heif") is not None


@functools.lru_cache(maxsize=None)
def has_tesseract() -> bool:
    return external.locate("tesseract") is not None


@functools.lru_cache(maxsize=None)
def has_onnxruntime() -> bool:
    return importlib.util.find_spec("onnxruntime") is not None


def reset() -> None:
    """Forgets what was probed; for tests that change PATH."""
    for function in (has_ffmpeg, has_heif, has_tesseract, has_onnxruntime):
        function.cache_clear()
