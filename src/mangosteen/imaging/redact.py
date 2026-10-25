"""Hiding things in pictures: covering regions irreversibly with a fill, a blur or large pixels, and finding faces and
text on the device."""

from __future__ import annotations

import os
import re
from enum import Enum

import cv2
import numpy as np
from PIL import Image

from ..convert import images
from ..core import capabilities, external, format_catalog, output_naming
from ..core.file_format import FileFormat, detect
from ..core.loc import L
from ..core.settings import ConversionOptions
from .geometry import UnitRect
from .compose import RGBA


class RedactionStyle(Enum):
    SOLID = "solid"
    BLUR = "blur"
    PIXELATE = "pixelate"


def apply(image: Image.Image, regions: list[UnitRect], style: RedactionStyle, color: RGBA = RGBA(0, 0, 0)) -> Image.Image:
    """Covers the regions of `image` (a copy is returned)."""
    result = image.convert("RGBA")
    array = np.asarray(result).copy()
    for region in regions:
        rect = region.to_pixels(result.width, result.height)
        view = array[rect.y:rect.bottom, rect.x:rect.right]
        if style is RedactionStyle.SOLID:
            r, g, b, a = color.to_tuple()
            view[..., 0], view[..., 1], view[..., 2] = r, g, b
            view[..., 3] = np.maximum(a, view[..., 3])
        elif style is RedactionStyle.PIXELATE:
            view[...] = _pixelate(view, max(6, min(rect.width, rect.height) // 8))
        else:
            # Pixelating first makes the blur impossible to undo; the blur then hides the blocks.
            block = max(4, min(rect.width, rect.height) // 12)
            pixelated = _pixelate(view, block)
            size = block * 2 + 1
            for _ in range(3):
                pixelated = cv2.blur(pixelated, (size, size), borderType=cv2.BORDER_REPLICATE)
            view[...] = pixelated
    return Image.fromarray(array, "RGBA")


def _pixelate(view: np.ndarray, block: int) -> np.ndarray:
    height, width = view.shape[:2]
    small = cv2.resize(view, (max(1, -(-width // block)), max(1, -(-height // block))), interpolation=cv2.INTER_AREA)
    return np.ascontiguousarray(cv2.resize(small, (width, height), interpolation=cv2.INTER_NEAREST))


# MARK: Detection


def detect_faces(image: Image.Image) -> list[UnitRect]:
    """Faces found on the device with OpenCV's cascades, slightly enlarged so the edges are covered too."""
    gray = cv2.cvtColor(np.asarray(image.convert("RGB")), cv2.COLOR_RGB2GRAY)
    scale = min(1.0, 1280 / max(gray.shape))
    if scale < 1:
        gray = cv2.resize(gray, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
    gray = cv2.equalizeHist(gray)
    boxes: list[tuple[int, int, int, int]] = []
    minimum = max(24, int(min(gray.shape) * 0.04))
    for name in ("haarcascade_frontalface_default.xml", "haarcascade_frontalface_alt2.xml",
                 "haarcascade_profileface.xml"):
        cascade = cv2.CascadeClassifier(os.path.join(cv2.data.haarcascades, name))
        if cascade.empty():
            continue
        found = cascade.detectMultiScale(gray, scaleFactor=1.1, minNeighbors=5, minSize=(minimum, minimum))
        boxes += [tuple(int(v) for v in b) for b in found]
    height, width = gray.shape
    rects = [UnitRect(x / width, y / height, w / width, h / height) for x, y, w, h in _merge(boxes)]
    return [r.inflate(0.15) for r in rects]


def _merge(boxes: list[tuple[int, int, int, int]]) -> list[tuple[int, int, int, int]]:
    """Boxes that overlap by half or more are one face."""
    merged: list[tuple[int, int, int, int]] = []
    for box in sorted(boxes, key=lambda b: -b[2] * b[3]):
        x, y, w, h = box
        for other in merged:
            ox, oy, ow, oh = other
            inter = max(0, min(x + w, ox + ow) - max(x, ox)) * max(0, min(y + h, oy + oh) - max(y, oy))
            if inter >= 0.4 * min(w * h, ow * oh):
                break
        else:
            merged.append(box)
    return merged


def available_ocr_languages() -> list[str]:
    """Tesseract's installed languages, the ones Mangosteen speaks first."""
    if not capabilities.has_tesseract():
        return []
    try:
        listing = external.run("tesseract", ["--list-langs"])
    except (external.ToolFailure, external.ToolMissing):
        return []
    installed = {line.strip() for line in listing.splitlines()[1:] if line.strip() and line.strip() != "osd"}
    preferred = [code for code in ("rus", "eng", "spa") if code in installed]
    return preferred or sorted(installed)[:3]


def detect_text(image: Image.Image) -> list[UnitRect]:
    """Lines of text found with Tesseract, slightly enlarged so the edges are covered too."""
    import tempfile

    languages = available_ocr_languages()
    if not languages:
        raise external.ToolMissing("tesseract")
    with tempfile.TemporaryDirectory(prefix="mangosteen-") as folder:
        path = os.path.join(folder, "page.png")
        image.convert("RGB").save(path)
        tsv = external.run("tesseract", [path, "stdout", "-l", "+".join(languages), "--psm", "11", "tsv"])
    lines: dict[tuple[str, str, str, str], list[int]] = {}
    for row in tsv.splitlines()[1:]:
        cells = row.split("\t")
        if len(cells) < 12 or not cells[11].strip():
            continue
        try:
            confidence = float(cells[10])
            left, top, width, height = (int(c) for c in cells[6:10])
        except ValueError:
            continue
        if confidence < 30 or width <= 0 or height <= 0:
            continue
        key = (cells[1], cells[2], cells[3], cells[4])
        box = lines.setdefault(key, [left, top, left + width, top + height])
        box[0], box[1] = min(box[0], left), min(box[1], top)
        box[2], box[3] = max(box[2], left + width), max(box[3], top + height)
    w, h = image.size
    return [UnitRect(l / w, t / h, (r - l) / w, (b - t) / h).inflate(0.08) for l, t, r, b in lines.values()]


def redact_file(path: str, regions: list[UnitRect], style: RedactionStyle, color: RGBA,
                options: ConversionOptions) -> str:
    """Writes `<name> (redacted).<ext>` without any metadata, so location and camera data are not leaked."""
    source = detect(path)
    if source is None:
        raise ValueError(f"Unknown format of {os.path.basename(path)}.")
    image, _ = images.load(path)
    result = apply(image, regions, style, color)
    target = source if source in format_catalog.EDITABLE_IMAGE_FORMATS else FileFormat.PNG

    def produce(output: str) -> None:
        images.write(result, target, output, options, None)

    return output_naming.write_atomically(os.path.dirname(os.path.abspath(path)),
                                          f"{output_naming.base_name(path)} ({L('redacted')})", target.extension, produce)


__all__ = ["apply", "detect_faces", "detect_text", "redact_file", "RedactionStyle", "re"]
