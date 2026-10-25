"""Entry point for format conversion: picks the converter and writes the result next to the input."""

from __future__ import annotations

import os
from collections.abc import Callable

from ..core import format_catalog, loc, output_naming
from ..core.cancellation import CancellationToken
from ..core.file_format import Category, FileFormat
from ..core.settings import ConversionOptions
from . import archives, images, media, pdf, subtitles, tables
from .documents import converter as documents


class ConversionError(Exception):
    pass


def convert(input_path: str, target: FileFormat, options: ConversionOptions | None = None,
            cancellation: CancellationToken | None = None,
            progress: Callable[[float], None] | None = None) -> str | None:
    """Converts `input_path` and returns the new file or folder, or None when it already has that format."""
    options = options or ConversionOptions()
    source, targets = format_catalog.conversion(input_path)
    if source is target:
        return None
    name = os.path.basename(input_path.rstrip("/\\"))
    if target not in targets:
        if source is not None:
            raise ConversionError(f"{source.display_name} cannot be converted to {target.display_name}.")
        raise ConversionError(f"{name} cannot be converted.")
    path = os.path.abspath(input_path.rstrip("/\\"))
    directory = os.path.dirname(path)
    base = os.path.basename(path) if source is None else output_naming.base_name(path)

    # Several PDF pages become a folder of images.
    if source is FileFormat.PDF and target.category is Category.IMAGE and pdf.page_count(path) > 1:
        return output_naming.write_atomically(
            directory, f"{base} ({target.display_name})", "",
            lambda folder: pdf.render_pages(path, target, folder, base, options, cancellation, progress))

    # A workbook with several sheets becomes a folder with one table per sheet.
    if source is FileFormat.XLSX:
        from . import xlsx

        sheets = [s for s in xlsx.read(path) if s.rows]
        if len(sheets) > 1:
            return output_naming.write_atomically(
                directory, f"{base} ({target.display_name})", "",
                lambda folder: tables.write_sheets(sheets, target, folder))

    def produce(output: str) -> None:
        if source is None:
            archives.pack([path], target, output)
            return
        category = source.category
        if category is Category.IMAGE:
            images.convert(path, target, output, options)
        elif category is Category.PDF:
            pdf.convert(path, target, output, options)
        elif category is Category.DOCUMENT:
            documents.convert(path, source, target, output)
        elif category is Category.SUBTITLE:
            subtitles.convert(path, target, output)
        elif category is Category.TABLE:
            tables.convert(path, source, target, output)
        elif category is Category.ARCHIVE:
            archives.repack(path, source, target, output)
        else:
            media.convert(path, target, output, progress, cancellation)

    return output_naming.write_atomically(directory, base, target.extension, produce)


def describe_error(error: BaseException, name: str) -> str:
    """The failure as shown in a notification; a PDF under a password says so instead of a reader error."""
    if isinstance(error, pdf.PdfLocked):
        return str(error)
    text = str(error) or type(error).__name__
    return f"{name}: {text}"


__all__ = ["convert", "describe_error", "ConversionError", "loc"]
