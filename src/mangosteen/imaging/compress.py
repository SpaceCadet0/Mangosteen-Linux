"""Image size reduction by quality, preset, or a target file size."""

from __future__ import annotations

import math
import os
from dataclasses import dataclass, replace
from enum import Enum

from PIL import Image

from ..convert import images
from ..core import capabilities, loc, output_naming
from ..core.file_format import FileFormat, detect
from ..core.loc import L


class NotSmaller(Exception):
    def __init__(self, original: int, result: int) -> None:
        super().__init__(L("The compressed file ({0}) is not smaller than the original ({1}). "
                           "Choose another format or a smaller size.").format(human_size(result), human_size(original)))
        self.original, self.result = original, result


class Mode(Enum):
    PRESET = "preset"
    QUALITY = "quality"
    TARGET_SIZE = "target_size"


class Preset(Enum):
    HIGH = "high"
    BALANCED = "balanced"
    SMALL = "small"

    @property
    def quality(self) -> float:
        return {Preset.HIGH: 0.85, Preset.BALANCED: 0.7, Preset.SMALL: 0.45}[self]

    @property
    def title(self) -> str:
        return {Preset.HIGH: L("High quality"), Preset.BALANCED: L("Balanced"), Preset.SMALL: L("Smallest size")}[self]

    @property
    def detail(self) -> str:
        return {Preset.HIGH: L("Best quality with moderate savings"),
                Preset.BALANCED: L("Noticeably smaller file, almost no visible loss"),
                Preset.SMALL: L("The smallest files, quality loss is more noticeable")}[self]


SIZE_LIMITS = [4096, 3840, 2560, 1920, 1600, 1280, 1024, 800]


@dataclass(frozen=True)
class CompressionSettings:
    mode: Mode = Mode.PRESET
    preset: Preset = Preset.BALANCED
    quality: float = 0.7  # 0.05…1
    target_bytes: int = 1_000_000  # upper bound for each output file in target-size mode
    max_pixel_size: int | None = None  # longer side limit; None keeps the original size
    format: FileFormat | None = None  # None keeps the original format when it is lossy, else picks a default
    preserve_metadata: bool = True

    @property
    def effective_max_pixel_size(self) -> int | None:
        if self.mode is Mode.PRESET and self.preset is Preset.SMALL:
            return self.max_pixel_size or 2560
        return self.max_pixel_size


def selectable_formats() -> list[FileFormat]:
    formats = [FileFormat.JPG, FileFormat.WEBP]
    if capabilities.has_heic():
        formats.append(FileFormat.HEIC)
    if capabilities.has_avif():
        formats.append(FileFormat.AVIF)
    return formats


def default_lossy_format() -> FileFormat:
    """Formats with transparency fall back to one that keeps it."""
    return FileFormat.WEBP


def output_format(source: FileFormat, settings: CompressionSettings) -> FileFormat:
    if settings.format is not None:
        return settings.format
    return source if source.is_lossy else default_lossy_format()


def best_fit(encode, limit: int, steps: int = 7) -> bytes | None:  # noqa: ANN001
    """Binary search over quality 0.05…0.95; None when even the lowest quality is too big."""
    low, high = 0.05, 0.95
    best: bytes | None = None
    for _ in range(steps):
        quality = (low + high) / 2
        data = encode(quality)
        if len(data) <= limit:
            best, low = data, quality
        else:
            high = quality
    if best is None:
        smallest = encode(0.05)
        if len(smallest) <= limit:
            best = smallest
    return best


def shrink_to_fit(width: int, height: int, smallest_bytes: int, limit: int) -> tuple[int, int]:
    """The size to try next when even the lowest quality is too big: shrink by the square root of the ratio."""
    ratio = min(math.sqrt(limit / max(smallest_bytes, 1)) * 0.9, 0.9)
    return max(1, int(width * ratio)), max(1, int(height * ratio))


def fit_inside(width: int, height: int, max_side: int | None) -> tuple[int, int]:
    if max_side is None or max(width, height) <= max_side:
        return width, height
    scale = max_side / max(width, height)
    return max(1, round(width * scale)), max(1, round(height * scale))


def compress(path: str, settings: CompressionSettings) -> tuple[bytes, FileFormat]:
    """Compresses one image in memory."""
    source = detect(path)
    if source is None:
        raise ValueError(f"Unknown format of {os.path.basename(path)}.")
    target = output_format(source, settings)
    image, metadata = images.load(path, settings.effective_max_pixel_size)
    kept = metadata if settings.preserve_metadata else None

    def encode(candidate: Image.Image, quality: float | None) -> bytes:
        return images.encode(candidate, target, quality, kept)

    if settings.mode is Mode.PRESET:
        return encode(image, settings.preset.quality), target
    if settings.mode is Mode.QUALITY:
        return encode(image, settings.quality), target
    # Find the highest quality that fits; if even the lowest is too big, shrink the pixels and retry.
    for _ in range(6):
        if target.is_lossy:
            data = best_fit(lambda q: encode(image, q), settings.target_bytes)
        else:
            data = encode(image, None)
            data = data if len(data) <= settings.target_bytes else None
        if data is not None:
            return data, target
        smallest = encode(image, 0.05)
        width, height = shrink_to_fit(image.width, image.height, len(smallest), settings.target_bytes)
        image = image.resize((width, height), Image.Resampling.LANCZOS)
    return encode(image, 0.05), target


def compress_file(path: str, settings: CompressionSettings | None = None) -> str:
    """Compresses and writes `<name> (compressed).<ext>` next to the original. Raises `NotSmaller` instead of writing
    a bigger file."""
    settings = settings or CompressionSettings()
    original = os.path.getsize(path)
    if detect(path) is FileFormat.PDF:
        return compress_pdf(path, original)
    data, target = compress(path, settings)
    if len(data) >= original:
        raise NotSmaller(original, len(data))

    def produce(output: str) -> None:
        with open(output, "wb") as stream:
            stream.write(data)

    return output_naming.write_atomically(os.path.dirname(os.path.abspath(path)),
                                          f"{output_naming.base_name(path)} ({L('compressed')})", target.extension, produce)


def compress_pdf(path: str, original_size: int) -> str:
    """Re-encodes embedded images as JPEG at screen resolution and drops what no page needs."""
    from pypdf import PdfWriter

    from ..convert import pdf as pdf_module

    def produce(output: str) -> None:
        writer = PdfWriter(clone_from=pdf_module._reader(path))  # noqa: SLF001
        for page in writer.pages:
            for image in page.images:
                try:
                    pil = image.image
                    if pil is None:
                        continue
                    pil = pil.convert("RGB") if pil.mode not in ("RGB", "L") else pil
                    pil.thumbnail((1600, 1600), Image.Resampling.LANCZOS)
                    image.replace(pil, quality=65)
                except Exception:  # noqa: BLE001 - an image that cannot be re-encoded stays as it is
                    continue
        writer.compress_identical_objects(remove_identicals=True, remove_orphans=True)
        for page in writer.pages:
            page.compress_content_streams()
        with open(output, "wb") as stream:
            writer.write(stream)

    result = output_naming.write_atomically(os.path.dirname(os.path.abspath(path)),
                                            f"{output_naming.base_name(path)} ({L('compressed')})", "pdf", produce)
    size = os.path.getsize(result)
    if size >= original_size:
        os.remove(result)
        raise NotSmaller(original_size, size)
    return result


def human_size(bytes_: int) -> str:
    """"1.2 MB" with decimal units, like the other Mangosteen apps."""
    units = [L("B"), L("KB"), L("MB"), "GB"]
    value = float(bytes_)
    for unit in units:
        if value < 1000 or unit == units[-1]:
            text = f"{value:.0f}" if unit == units[0] else f"{value:.1f}".rstrip("0").rstrip(".")
            return f"{text} {unit}"
        value /= 1000
    return f"{bytes_} B"


__all__ = ["compress", "compress_file", "CompressionSettings", "Mode", "Preset", "NotSmaller", "replace", "loc"]
