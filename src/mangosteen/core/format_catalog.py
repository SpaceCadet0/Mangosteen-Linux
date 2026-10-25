"""Which output formats are offered for which inputs."""

from __future__ import annotations

import os
from collections.abc import Iterable, Sequence

from . import capabilities
from .file_format import Category, FileFormat, detect

F = FileFormat

# Written with Pillow; HEIC needs pillow-heif, AVIF needs Pillow 11.3+, video and audio need ffmpeg.
_IMAGE_OUTPUT_ORDER = [F.PNG, F.JPG, F.WEBP, F.HEIC, F.TIFF, F.AVIF, F.GIF, F.PDF]

# Formats the editors (crop, editor, annotate, background, hide…) save an edited image in: the image targets
# without PDF, plus BMP, so an edited BMP stays a BMP. Anything else is saved as PNG.
EDITABLE_IMAGE_FORMATS = frozenset({F.PNG, F.JPG, F.WEBP, F.TIFF, F.GIF, F.BMP})

VIDEO_OUTPUTS = [F.MP4, F.MOV, F.MKV, F.WEBM, F.AVI, F.WMV, F.GIF, F.MP3]
AUDIO_OUTPUTS = [F.MP3, F.M4A, F.WAV, F.FLAC, F.OGG, F.OPUS, F.AIFF, F.WMA]
PDF_OUTPUTS = [F.PNG, F.JPG, F.TXT, F.MD, F.RTF, F.DOCX, F.HTML]
DOCUMENT_OUTPUTS = [F.PDF, F.DOCX, F.ODT, F.RTF, F.TXT, F.MD, F.HTML]
SUBTITLE_OUTPUTS = [F.SRT, F.VTT, F.TXT]
TABLE_OUTPUTS = [F.CSV, F.TSV, F.XLSX]
ARCHIVE_OUTPUTS = [F.ZIP, F.TAR, F.TGZ]

_BASE_IMAGE_INPUTS = frozenset({F.PNG, F.JPG, F.TIFF, F.BMP, F.GIF, F.ICO, F.ICNS, F.WEBP, F.SVG, F.PSD, F.JP2, F.TGA})

# Order of segments on the wheel when the selection mixes kinds of files.
_DISPLAY_ORDER = [
    F.PNG, F.JPG, F.WEBP, F.HEIC, F.TIFF, F.AVIF, F.GIF, F.PDF,
    F.DOCX, F.ODT, F.RTF, F.TXT, F.MD, F.HTML,
    F.SRT, F.VTT, F.CSV, F.TSV, F.XLSX,
    F.MP4, F.MOV, F.MKV, F.WEBM, F.AVI, F.WMV,
    F.MP3, F.M4A, F.WAV, F.FLAC, F.OGG, F.OPUS, F.AIFF, F.WMA,
    F.ZIP, F.TAR, F.TGZ,
]


def image_outputs() -> list[FileFormat]:
    return [f for f in _IMAGE_OUTPUT_ORDER
            if (f is not F.HEIC or capabilities.has_heic()) and (f is not F.AVIF or capabilities.has_avif())]


def image_inputs() -> frozenset[FileFormat]:
    extra = set()
    if capabilities.has_heic():
        extra.add(F.HEIC)
    if capabilities.has_avif() or capabilities.has_heic():
        extra.add(F.AVIF)
    return _BASE_IMAGE_INPUTS | extra


def is_page_image(fmt: FileFormat) -> bool:
    """An image that becomes one page when several are converted to a single PDF (raster, readable)."""
    return fmt.is_raster_image and fmt in image_inputs()


def split_for_pdf(paths: Sequence[str]) -> tuple[list[str], list[str]]:
    """Converting to PDF: two or more photos go into one PDF (a page each, in the selection's order);
    everything else in the selection, and a single photo, is converted on its own."""
    pages = [p for p in paths if (f := detect(p)) is not None and is_page_image(f)]
    if len(pages) < 2:
        return [], list(paths)
    return pages, [p for p in paths if p not in pages]


def can_read(fmt: FileFormat) -> bool:
    """Formats Mangosteen can read as a conversion source."""
    category = fmt.category
    if category is Category.IMAGE:
        return fmt in image_inputs()
    if category is Category.DOCUMENT:
        return fmt is not F.DOC
    if category.is_media:
        return capabilities.has_ffmpeg()
    return True


def outputs(category: Category) -> list[FileFormat]:
    if category is Category.IMAGE:
        return image_outputs()
    if category is Category.PDF:
        return list(PDF_OUTPUTS)
    if category is Category.DOCUMENT:
        return list(DOCUMENT_OUTPUTS)
    if category is Category.SUBTITLE:
        return list(SUBTITLE_OUTPUTS)
    if category is Category.TABLE:
        return list(TABLE_OUTPUTS)
    if category is Category.ARCHIVE:
        return list(ARCHIVE_OUTPUTS)
    if category is Category.VIDEO:
        return list(VIDEO_OUTPUTS) if capabilities.has_ffmpeg() else []
    return list(AUDIO_OUTPUTS) if capabilities.has_ffmpeg() else []


def targets_for_format(source: FileFormat) -> list[FileFormat]:
    if not can_read(source):
        return []
    return [f for f in outputs(source.category) if f is not source]


def conversion(path: str) -> tuple[FileFormat | None, list[FileFormat]]:
    """The detected format of an item (None for folders) and what it can become."""
    source = detect(path)
    if source is not None:
        return source, targets_for_format(source)
    return None, (list(ARCHIVE_OUTPUTS) if os.path.isdir(path) else [])


def targets(paths: Iterable[str]) -> list[FileFormat]:
    """Formats offered for a selection. A format is offered when every convertible item can either be
    converted to it or already is it (those items are skipped), and at least one item needs converting.
    Items that cannot be converted at all are ignored."""
    items = [c for c in (conversion(p) for p in paths) if c[1]]
    if not items:
        return []
    # A single kind of file keeps that kind's own order (video: MP4 first, GIF near the end).
    categories = {(source.category if source else Category.ARCHIVE) for source, _ in items}
    order = outputs(next(iter(categories))) if len(categories) == 1 else _DISPLAY_ORDER
    return [
        target for target in order
        if all(source is target or target in options for source, options in items)
        and any(source is not target for source, _ in items)
    ]
