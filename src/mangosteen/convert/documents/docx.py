"""Word documents (.docx): a ZIP of XML parts, read and written with the standard library."""

from __future__ import annotations

import posixpath
import zipfile
from xml.etree import ElementTree as ET
from xml.sax.saxutils import escape, quoteattr

from .. import archives
from .rich import Block, BlockType, Run, RichDocument

_W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
_R = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
_PKG_REL = "http://schemas.openxmlformats.org/package/2006/relationships"
_MC = "http://schemas.openxmlformats.org/markup-compatibility/2006"
_CODE_FONT = "Consolas"
_HEADING_SIZES = [36, 30, 26, 24, 22, 22]  # half-points


def _w(tag: str) -> str:
    return f"{{{_W}}}{tag}"


def _val(element: ET.Element | None) -> str | None:
    return None if element is None else element.get(_w("val"))


def _is_on(element: ET.Element | None) -> bool:
    if element is None:
        return False
    return element.get(_w("val")) not in ("0", "false", "off")


# MARK: Reading


def read(path: str) -> RichDocument:
    archives.check_unpacked_size(path, "word/media/", "docProps/thumbnail")
    with zipfile.ZipFile(path) as zf:
        names = set(zf.namelist())
        main = _main_part(zf, names)
        body = ET.fromstring(zf.read(main)).find(_w("body"))
        if body is None:
            raise ValueError("The document has no body.")
        base = posixpath.dirname(main)
        styles = ET.fromstring(zf.read(posixpath.join(base, "styles.xml"))) \
            if posixpath.join(base, "styles.xml") in names else None
        numbering = ET.fromstring(zf.read(posixpath.join(base, "numbering.xml"))) \
            if posixpath.join(base, "numbering.xml") in names else None
        links: dict[str, str] = {}
        rels = posixpath.join(base, "_rels", posixpath.basename(main) + ".rels")
        if rels in names:
            for rel in ET.fromstring(zf.read(rels)):
                if rel.get("TargetMode") == "External":
                    links[rel.get("Id", "")] = rel.get("Target", "")
    heading_styles = _heading_styles(styles)
    ordered_lists = _ordered_lists(numbering)
    document = RichDocument()
    _read_paragraphs(body, document, heading_styles, ordered_lists, links)
    return document


def _main_part(zf: zipfile.ZipFile, names: set[str]) -> str:
    if "_rels/.rels" in names:
        for rel in ET.fromstring(zf.read("_rels/.rels")):
            if rel.get("Type", "").endswith("/officeDocument"):
                return rel.get("Target", "").lstrip("/")
    if "word/document.xml" in names:
        return "word/document.xml"
    raise ValueError("The document has no body.")


def _read_paragraphs(node: ET.Element, document: RichDocument, heading_styles: dict[str, int],
                     ordered_lists: set[tuple[int, int]], links: dict[str, str]) -> None:
    for child in node:
        if child.tag == f"{{{_MC}}}Fallback":
            continue  # text boxes repeat their content in a fallback for old Word versions; read it once
        if child.tag == _w("p"):
            document.blocks.append(_read_paragraph(child, heading_styles, ordered_lists, links))
        _read_paragraphs(child, document, heading_styles, ordered_lists, links)


def _read_paragraph(paragraph: ET.Element, heading_styles: dict[str, int], ordered_lists: set[tuple[int, int]],
                    links: dict[str, str]) -> Block:
    properties = paragraph.find(_w("pPr"))
    style_id = _val(properties.find(_w("pStyle"))) or "" if properties is not None else ""
    block = Block(BlockType.PARAGRAPH)
    outline = _val(properties.find(_w("outlineLvl"))) if properties is not None else None
    numbering = properties.find(_w("numPr")) if properties is not None else None
    num_id = int(_val(numbering.find(_w("numId"))) or 0) if numbering is not None else 0
    if style_id.lower() in {k.lower() for k in heading_styles} and _style_level(style_id, heading_styles):
        block = Block(BlockType.HEADING, _style_level(style_id, heading_styles))
    elif outline is not None and outline.isdigit() and int(outline) < 6:
        block = Block(BlockType.HEADING, int(outline) + 1)
    elif numbering is not None and num_id > 0:
        level = int(_val(numbering.find(_w("ilvl"))) or 0)
        block = Block(BlockType.LIST_ITEM, level, (num_id, level) in ordered_lists)
    elif "code" in style_id.lower() or "htmlpreformatted" in style_id.lower():
        block = Block(BlockType.CODE)
    _read_runs(paragraph, block, None, links)
    return block


def _style_level(style_id: str, heading_styles: dict[str, int]) -> int:
    for key, level in heading_styles.items():
        if key.lower() == style_id.lower():
            return level
    return 0


def _read_runs(node: ET.Element, block: Block, link: str | None, links: dict[str, str]) -> None:
    for child in node:
        if child.tag == _w("hyperlink"):
            target = links.get(child.get(f"{{{_R}}}id", ""))
            _read_runs(child, block, target or link, links)
        elif child.tag == _w("r"):
            _read_run(child, block, link)
        elif child.tag in (_w("pPr"), _w("rPr")):
            continue
        else:
            _read_runs(child, block, link, links)  # ins, smartTag, sdt, fldSimple…


def _read_run(run: ET.Element, block: Block, link: str | None) -> None:
    properties = run.find(_w("rPr"))
    bold = italic = underline = False
    font = ""
    if properties is not None:
        bold = _is_on(properties.find(_w("b")))
        italic = _is_on(properties.find(_w("i")))
        underline_element = properties.find(_w("u"))
        underline = underline_element is not None and _val(underline_element) != "none"
        fonts = properties.find(_w("rFonts"))
        font = fonts.get(_w("ascii"), "") if fonts is not None else ""
    in_code = block.type is BlockType.CODE
    code = in_code or any(f in font.lower() for f in ("consolas", "courier", "mono"))
    for child in run:
        text = ""
        if child.tag == _w("t"):
            text = child.text or ""
        elif child.tag == _w("tab"):
            text = "\t"
        elif child.tag in (_w("br"), _w("cr")):
            text = "\n"
        elif child.tag == _w("noBreakHyphen"):
            text = "-"
        block.add(Run(text, bold, italic, underline and link is None, link, code and not in_code))


def _heading_styles(styles: ET.Element | None) -> dict[str, int]:
    """Style ids of headings: "Heading 1".."Heading 6" (any language, by name or outline level) and "Title"."""
    result: dict[str, int] = {}
    if styles is not None:
        for style in styles.findall(_w("style")):
            style_id = style.get(_w("styleId"))
            if not style_id:
                continue
            name = (_val(style.find(_w("name"))) or "").lower()
            ppr = style.find(_w("pPr"))
            outline = _val(ppr.find(_w("outlineLvl"))) if ppr is not None else None
            if outline is not None and outline.isdigit() and int(outline) < 6:
                result[style_id] = int(outline) + 1
            elif name.startswith("heading ") and name[8:].isdigit() and 1 <= int(name[8:]) <= 6:
                result[style_id] = int(name[8:])
            elif name == "title":
                result[style_id] = 1
    for level in range(1, 7):
        result.setdefault(f"Heading{level}", level)
    result.setdefault("Title", 1)
    return result


def _ordered_lists(numbering: ET.Element | None) -> set[tuple[int, int]]:
    """(numbering id, level) pairs that are numbered rather than bulleted."""
    result: set[tuple[int, int]] = set()
    if numbering is None:
        return result
    abstracts = {a.get(_w("abstractNumId")): a for a in numbering.findall(_w("abstractNum"))}
    for instance in numbering.findall(_w("num")):
        try:
            num_id = int(instance.get(_w("numId"), ""))
        except ValueError:
            continue
        definition = abstracts.get(_val(instance.find(_w("abstractNumId"))))
        if definition is None:
            continue
        for level in definition.findall(_w("lvl")):
            fmt = _val(level.find(_w("numFmt")))
            index = level.get(_w("ilvl"))
            if fmt and fmt not in ("bullet", "none") and index and index.isdigit():
                result.add((num_id, int(index)))
    return result


# MARK: Writing


def write(document: RichDocument, path: str) -> None:
    links: list[str] = []
    ordered_instances = 0
    instances: list[int] = []
    body: list[str] = []
    previous: Block | None = None
    ordered_instance = 0
    for block in document.blocks:
        props = ""
        if block.type is BlockType.HEADING:
            props = f'<w:pStyle w:val="Heading{max(1, min(block.level, 6))}"/>'
        elif block.type is BlockType.CODE:
            props = '<w:pStyle w:val="Code"/>'
        elif block.type is BlockType.LIST_ITEM:
            # Each ordered list starts at 1: it gets its own numbering instance.
            if block.ordered and (previous is None or previous.type is not BlockType.LIST_ITEM or ordered_instance == 0):
                ordered_instances += 1
                ordered_instance = 1 + ordered_instances
                instances.append(ordered_instance)
            props = ('<w:pStyle w:val="ListParagraph"/><w:numPr>'
                     f'<w:ilvl w:val="{min(block.level, 8)}"/>'
                     f'<w:numId w:val="{ordered_instance if block.ordered else 1}"/></w:numPr>')
        runs = []
        for run in block.runs:
            element = _build_run(run, block.type is BlockType.CODE)
            if run.link:
                links.append(run.link)
                element = f'<w:hyperlink r:id="rId{len(links) + 10}">{element}</w:hyperlink>'
            runs.append(element)
        body.append(f"<w:p>{f'<w:pPr>{props}</w:pPr>' if props else ''}{''.join(runs)}</w:p>")
        previous = block
    section = ('<w:sectPr><w:pgSz w:w="11906" w:h="16838"/><w:pgMar w:top="1134" w:right="1134" w:bottom="1134" '
               'w:left="1134" w:header="708" w:footer="708" w:gutter="0"/></w:sectPr>')
    xml = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
           f'<w:document xmlns:w="{_W}" xmlns:r="{_R}"><w:body>{"".join(body)}{section}</w:body></w:document>')

    rels = [f'<Relationship Id="rId1" Type="{_R}/styles" Target="styles.xml"/>',
            f'<Relationship Id="rId2" Type="{_R}/numbering" Target="numbering.xml"/>']
    for index, link in enumerate(links, start=1):
        rels.append(f'<Relationship Id="rId{index + 10}" Type="{_R}/hyperlink" Target={quoteattr(link)} '
                    'TargetMode="External"/>')
    parts = {
        "[Content_Types].xml": (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
            '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
            '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
            '<Default Extension="xml" ContentType="application/xml"/>'
            '<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.'
            'wordprocessingml.document.main+xml"/>'
            '<Override PartName="/word/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.'
            'wordprocessingml.styles+xml"/>'
            '<Override PartName="/word/numbering.xml" ContentType="application/vnd.openxmlformats-officedocument.'
            'wordprocessingml.numbering+xml"/></Types>'),
        "_rels/.rels": (
            f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n<Relationships xmlns="{_PKG_REL}">'
            f'<Relationship Id="rId1" Type="{_R}/officeDocument" Target="word/document.xml"/></Relationships>'),
        "word/document.xml": xml,
        "word/_rels/document.xml.rels": (
            f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n<Relationships xmlns="{_PKG_REL}">'
            f'{"".join(rels)}</Relationships>'),
        "word/styles.xml": _styles(),
        "word/numbering.xml": _numbering(instances),
    }
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, content in parts.items():
            zf.writestr(name, content)


def _build_run(run: Run, in_code: bool) -> str:
    props = ""
    if run.link:
        props += '<w:rStyle w:val="Hyperlink"/>'
    if run.code and not in_code:
        props += f'<w:rFonts w:ascii="{_CODE_FONT}" w:hAnsi="{_CODE_FONT}" w:cs="{_CODE_FONT}"/>'
    if run.bold:
        props += "<w:b/>"
    if run.italic:
        props += "<w:i/>"
    if run.underline:
        props += '<w:u w:val="single"/>'
    out = []
    for p, part in enumerate(run.text.split("\n")):
        if p > 0:
            out.append("<w:br/>")
        for t, piece in enumerate(part.split("\t")):
            if t > 0:
                out.append("<w:tab/>")
            if piece:
                out.append(f'<w:t xml:space="preserve">{escape(_clean(piece))}</w:t>')
    return f"<w:r>{f'<w:rPr>{props}</w:rPr>' if props else ''}{''.join(out)}</w:r>"


def _clean(text: str) -> str:
    """Control characters are not allowed in XML."""
    return "".join(c for c in text if c in "\t\n\r" or ord(c) >= 0x20 and c not in "￾￿")


def _styles() -> str:
    parts = [
        f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n<w:styles xmlns:w="{_W}">',
        '<w:docDefaults><w:rPrDefault><w:rPr><w:rFonts w:ascii="Calibri" w:hAnsi="Calibri" w:cs="Calibri" '
        'w:eastAsia="Calibri"/><w:sz w:val="22"/></w:rPr></w:rPrDefault><w:pPrDefault><w:pPr>'
        '<w:spacing w:after="120" w:line="276" w:lineRule="auto"/></w:pPr></w:pPrDefault></w:docDefaults>',
        '<w:style w:type="paragraph" w:default="1" w:styleId="Normal"><w:name w:val="Normal"/><w:qFormat/></w:style>',
    ]
    for level in range(1, 7):
        parts.append(
            f'<w:style w:type="paragraph" w:styleId="Heading{level}"><w:name w:val="heading {level}"/>'
            '<w:basedOn w:val="Normal"/><w:next w:val="Normal"/><w:qFormat/>'
            f'<w:pPr><w:keepNext/><w:spacing w:before="240" w:after="120"/><w:outlineLvl w:val="{level - 1}"/></w:pPr>'
            f'<w:rPr><w:b/><w:sz w:val="{_HEADING_SIZES[level - 1]}"/></w:rPr></w:style>')
    parts.append('<w:style w:type="paragraph" w:styleId="ListParagraph"><w:name w:val="List Paragraph"/>'
                 '<w:basedOn w:val="Normal"/><w:pPr><w:spacing w:after="60"/></w:pPr></w:style>')
    parts.append(
        '<w:style w:type="paragraph" w:styleId="Code"><w:name w:val="Code"/><w:basedOn w:val="Normal"/>'
        '<w:pPr><w:shd w:val="clear" w:color="auto" w:fill="F4F4F4"/><w:spacing w:after="0" w:line="240" '
        'w:lineRule="auto"/></w:pPr>'
        f'<w:rPr><w:rFonts w:ascii="{_CODE_FONT}" w:hAnsi="{_CODE_FONT}" w:cs="{_CODE_FONT}"/><w:sz w:val="20"/></w:rPr>'
        '</w:style>')
    parts.append('<w:style w:type="character" w:styleId="Hyperlink"><w:name w:val="Hyperlink"/>'
                 '<w:rPr><w:color w:val="0563C1"/><w:u w:val="single"/></w:rPr></w:style></w:styles>')
    return "".join(parts)


def _numbering(ordered_instances: list[int]) -> str:
    """Abstract 0: bullets, numbering instance 1. Abstract 1: decimal numbers, instances added per list."""
    bullets = numbers = ""
    glyphs = ["•", "◦", "▪"]
    for level in range(9):
        indent = f'<w:pPr><w:ind w:left="{720 * (level + 1)}" w:hanging="360"/></w:pPr>'
        bullets += (f'<w:lvl w:ilvl="{level}"><w:start w:val="1"/><w:numFmt w:val="bullet"/>'
                    f'<w:lvlText w:val="{glyphs[level % 3]}"/><w:lvlJc w:val="left"/>{indent}</w:lvl>')
        numbers += (f'<w:lvl w:ilvl="{level}"><w:start w:val="1"/><w:numFmt w:val="decimal"/>'
                    f'<w:lvlText w:val="%{level + 1}."/><w:lvlJc w:val="left"/>{indent}</w:lvl>')
    instances = '<w:num w:numId="1"><w:abstractNumId w:val="0"/></w:num>'
    for instance in ordered_instances:
        overrides = "".join(
            f'<w:lvlOverride w:ilvl="{level}"><w:startOverride w:val="1"/></w:lvlOverride>' for level in range(9))
        instances += f'<w:num w:numId="{instance}"><w:abstractNumId w:val="1"/>{overrides}</w:num>'
    return (f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n<w:numbering xmlns:w="{_W}">'
            f'<w:abstractNum w:abstractNumId="0">{bullets}</w:abstractNum>'
            f'<w:abstractNum w:abstractNumId="1">{numbers}</w:abstractNum>{instances}</w:numbering>')
