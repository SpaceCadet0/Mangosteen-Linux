"""Reads any supported document into the common model and writes it out in another format."""

from __future__ import annotations

from ...core import output_naming, text_file
from ...core.file_format import FileFormat
from . import docx, html, markdown, odt, rtf
from .rich import RichDocument


def read(path: str, fmt: FileFormat) -> RichDocument:
    if fmt is FileFormat.TXT:
        return RichDocument.from_plain_text(text_file.read(path))
    if fmt is FileFormat.MD:
        return markdown.parse(text_file.read(path))
    if fmt is FileFormat.HTML:
        return html.parse(text_file.read(path))
    if fmt is FileFormat.DOCX:
        return docx.read(path)
    if fmt is FileFormat.ODT:
        return odt.read(path)
    if fmt is FileFormat.RTF:
        with open(path, "rb") as stream:
            return rtf.parse(stream.read())
    if fmt is FileFormat.PDF:
        from .. import pdf

        return pdf.read_document(path)
    raise ValueError(f"{fmt.display_name} documents cannot be read.")


def write(document: RichDocument, fmt: FileFormat, output: str, title: str) -> None:
    """Writes every text format and PDF."""
    if fmt is FileFormat.TXT:
        text_file.write(output, document.to_plain_text())
    elif fmt is FileFormat.MD:
        text_file.write(output, markdown.write(document))
    elif fmt is FileFormat.HTML:
        text_file.write(output, html.write(document, title))
    elif fmt is FileFormat.DOCX:
        docx.write(document, output)
    elif fmt is FileFormat.ODT:
        odt.write(document, output)
    elif fmt is FileFormat.RTF:
        with open(output, "w", encoding="ascii", newline="") as stream:
            stream.write(rtf.write(document))
    elif fmt is FileFormat.PDF:
        from . import pdf_writer

        pdf_writer.write_document(document, title, output)
    else:
        raise ValueError(f"Documents cannot be written as {fmt.display_name}.")


def convert(input_path: str, source: FileFormat, target: FileFormat, output: str) -> None:
    """Converts between document formats through the common model."""
    write(read(input_path, source), target, output, output_naming.base_name(input_path))
