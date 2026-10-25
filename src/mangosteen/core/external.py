"""Locates and runs command-line tools (ffmpeg, ffprobe, tesseract…).

Lookup order: the folder next to the app that carries the tools (the AppImage and the bundled builds), then PATH.
Arguments are always passed as a list, never through a shell."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import threading
from collections import deque
from collections.abc import Callable
from pathlib import Path

from .cancellation import Cancelled, CancellationToken


class ToolFailure(Exception):
    def __init__(self, tool: str, status: int, output: str) -> None:
        details = output.strip()
        super().__init__(f"{tool} exited with code {status}" + (f": {details}" if details else ""))
        self.tool = tool
        self.status = status
        self.output = output


class ToolMissing(Exception):
    def __init__(self, tool: str) -> None:
        super().__init__(f"The program “{tool}” was not found. Install it with your package manager "
                         f"(for example: sudo apt install {_PACKAGES.get(tool, tool)}).")
        self.tool = tool


_PACKAGES = {"ffprobe": "ffmpeg", "cwebp": "webp", "gif2webp": "webp", "tesseract": "tesseract-ocr"}


def _bundled_directories() -> list[Path]:
    directories: list[Path] = []
    override = os.environ.get("MANGOSTEEN_TOOLS")
    if override:
        directories.append(Path(override))
    appdir = os.environ.get("APPDIR")
    if appdir:
        directories.append(Path(appdir) / "usr" / "bin")
    here = Path(__file__).resolve().parent.parent
    directories += [here / "tools_bin", here.parent.parent / "tools_bin"]
    if getattr(sys, "frozen", False):
        directories.append(Path(sys.executable).resolve().parent / "tools")
    return directories


def locate(name: str) -> str | None:
    for directory in _bundled_directories():
        candidate = directory / name
        if candidate.is_file() and os.access(candidate, os.X_OK):
            return str(candidate)
    return shutil.which(name)


def is_available(name: str) -> bool:
    return locate(name) is not None


def _require(name: str) -> str:
    path = locate(name)
    if path is None:
        raise ToolMissing(name)
    return path


def run(name: str, arguments: list[str], input_data: bytes | None = None) -> str:
    """Runs the tool to completion and returns its combined text output."""
    process = subprocess.run([_require(name), *arguments], input=input_data, stdout=subprocess.PIPE,
                             stderr=subprocess.STDOUT, check=False)
    text = process.stdout.decode("utf-8", "replace")
    if process.returncode != 0:
        raise ToolFailure(name, process.returncode, text[-800:])
    return text


def run_data(name: str, arguments: list[str], input_data: bytes | None = None) -> bytes:
    """Runs the tool and returns its raw stdout (images or samples piped by ffmpeg)."""
    process = subprocess.run([_require(name), *arguments], input=input_data, stdout=subprocess.PIPE,
                             stderr=subprocess.PIPE, check=False)
    if process.returncode != 0:
        raise ToolFailure(name, process.returncode, process.stderr.decode("utf-8", "replace")[-800:])
    return process.stdout


def run_streaming(name: str, arguments: list[str], on_line: Callable[[str], None],
                  cancellation: CancellationToken | None = None) -> None:
    """Runs the tool, delivering each stdout line as it arrives (ffmpeg `-progress pipe:1`). Stderr is kept for
    the error message. The process is terminated when `cancellation` fires and the call then raises `Cancelled`."""
    process = subprocess.Popen([_require(name), *arguments], stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                               stdin=subprocess.DEVNULL, bufsize=0)
    tail: deque[bytes] = deque(maxlen=64)

    def drain_errors() -> None:
        assert process.stderr is not None
        for chunk in iter(lambda: process.stderr.readline(), b""):  # type: ignore[union-attr]
            tail.append(chunk)

    reader = threading.Thread(target=drain_errors, daemon=True)
    reader.start()
    if cancellation is not None:
        cancellation.on_cancel(lambda: process.poll() is None and process.terminate())
    assert process.stdout is not None
    try:
        for raw in iter(process.stdout.readline, b""):
            on_line(raw.decode("utf-8", "replace").rstrip("\r\n"))
        process.wait()
    finally:
        if process.poll() is None:
            process.kill()
            process.wait()
    reader.join(timeout=2)
    if cancellation is not None and cancellation.is_cancelled:
        raise Cancelled()
    if process.returncode != 0:
        message = b"".join(tail).decode("utf-8", "replace")
        raise ToolFailure(name, process.returncode, message[-800:])
