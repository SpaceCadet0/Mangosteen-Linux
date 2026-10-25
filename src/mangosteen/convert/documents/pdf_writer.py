"""Lays a document out on A4 pages with Qt's text engine and writes it as PDF."""

from __future__ import annotations

from .. import qtutil
from .rich import Block, BlockType, RichDocument, Run

_HEADING_SIZES = [20, 16, 14, 12.5, 11.5, 11]
_BODY_SIZE = 11
_CODE_SIZE = 9.5
_LINK_COLOR = "#0563C1"


def _build(document: RichDocument, title: str):  # noqa: ANN202
    from PySide6.QtGui import (QColor, QFont, QTextBlockFormat, QTextCharFormat, QTextCursor, QTextDocument,
                               QTextListFormat)

    text = QTextDocument()
    text.setDocumentMargin(0)
    text.setMetaInformation(QTextDocument.MetaInformation.DocumentTitle, title)
    base = QFont("Sans Serif")
    base.setPointSizeF(_BODY_SIZE)
    text.setDefaultFont(base)
    cursor = QTextCursor(text)
    first = True
    current_list = None
    for block in document.blocks:
        block_format = QTextBlockFormat()
        block_format.setBottomMargin(6)
        char_format = QTextCharFormat()
        if block.type is BlockType.HEADING:
            level = max(1, min(block.level, 6))
            block_format.setTopMargin(12)
            block_format.setHeadingLevel(level)
            char_format.setFontPointSize(_HEADING_SIZES[level - 1])
            char_format.setFontWeight(QFont.Weight.Bold)
            current_list = None
        elif block.type is BlockType.CODE:
            block_format.setBottomMargin(0)
            block_format.setBackground(QColor("#F4F4F4"))
            char_format.setFontFamilies(["Monospace"])
            char_format.setFontFixedPitch(True)
            char_format.setFontPointSize(_CODE_SIZE)
            current_list = None
        elif block.type is BlockType.LIST_ITEM:
            block_format.setBottomMargin(2)
        else:
            current_list = None

        if first:
            cursor.setBlockFormat(block_format)
            first = False
        else:
            cursor.insertBlock(block_format, char_format)
        cursor.setBlockCharFormat(char_format)

        if block.type is BlockType.LIST_ITEM:
            list_format = QTextListFormat()
            list_format.setStyle(QTextListFormat.Style.ListDecimal if block.ordered else QTextListFormat.Style.ListDisc)
            list_format.setIndent(block.level + 1)
            if current_list is None or current_list.format().style() != list_format.style() \
                    or current_list.format().indent() != list_format.indent():
                current_list = cursor.createList(list_format)
            else:
                current_list.add(cursor.block())

        for run in block.runs:
            _insert_run(cursor, run, char_format, block.type is BlockType.CODE)
    return text


def _insert_run(cursor, run: Run, block_format, in_code: bool) -> None:  # noqa: ANN001
    from PySide6.QtGui import QColor, QFont, QTextCharFormat

    fmt = QTextCharFormat(block_format)
    if run.bold:
        fmt.setFontWeight(QFont.Weight.Bold)
    if run.italic:
        fmt.setFontItalic(True)
    if run.underline:
        fmt.setFontUnderline(True)
    if run.code and not in_code:
        fmt.setFontFamilies(["Monospace"])
        fmt.setFontFixedPitch(True)
    if run.link:
        fmt.setAnchor(True)
        fmt.setAnchorHref(run.link)
        fmt.setForeground(QColor(_LINK_COLOR))
        fmt.setFontUnderline(True)
    text = run.text.replace("\n", " ")
    cursor.insertText(text, fmt)


def write_document(document: RichDocument, title: str, output: str) -> None:
    from PySide6.QtCore import QMarginsF
    from PySide6.QtGui import QPageLayout, QPageSize, QPdfWriter

    qtutil.ensure_gui_app()
    writer = QPdfWriter(output)
    writer.setTitle(title)
    writer.setPageSize(QPageSize(QPageSize.PageSizeId.A4))
    writer.setPageMargins(QMarginsF(20, 20, 20, 20), QPageLayout.Unit.Millimeter)
    writer.setResolution(300)
    text = _build(document, title)
    text.print_(writer)
