"""The three wheels and the segments each shows for a set of files.

Shift opens Convert, Ctrl opens Tools, Alt opens Actions (the keys can be changed in Settings)."""

from __future__ import annotations

import os
from collections.abc import Sequence
from dataclasses import dataclass, replace
from enum import Enum

from . import capabilities, format_catalog
from .file_format import Category, FileFormat, detect
from .loc import L, count


class WheelKind(Enum):
    CONVERT = "convert"
    TOOLS = "tools"
    ACTIONS = "actions"


@dataclass(frozen=True)
class WheelItem:
    """One segment of a wheel. `available` is False when a program the feature needs is missing; `hint` then
    says what to install."""

    id: str
    title: str
    icon: str
    available: bool = True
    target: FileFormat | None = None
    hint: str = ""


def wheel_title(kind: WheelKind) -> str:
    return {WheelKind.CONVERT: L("Convert"), WheelKind.TOOLS: L("Tools")}.get(kind, L("Actions"))


def file_count(number: int) -> str:
    return count(number, "file")


def icon_for(fmt: FileFormat) -> str:
    return {
        Category.IMAGE: "image",
        Category.VIDEO: "film",
        Category.AUDIO: "music",
        Category.ARCHIVE: "archive",
        Category.TABLE: "table",
        Category.SUBTITLE: "subtitle",
    }.get(fmt.category, "document")


def items(kind: WheelKind, paths: Sequence[str]) -> list[WheelItem]:
    if kind is WheelKind.CONVERT:
        return [
            WheelItem(f"convert.{fmt.extension}", fmt.display_name, icon_for(fmt), True, fmt)
            for fmt in format_catalog.targets(paths)
        ]
    if kind is WheelKind.TOOLS:
        return tool_items(paths)
    return [replace(item, title=L(item.title)) for item in _ACTION_ITEMS]


_ACTION_ITEMS = [
    WheelItem("action.float", "Float", "float"),
    WheelItem("action.copy", "Copy", "copy"),
    WheelItem("action.move", "Move", "move"),
    WheelItem("action.copyPath", "Path", "path"),
    WheelItem("action.terminal", "Terminal", "terminal"),
]

_NEEDS_FFMPEG = {
    "tool.trimMedia", "tool.splitMedia", "tool.speed", "tool.normalize", "tool.bleep", "tool.channels",
    "tool.visualizer", "tool.redactVideo", "tool.cropVideo", "tool.join", "tool.compressMedia", "tool.frames",
}


def _availability(tool_id: str) -> tuple[bool, str]:
    if tool_id in _NEEDS_FFMPEG and not capabilities.has_ffmpeg():
        return False, L("Needs FFmpeg: install the ffmpeg package.")
    if tool_id == "tool.recognizeText" and not capabilities.has_tesseract():
        return False, L("Needs Tesseract: install the tesseract-ocr package.")
    return True, ""


def _kinds(paths: Sequence[str]) -> set[str]:
    kinds: set[str] = set()
    for path in paths:
        fmt = detect(path)
        if fmt is not None:
            kinds.add(fmt.category.value)
        elif os.path.isdir(path):
            kinds.add("folder")
    return kinds


def can_compress(fmt: FileFormat) -> bool:
    """Formats "Compress" handles without a window: photos and PDF, and video and audio when ffmpeg is there."""
    return fmt.is_raster_image or fmt is FileFormat.PDF or (fmt.category.is_media and capabilities.has_ffmpeg())


class _Builder:
    def __init__(self) -> None:
        self.items: list[WheelItem] = []

    def add(self, condition: bool, tool_id: str, title: str, icon: str) -> None:
        if condition:
            available, hint = _availability(tool_id)
            self.items.append(WheelItem(tool_id, L(title), icon, available, None, hint))


def _mixed_items(paths: Sequence[str], formats: list[FileFormat]) -> list[WheelItem]:
    """A mixed selection (say photos and a video) gets only what applies to all of it, instead of every tool for
    every kind: compress each file its own way, metadata of the photos, text from photos and PDFs, one archive."""
    b = _Builder()
    b.add(any(can_compress(f) for f in formats), "tool.compressAll", "Compress", "compress")
    b.add(any(f.is_raster_image for f in formats), "tool.metadata", "Metadata", "info")
    b.add(len(formats) == len(paths) and all(f.is_raster_image or f is FileFormat.PDF for f in formats),
          "tool.recognizeText", "Text", "text")
    b.add(True, "tool.archive", "Archive", "archive")
    return b.items


def tool_items(paths: Sequence[str]) -> list[WheelItem]:
    """Same rules and order as the macOS and Windows Tools wheels."""
    formats = [f for f in (detect(p) for p in paths) if f is not None]
    if len(_kinds(paths)) > 1:
        return _mixed_items(paths, formats)

    def any_of(predicate) -> bool:  # noqa: ANN001
        return any(predicate(f) for f in formats)

    def number(predicate) -> int:  # noqa: ANN001
        return sum(1 for f in formats if predicate(f))

    media = any_of(lambda f: f.category.is_media)
    audio = any_of(lambda f: f.category is Category.AUDIO)
    video = any_of(lambda f: f.category is Category.VIDEO)
    images = any_of(lambda f: f.category is Category.IMAGE)
    pdf = any_of(lambda f: f is FileFormat.PDF)
    raster = any_of(lambda f: f.is_raster_image)

    b = _Builder()
    b.add(media, "tool.trimMedia", "Trim", "trim")
    b.add(media, "tool.splitMedia", "Split", "split")
    b.add(media, "tool.speed", "Speed", "speed")
    b.add(media, "tool.normalize", "Volume", "volume")
    b.add(media, "tool.bleep", "Bleep", "bleep")
    b.add(audio, "tool.channels", "Channels", "channels")
    b.add(audio, "tool.visualizer", "Visualizer", "visualizer")
    b.add(video, "tool.redactVideo", "Hide", "hide")
    b.add(video, "tool.cropVideo", "Reframe", "crop")
    b.add(number(lambda f: f.category is Category.VIDEO) >= 2, "tool.join", "Join", "join")
    b.add(media and not images and not pdf, "tool.compressMedia", "Compress", "compress")
    b.add(video, "tool.frames", "Frames", "frames")
    b.add(images or pdf, "tool.compress", "Compress", "compress")
    b.add(images, "tool.crop", "Crop", "crop")
    b.add(images, "tool.edit", "Editor", "edit")
    b.add(images, "tool.annotate", "Annotate", "annotate")
    b.add(images, "tool.redact", "Hide", "hide")
    # With media in the selection there is a "Split" for video too; say which one this is.
    b.add(pdf, "tool.splitPDF", "Split PDF" if media else "Split", "split")
    b.add(pdf, "tool.organizePDF", "Page order", "pages")
    b.add(raster or pdf, "tool.recognizeText", "Text", "text")
    b.add(images, "tool.frame", "Background", "background")
    b.add(raster, "tool.removeBackground", "Remove bg", "removeBackground")
    b.add(number(lambda f: f.category is Category.IMAGE) >= 2, "tool.collage", "Collage", "collage")
    b.add(raster, "tool.metadata", "Metadata", "info")
    b.add(any_of(lambda f: f.category is Category.ARCHIVE), "tool.extract", "Extract", "extract")
    b.add(number(lambda f: f is FileFormat.PDF) >= 2, "tool.mergePDF", "Merge", "merge")
    return b.items
