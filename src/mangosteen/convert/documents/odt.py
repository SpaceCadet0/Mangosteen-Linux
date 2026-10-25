"""OpenDocument text (.odt): a ZIP with content.xml and styles.xml."""

from __future__ import annotations

import zipfile
from dataclasses import dataclass
from xml.etree import ElementTree as ET

from .. import archives
from .rich import Block, BlockType, Run, RichDocument

OFFICE = "urn:oasis:names:tc:opendocument:xmlns:office:1.0"
TEXT = "urn:oasis:names:tc:opendocument:xmlns:text:1.0"
STYLE = "urn:oasis:names:tc:opendocument:xmlns:style:1.0"
FO = "urn:oasis:names:tc:opendocument:xmlns:xsl-fo-compatible:1.0"
XLINK = "http://www.w3.org/1999/xlink"
MANIFEST = "urn:oasis:names:tc:opendocument:xmlns:manifest:1.0"
MIME_TYPE = "application/vnd.oasis.opendocument.text"
_HEADING_SIZES = [18, 15, 13, 12, 11, 11]

for _prefix, _uri in (("office", OFFICE), ("text", TEXT), ("style", STYLE), ("fo", FO), ("xlink", XLINK),
                      ("manifest", MANIFEST)):
    ET.register_namespace(_prefix, _uri)


def _q(ns: str, tag: str) -> str:
    return f"{{{ns}}}{tag}"


@dataclass(frozen=True)
class _TextStyle:
    bold: bool = False
    italic: bool = False
    underline: bool = False
    code: bool = False


# MARK: Reading


def read(path: str) -> RichDocument:
    archives.check_unpacked_size(path, "Pictures/", "Thumbnails/")
    with zipfile.ZipFile(path) as zf:
        names = set(zf.namelist())
        if "content.xml" not in names:
            raise ValueError("The document has no content.")
        content = ET.fromstring(zf.read("content.xml"))
        styles_root = ET.fromstring(zf.read("styles.xml")) if "styles.xml" in names else None
    styles: dict[str, _TextStyle] = {}
    ordered: set[str] = set()
    for source in (styles_root, content):
        if source is None:
            continue
        for style in source.iter(_q(STYLE, "style")):
            name = style.get(_q(STYLE, "name"))
            props = style.find(_q(STYLE, "text-properties"))
            if name is None:
                continue
            get = props.get if props is not None else (lambda *_: None)
            font = get(_q(STYLE, "font-name")) or get(_q(FO, "font-family")) or ""
            weight = get(_q(FO, "font-weight")) or ""
            underline = get(_q(STYLE, "text-underline-style"))
            styles[name] = _TextStyle(
                weight in ("bold", "600", "700", "800", "900") or "Strong" in name,
                get(_q(FO, "font-style")) == "italic" or "Emphasis" in name,
                underline is not None and underline != "none",
                any(f in font.lower() for f in ("mono", "courier", "consolas")) or "Source_20_Text" in name)
        for list_style in source.iter(_q(TEXT, "list-style")):
            name = list_style.get(_q(STYLE, "name"))
            if name and list_style.find(_q(TEXT, "list-level-style-number")) is not None:
                ordered.add(name)
    body = next(content.iter(_q(OFFICE, "text")), None)
    if body is None:
        raise ValueError("The document has no text.")
    document = RichDocument()
    _read_blocks(body, document, styles, ordered, 0, False)
    return document


def _read_blocks(parent: ET.Element, document: RichDocument, styles: dict[str, _TextStyle], ordered: set[str],
                 depth: int, is_ordered: bool) -> None:
    for element in parent:
        tag = element.tag
        if tag == _q(TEXT, "h"):
            try:
                level = max(1, min(int(element.get(_q(TEXT, "outline-level"), "1")), 6))
            except ValueError:
                level = 1
            block = Block(BlockType.HEADING, level)
            _read_inline(element, block, styles, _TextStyle(), None)
            document.blocks.append(block)
        elif tag == _q(TEXT, "p"):
            paragraph_style = styles.get(element.get(_q(TEXT, "style-name"), ""), _TextStyle())
            if depth > 0:
                block = Block(BlockType.LIST_ITEM, depth - 1, is_ordered)
            else:
                block = Block(BlockType.CODE if paragraph_style.code else BlockType.PARAGRAPH)
            _read_inline(element, block, styles,
                         _TextStyle(paragraph_style.bold, paragraph_style.italic, paragraph_style.underline, False),
                         None)
            document.blocks.append(block)
        elif tag == _q(TEXT, "list"):
            name = element.get(_q(TEXT, "style-name"))
            _read_blocks(element, document, styles, ordered, depth + 1, is_ordered if name is None else name in ordered)
        elif tag in (_q(TEXT, "list-item"), _q(TEXT, "list-header"), _q(TEXT, "section")) or \
                tag.rsplit("}", 1)[-1] in ("table", "table-row", "table-cell", "table-header-rows"):
            _read_blocks(element, document, styles, ordered, depth, is_ordered)


def _read_inline(element: ET.Element, block: Block, styles: dict[str, _TextStyle], style: _TextStyle,
                 link: str | None) -> None:
    def run(text: str, style: _TextStyle = style) -> None:
        block.add(Run(text, style.bold, style.italic, style.underline, link, style.code))

    if element.text:
        run(element.text.replace("\n", " "))
    for child in element:
        tag = child.tag
        if tag == _q(TEXT, "span"):
            known = styles.get(child.get(_q(TEXT, "style-name"), ""))
            inner = style if known is None else _TextStyle(style.bold or known.bold, style.italic or known.italic,
                                                           style.underline or known.underline, style.code or known.code)
            _read_inline(child, block, styles, inner, link)
        elif tag == _q(TEXT, "a"):
            _read_inline(child, block, styles, style, child.get(_q(XLINK, "href")) or link)
        elif tag == _q(TEXT, "s"):
            try:
                count = int(child.get(_q(TEXT, "c"), "1"))
            except ValueError:
                count = 1
            run(" " * count)
        elif tag == _q(TEXT, "tab"):
            run("\t")
        elif tag == _q(TEXT, "line-break"):
            run("\n")
        elif tag.rsplit("}", 1)[-1] in ("note", "annotation", "bookmark", "bookmark-start", "bookmark-end",
                                         "soft-page-break", "frame"):
            pass
        else:
            _read_inline(child, block, styles, style, link)
        if child.tail:
            run(child.tail.replace("\n", " "))


# MARK: Writing


def write(document: RichDocument, path: str) -> None:
    automatic = ET.Element(_q(OFFICE, "automatic-styles"))
    automatic.append(_list_style("L1", ordered=False))
    automatic.append(_list_style("L2", ordered=True))
    code_style = ET.SubElement(automatic, _q(STYLE, "style"), {_q(STYLE, "name"): "P_code", _q(STYLE, "family"): "paragraph"})
    ET.SubElement(code_style, _q(STYLE, "paragraph-properties"), {_q(FO, "background-color"): "#f4f4f4"})
    ET.SubElement(code_style, _q(STYLE, "text-properties"),
                  {_q(FO, "font-family"): "Consolas", _q(FO, "font-size"): "10pt"})
    text_styles: dict[tuple, str] = {}

    def style_for(run: Run) -> str | None:
        key = (run.bold, run.italic, run.underline, run.code)
        if not any(key):
            return None
        if key not in text_styles:
            name = f"T{len(text_styles) + 1}"
            text_styles[key] = name
            style = ET.SubElement(automatic, _q(STYLE, "style"), {_q(STYLE, "name"): name, _q(STYLE, "family"): "text"})
            props = ET.SubElement(style, _q(STYLE, "text-properties"))
            if run.bold:
                props.set(_q(FO, "font-weight"), "bold")
            if run.italic:
                props.set(_q(FO, "font-style"), "italic")
            if run.underline:
                props.set(_q(STYLE, "text-underline-style"), "solid")
                props.set(_q(STYLE, "text-underline-width"), "auto")
                props.set(_q(STYLE, "text-underline-color"), "font-color")
            if run.code:
                props.set(_q(FO, "font-family"), "Consolas")
        return text_styles[key]

    text = ET.Element(_q(OFFICE, "text"))
    lists: list[ET.Element] = []
    for block in document.blocks:
        if block.type is BlockType.LIST_ITEM:
            del lists[block.level + 1:]
            wanted = "L2" if block.ordered else "L1"
            if not lists or (len(lists) == block.level + 1 and lists[-1].get(_q(TEXT, "style-name")) != wanted):
                if lists:
                    lists.pop()
                top = ET.Element(_q(TEXT, "list"), {_q(TEXT, "style-name"): wanted})
                (text if not lists else _last_item(lists[-1])).append(top)
                lists.append(top)
            while len(lists) < block.level + 1:
                nested = ET.Element(_q(TEXT, "list"))
                _last_item(lists[-1]).append(nested)
                lists.append(nested)
            paragraph = ET.Element(_q(TEXT, "p"), {_q(TEXT, "style-name"): "Standard"})
            item = ET.SubElement(lists[-1], _q(TEXT, "list-item"))
            item.append(paragraph)
        else:
            lists.clear()
            if block.type is BlockType.HEADING:
                level = max(1, min(block.level, 6))
                paragraph = ET.SubElement(text, _q(TEXT, "h"), {_q(TEXT, "style-name"): f"Heading_20_{level}",
                                                                _q(TEXT, "outline-level"): str(level)})
            elif block.type is BlockType.CODE:
                paragraph = ET.SubElement(text, _q(TEXT, "p"), {_q(TEXT, "style-name"): "P_code"})
            else:
                paragraph = ET.SubElement(text, _q(TEXT, "p"), {_q(TEXT, "style-name"): "Standard"})
        for run in block.runs:
            target = paragraph
            if run.link:
                anchor = ET.SubElement(paragraph, _q(TEXT, "a"), {_q(XLINK, "type"): "simple", _q(XLINK, "href"): run.link})
                target = anchor
            style = None if block.type is BlockType.CODE else style_for(run)
            if style:
                target = ET.SubElement(target, _q(TEXT, "span"), {_q(TEXT, "style-name"): style})
            _add_text(target, run.text)

    content = ET.Element(_q(OFFICE, "document-content"), {_q(OFFICE, "version"): "1.2"})
    content.append(automatic)
    ET.SubElement(content, _q(OFFICE, "body")).append(text)

    styles = ET.Element(_q(OFFICE, "document-styles"), {_q(OFFICE, "version"): "1.2"})
    section = ET.SubElement(styles, _q(OFFICE, "styles"))
    default = ET.SubElement(section, _q(STYLE, "default-style"), {_q(STYLE, "family"): "paragraph"})
    ET.SubElement(default, _q(STYLE, "text-properties"), {_q(FO, "font-size"): "11pt", _q(STYLE, "font-name"): "Calibri"})
    standard = ET.SubElement(section, _q(STYLE, "style"), {_q(STYLE, "name"): "Standard", _q(STYLE, "family"): "paragraph"})
    ET.SubElement(standard, _q(STYLE, "paragraph-properties"), {_q(FO, "margin-bottom"): "0.21cm"})
    for level in range(1, 7):
        heading = ET.SubElement(section, _q(STYLE, "style"), {
            _q(STYLE, "name"): f"Heading_20_{level}", _q(STYLE, "display-name"): f"Heading {level}",
            _q(STYLE, "family"): "paragraph", _q(STYLE, "parent-style-name"): "Standard",
            _q(STYLE, "default-outline-level"): str(level)})
        ET.SubElement(heading, _q(STYLE, "paragraph-properties"),
                      {_q(FO, "margin-top"): "0.42cm", _q(FO, "keep-with-next"): "always"})
        ET.SubElement(heading, _q(STYLE, "text-properties"),
                      {_q(FO, "font-size"): f"{_HEADING_SIZES[level - 1]}pt", _q(FO, "font-weight"): "bold"})

    manifest = ET.Element(_q(MANIFEST, "manifest"), {_q(MANIFEST, "version"): "1.2"})
    for full_path, media_type in (("/", MIME_TYPE), ("content.xml", "text/xml"), ("styles.xml", "text/xml")):
        ET.SubElement(manifest, _q(MANIFEST, "file-entry"),
                      {_q(MANIFEST, "full-path"): full_path, _q(MANIFEST, "media-type"): media_type})

    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
        # The mimetype must be the first entry and stored uncompressed.
        zf.writestr(zipfile.ZipInfo("mimetype"), MIME_TYPE, compress_type=zipfile.ZIP_STORED)
        zf.writestr("content.xml", _serialize(content))
        zf.writestr("styles.xml", _serialize(styles))
        zf.writestr("META-INF/manifest.xml", _serialize(manifest))


def _serialize(root: ET.Element) -> bytes:
    return b'<?xml version="1.0" encoding="UTF-8"?>\n' + ET.tostring(root, encoding="utf-8")


def _last_item(lst: ET.Element) -> ET.Element:
    items = lst.findall(_q(TEXT, "list-item"))
    return items[-1] if items else ET.SubElement(lst, _q(TEXT, "list-item"))


def _list_style(name: str, ordered: bool) -> ET.Element:
    style = ET.Element(_q(TEXT, "list-style"), {_q(STYLE, "name"): name})
    for level in range(1, 11):
        if ordered:
            item = ET.SubElement(style, _q(TEXT, "list-level-style-number"), {
                _q(TEXT, "level"): str(level), _q(STYLE, "num-suffix"): ".", _q(STYLE, "num-format"): "1"})
        else:
            item = ET.SubElement(style, _q(TEXT, "list-level-style-bullet"),
                                 {_q(TEXT, "level"): str(level), _q(TEXT, "bullet-char"): "•"})
        props = ET.SubElement(item, _q(STYLE, "list-level-properties"),
                              {_q(TEXT, "list-level-position-and-space-mode"): "label-alignment"})
        ET.SubElement(props, _q(STYLE, "list-level-label-alignment"), {
            _q(TEXT, "label-followed-by"): "listtab", _q(FO, "text-indent"): "-0.635cm",
            _q(FO, "margin-left"): f"{0.635 * (level + 1):.3f}".rstrip("0").rstrip(".") + "cm"})
    return style


def _add_text(target: ET.Element, text: str) -> None:
    """ODF collapses whitespace, so runs of spaces, tabs and line breaks become elements."""
    plain: list[str] = []

    def flush() -> None:
        if plain:
            _append_text(target, "".join(plain))
            plain.clear()

    i, n = 0, len(text)
    while i < n:
        c = text[i]
        if c == "\n":
            flush()
            ET.SubElement(target, _q(TEXT, "line-break"))
        elif c == "\t":
            flush()
            ET.SubElement(target, _q(TEXT, "tab"))
        elif c == " " and (i == 0 or i == n - 1 or text[i + 1] == " "):
            count = 1
            while i + 1 < n and text[i + 1] == " ":
                count += 1
                i += 1
            flush()
            space = ET.SubElement(target, _q(TEXT, "s"))
            if count > 1:
                space.set(_q(TEXT, "c"), str(count))
        else:
            if c >= " " and c not in "￾￿":
                plain.append(c)
        i += 1
    flush()


def _append_text(target: ET.Element, text: str) -> None:
    children = list(target)
    if children:
        children[-1].tail = (children[-1].tail or "") + text
    else:
        target.text = (target.text or "") + text
