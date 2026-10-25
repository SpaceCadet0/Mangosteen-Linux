"""Image to image conversion with Pillow (JPEG, PNG, WebP, TIFF, GIF, BMP, HEIC, AVIF, PDF) and Qt for SVG."""

from __future__ import annotations

import io
import os
from dataclasses import dataclass, field

import numpy as np
from PIL import Image, ImageOps, ImageSequence

from ..core import capabilities
from ..core.file_format import FileFormat, detect
from ..core.settings import ConversionOptions
from . import pdf_images, qtutil

Image.MAX_IMAGE_PIXELS = 1_000_000_000

# SVG has no pixel size of its own; it is rasterised so the longer side is at least this many pixels.
SVG_MINIMUM_PIXEL_SIZE = 2048

_heif_registered = False


def register_plugins() -> None:
    """HEIC reading and writing come from pillow-heif; it registers itself with Pillow."""
    global _heif_registered
    if _heif_registered:
        return
    _heif_registered = True
    if capabilities.has_heic():
        import pillow_heif

        pillow_heif.register_heif_opener()


class UnreadableImage(Exception):
    pass


@dataclass
class Metadata:
    """What is carried over from the source into the result."""

    exif: bytes | None = None
    icc_profile: bytes | None = None
    dpi: tuple[float, float] | None = None
    info: dict = field(default_factory=dict)


# MARK: Reading


def _normalize(image: Image.Image) -> Image.Image:
    """8-bit grey, RGB or RGBA, whatever the file stored (palette, 16-bit, CMYK, LAB…)."""
    mode = image.mode
    if mode in ("RGB", "RGBA", "L", "LA"):
        return image.convert("RGBA") if mode == "LA" else image
    if mode in ("I;16", "I;16L", "I;16B", "I"):
        array = np.asarray(image, dtype=np.float64)
        top = array.max() if array.size else 1
        scale = 255.0 / (65535.0 if top > 255 else 255.0)
        return Image.fromarray(np.clip(array * scale, 0, 255).astype(np.uint8), "L")
    if mode == "F":
        array = np.asarray(image, dtype=np.float64)
        return Image.fromarray(np.clip(array * 255.0, 0, 255).astype(np.uint8), "L")
    if mode in ("P", "PA") or "transparency" in image.info:
        return image.convert("RGBA")
    if mode == "1":
        return image.convert("L")
    return image.convert("RGB")


def _metadata_of(image: Image.Image) -> Metadata:
    """The metadata of an image whose pixels are already upright (its orientation tag is gone)."""
    exif = None
    try:
        data = image.getexif()
        if len(data):
            data[0x0112] = 1
            exif = data.tobytes()
    except Exception:  # noqa: BLE001 - damaged EXIF is simply not carried over
        exif = None
    dpi = image.info.get("dpi")
    return Metadata(exif, image.info.get("icc_profile"),
                    (float(dpi[0]), float(dpi[1])) if isinstance(dpi, tuple) and len(dpi) == 2 else None)


def load(path: str, max_pixel_size: int | None = None) -> tuple[Image.Image, Metadata]:
    """Decodes the primary image upright (EXIF orientation applied), optionally downscaled so its longer side is at
    most `max_pixel_size`. Returns the image together with the source metadata."""
    register_plugins()
    if detect(path) is FileFormat.SVG:
        return rasterize_svg(path, max_pixel_size), Metadata()
    try:
        with Image.open(path) as source:
            source.load() if max_pixel_size is None else _draft(source, max_pixel_size)
            upright = ImageOps.exif_transpose(source)
            metadata = _metadata_of(upright)
            image = _normalize(upright)
            image.load()
    except (OSError, ValueError, SyntaxError, Image.DecompressionBombError) as error:
        raise UnreadableImage(os.path.basename(path)) from error
    if max_pixel_size is not None and max(image.size) > max_pixel_size:
        image.thumbnail((max_pixel_size, max_pixel_size), Image.Resampling.LANCZOS)
    return image, metadata


def _draft(source: Image.Image, size: int) -> None:
    """Lets JPEG decode at a reduced scale, which is much faster for previews."""
    if source.format == "JPEG":
        source.draft(None, (size, size))
    source.load()


def frames(path: str) -> list[Image.Image]:
    """Every frame of an animated GIF or multi-page TIFF, upright and normalised; one image otherwise."""
    register_plugins()
    try:
        with Image.open(path) as source:
            if getattr(source, "n_frames", 1) <= 1:
                return [load(path)[0]]
            result = []
            for frame in ImageSequence.Iterator(source):
                copy = frame.copy()
                copy.info = dict(frame.info)
                result.append(_normalize(ImageOps.exif_transpose(copy)))
            return result
    except (OSError, ValueError, SyntaxError) as error:
        raise UnreadableImage(os.path.basename(path)) from error


def rasterize_svg(path: str, max_pixel_size: int | None = None) -> Image.Image:
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QImage, QPainter
    from PySide6.QtSvg import QSvgRenderer

    qtutil.ensure_gui_app()
    renderer = QSvgRenderer(path)
    if not renderer.isValid():
        raise UnreadableImage(os.path.basename(path))
    size = renderer.defaultSize()
    if size.width() <= 0 or size.height() <= 0:
        raise UnreadableImage(os.path.basename(path))
    longest = max_pixel_size or SVG_MINIMUM_PIXEL_SIZE
    scale = longest / max(size.width(), size.height())
    width, height = max(1, round(size.width() * scale)), max(1, round(size.height() * scale))
    qimage = QImage(width, height, QImage.Format.Format_ARGB32_Premultiplied)
    qimage.fill(Qt.GlobalColor.transparent)
    painter = QPainter(qimage)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    renderer.render(painter)
    painter.end()
    return qtutil.qimage_to_pil(qimage)


# MARK: Pixels


def has_alpha(image: Image.Image) -> bool:
    return image.mode in ("RGBA", "LA") or "transparency" in image.info


def flatten_on_white(image: Image.Image) -> Image.Image:
    """Composites onto white for formats without transparency."""
    if not has_alpha(image):
        return image.convert("RGB") if image.mode not in ("RGB", "L") else image
    rgba = image.convert("RGBA")
    background = Image.new("RGBA", rgba.size, (255, 255, 255, 255))
    return Image.alpha_composite(background, rgba).convert("RGB")


def _has_soft_alpha(image: Image.Image) -> bool:
    if image.mode != "RGBA":
        return False
    alpha = np.asarray(image.getchannel("A"))
    return bool(((alpha > 0) & (alpha < 255)).any())


# MARK: Writing


def encode(image: Image.Image, target: FileFormat, quality: float | None = None, metadata: Metadata | None = None,
           extra_frames: list[Image.Image] | None = None, durations: list[int] | None = None, loop: int = 0) -> bytes:
    """Encodes in memory. `quality` is 0…1 and only used by lossy formats."""
    buffer = io.BytesIO()
    _save(image, target, buffer, quality, metadata, extra_frames, durations, loop)
    return buffer.getvalue()


def _save(image: Image.Image, target: FileFormat, out, quality: float | None, metadata: Metadata | None,
          extra_frames: list[Image.Image] | None = None, durations: list[int] | None = None, loop: int = 0) -> None:
    register_plugins()
    metadata = metadata or Metadata()
    keywords: dict = {}
    if metadata.exif is not None and target in (FileFormat.JPG, FileFormat.PNG, FileFormat.WEBP, FileFormat.TIFF,
                                                FileFormat.HEIC, FileFormat.AVIF):
        keywords["exif"] = metadata.exif
    if metadata.icc_profile and target in (FileFormat.JPG, FileFormat.PNG, FileFormat.WEBP, FileFormat.TIFF,
                                           FileFormat.HEIC, FileFormat.AVIF):
        keywords["icc_profile"] = metadata.icc_profile
    if metadata.dpi and target in (FileFormat.JPG, FileFormat.PNG, FileFormat.TIFF):
        keywords["dpi"] = metadata.dpi
    q = int(round((quality if quality is not None else 0.85) * 100))
    all_frames = [image, *(extra_frames or [])]

    if target is FileFormat.JPG:
        flatten_on_white(image).convert("RGB").save(out, "JPEG", quality=q, optimize=True, **keywords)
    elif target is FileFormat.PNG:
        image.save(out, "PNG", **keywords)
    elif target is FileFormat.WEBP:
        if len(all_frames) > 1:
            all_frames[0].save(out, "WEBP", save_all=True, append_images=all_frames[1:], quality=q,
                               duration=durations or 100, loop=loop, **keywords)
        else:
            image.save(out, "WEBP", quality=q, method=4, **keywords)
    elif target is FileFormat.TIFF:
        if len(all_frames) > 1:
            all_frames[0].save(out, "TIFF", save_all=True, append_images=all_frames[1:], compression="tiff_lzw",
                               **keywords)
        else:
            image.save(out, "TIFF", compression="tiff_lzw", **keywords)
    elif target is FileFormat.BMP:
        flatten_on_white(image).convert("RGB").save(out, "BMP")
    elif target is FileFormat.GIF:
        prepared = [flatten_on_white(f).convert("RGB") if _has_soft_alpha(f) else f for f in all_frames]
        if len(prepared) > 1:
            prepared[0].save(out, "GIF", save_all=True, append_images=prepared[1:], duration=durations or 100,
                             loop=loop, disposal=2)
        else:
            prepared[0].save(out, "GIF")
    elif target is FileFormat.HEIC:
        image.convert("RGBA" if has_alpha(image) else "RGB").save(out, "HEIF", quality=q, **keywords)
    elif target is FileFormat.AVIF:
        image.convert("RGBA" if has_alpha(image) else "RGB").save(out, "AVIF", quality=q, **keywords)
    else:
        raise ValueError(f"{target.display_name} images cannot be written.")


def write(image: Image.Image, target: FileFormat, output: str, options: ConversionOptions,
          metadata: Metadata | None = None) -> None:
    """Encodes a single already-decoded image (rendered PDF pages, SVG, edited photos)."""
    if target is FileFormat.PDF:
        pdf_images.write_pdf([pdf_images.PdfPage(image, None, metadata.dpi if metadata else None)], output)
        return
    with open(output, "wb") as stream:
        _save(image, target, stream, options.quality(target), metadata if options.preserve_metadata else None)


def convert(input_path: str, target: FileFormat, output: str, options: ConversionOptions) -> None:
    """Converts `input_path` into a new file at `output`."""
    source_format = detect(input_path)
    if source_format is FileFormat.SVG and target is FileFormat.PDF:
        pdf_images.svg_to_pdf(input_path, output)
        return
    register_plugins()
    if target is FileFormat.PDF:
        keep_jpeg = source_format is FileFormat.JPG
        image, metadata = load(input_path)
        pdf_images.write_pdf(
            [pdf_images.PdfPage(image, _jpeg_bytes(input_path) if keep_jpeg and _is_upright_jpeg(input_path) else None,
                                metadata.dpi)], output)
        return
    # Keep every frame where the target can hold several (animated GIF, multi-page TIFF).
    if target in (FileFormat.GIF, FileFormat.TIFF, FileFormat.WEBP) and source_format in (FileFormat.GIF, FileFormat.TIFF,
                                                                                         FileFormat.WEBP):
        sequence = frames(input_path)
        if len(sequence) > 1:
            durations = _durations(input_path)
            with open(output, "wb") as stream:
                _save(sequence[0], target, stream, options.quality(target), None, sequence[1:], durations)
            return
    image, metadata = load(input_path)
    write(image, target, output, options, metadata)


def _durations(path: str) -> list[int] | None:
    try:
        with Image.open(path) as source:
            return [int(f.info.get("duration", 100)) or 100 for f in ImageSequence.Iterator(source)]
    except (OSError, ValueError):
        return None


def _is_upright_jpeg(path: str) -> bool:
    try:
        with Image.open(path) as source:
            return (source.format == "JPEG" and source.mode in ("RGB", "L")
                    and source.getexif().get(0x0112, 1) == 1)
    except (OSError, ValueError):
        return False


def _jpeg_bytes(path: str) -> bytes:
    with open(path, "rb") as stream:
        return stream.read()
