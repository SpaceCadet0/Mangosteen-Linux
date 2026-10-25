"""Reads and writes .xlsx workbooks with the standard library: a ZIP of XML parts."""

from __future__ import annotations

import datetime as dt
import posixpath
import re
import zipfile
from xml.etree import ElementTree as ET
from xml.sax.saxutils import escape

from . import archives

_MAIN = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
_REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
_PKG_REL = "http://schemas.openxmlformats.org/package/2006/relationships"


def _q(tag: str, ns: str = _MAIN) -> str:
    return f"{{{ns}}}{tag}"


def _text_of(element: ET.Element) -> str:
    """The text of a shared or inline string, without phonetic guides."""
    parts: list[str] = []

    def walk(node: ET.Element) -> None:
        for child in node:
            if child.tag == _q("rPh"):
                continue
            if child.tag == _q("t"):
                parts.append(child.text or "")
            else:
                walk(child)

    walk(element)
    return "".join(parts)


# MARK: Reading


def read(path: str):  # noqa: ANN201 - list[tables.Sheet]; imported lazily to avoid a cycle
    from .tables import Sheet

    archives.check_unpacked_size(path, "xl/media/", "docProps/thumbnail")
    with zipfile.ZipFile(path) as zf:
        names = set(zf.namelist())
        if "xl/workbook.xml" not in names:
            raise ValueError("The workbook has no sheets.")
        workbook = ET.fromstring(zf.read("xl/workbook.xml"))
        date1904 = False
        properties = workbook.find(_q("workbookPr"))
        if properties is not None and properties.get("date1904") in ("1", "true"):
            date1904 = True

        relationships: dict[str, str] = {}
        if "xl/_rels/workbook.xml.rels" in names:
            for rel in ET.fromstring(zf.read("xl/_rels/workbook.xml.rels")):
                target = rel.get("Target", "")
                target = target.lstrip("/") if target.startswith("/") else posixpath.normpath(posixpath.join("xl", target))
                relationships[rel.get("Id", "")] = target

        shared: list[str] = []
        if "xl/sharedStrings.xml" in names:
            shared = [_text_of(si) for si in ET.fromstring(zf.read("xl/sharedStrings.xml")).iter(_q("si"))]
        date_styles = _date_styles(ET.fromstring(zf.read("xl/styles.xml"))) if "xl/styles.xml" in names else set()

        sheets: list[Sheet] = []
        container = workbook.find(_q("sheets"))
        for sheet in container if container is not None else []:
            target = relationships.get(sheet.get(_q("id", _REL), ""))
            if target is None or target not in names:
                continue
            rows = _read_sheet(ET.fromstring(zf.read(target)), shared, date_styles, date1904)
            sheets.append(Sheet(sheet.get("name") or f"Sheet{len(sheets) + 1}", rows))
        return sheets


def _read_sheet(root: ET.Element, shared: list[str], date_styles: set[int], date1904: bool) -> list[list[str]]:
    rows: list[list[str]] = []
    data = root.find(_q("sheetData"))
    for row in data if data is not None else []:
        if row.tag != _q("row"):
            continue
        index = int(row.get("r", len(rows) + 1)) - 1
        while len(rows) < index:
            rows.append([])
        values: list[str] = []
        for cell in row:
            if cell.tag != _q("c"):
                continue
            reference = cell.get("r")
            column = column_index(reference) if reference else len(values)
            while len(values) < column:
                values.append("")
            values.append(_cell_text(cell, shared, date_styles, date1904))
        while values and not values[-1]:
            values.pop()
        rows.append(values)
    while rows and not rows[-1]:
        rows.pop()
    # Every row gets the same number of columns, so CSV readers line them up.
    width = max((len(r) for r in rows), default=0)
    for r in rows:
        r.extend([""] * (width - len(r)))
    return rows


def _cell_text(cell: ET.Element, shared: list[str], date_styles: set[int], date1904: bool) -> str:
    kind = cell.get("t")
    value = cell.find(_q("v"))
    raw = value.text or "" if value is not None else ""
    if kind == "s":
        try:
            index = int(raw)
        except ValueError:
            return ""
        return shared[index] if 0 <= index < len(shared) else ""
    if kind == "inlineStr":
        inline = cell.find(_q("is"))
        return _text_of(inline) if inline is not None else ""
    if kind == "b":
        return "TRUE" if raw == "1" else "FALSE"
    style = cell.get("s")
    if kind not in ("str", "e") and style is not None and style.isdigit() and int(style) in date_styles:
        try:
            serial = float(raw)
        except ValueError:
            return raw
        if 0 < serial < 2958466:
            return excel_date(serial, date1904)
    return raw


def excel_date(serial: float, date1904: bool = False) -> str:
    """A date serial as text. In the 1900 system Excel counts the non-existent 29 February 1900 (serial 60), so
    serials before it are one day later than real dates; the 1904 system starts on 1 January 1904."""
    day = int(serial // 1)
    fraction = serial - day
    seconds = int(round(fraction * 86400))
    if seconds >= 86400:
        day += 1
        seconds -= 86400
    text: str | None = None
    if date1904:
        text = (dt.date(1904, 1, 1) + dt.timedelta(days=day)).isoformat()
    elif day == 60:
        text = "1900-02-29"
    elif day >= 1:
        text = (dt.date(1899, 12, 31) + dt.timedelta(days=day if day < 60 else day - 1)).isoformat()
    clock = f"{seconds // 3600:02}:{seconds // 60 % 60:02}:{seconds % 60:02}"
    if text is None:
        return clock
    return text if seconds == 0 else f"{text} {clock}"


def _date_styles(styles: ET.Element) -> set[int]:
    """Cell styles whose number format shows a date or time."""
    result: set[int] = set()
    custom: dict[int, str] = {}
    formats = styles.find(_q("numFmts"))
    for fmt in formats if formats is not None else []:
        try:
            custom[int(fmt.get("numFmtId", ""))] = fmt.get("formatCode", "")
        except ValueError:
            continue
    cell_formats = styles.find(_q("cellXfs"))
    for index, xf in enumerate(cell_formats if cell_formats is not None else []):
        try:
            number = int(xf.get("numFmtId", "0"))
        except ValueError:
            continue
        if 14 <= number <= 22 or 45 <= number <= 47 or (number in custom and _is_date_format(custom[number])):
            result.add(index)
    return result


def _is_date_format(code: str) -> bool:
    # Drop quoted text and [colour]/[locale] sections, then look for date or time letters.
    plain = re.sub(r'"[^"]*"|\[[^\]]*\]|\\.', "", code)
    return any(c in plain for c in "yYdDhHsS") or ("m" in plain.lower() and "0" not in plain and "#" not in plain)


def column_index(reference: str) -> int:
    index = 0
    for c in reference:
        if not c.isalpha():
            break
        index = index * 26 + (ord(c.upper()) - ord("A") + 1)
    return index - 1


def column_name(index: int) -> str:
    name = ""
    index += 1
    while index > 0:
        name = chr(ord("A") + (index - 1) % 26) + name
        index = (index - 1) // 26
    return name


# MARK: Writing

_NUMBER = re.compile(r"^-?(0|[1-9][0-9]*)(\.[0-9]+)?$")
_ILLEGAL = re.compile("[\x00-\x08\x0b\x0c\x0e-\x1f￾￿]")


def _is_plain_number(value: str) -> bool:
    """Numbers stay numbers in Excel; anything that would change when stored as one stays text."""
    return len(value) < 16 and _NUMBER.match(value) is not None


def _sheet_name(name: str) -> str:
    clean = re.sub(r"[\[\]:*?/\\]", "", name).strip("'").strip()
    return (clean or "Sheet1")[:31]


def write(rows: list[list[str]], sheet_name: str, path: str) -> None:
    body: list[str] = []
    for r, row in enumerate(rows):
        cells: list[str] = []
        for c, value in enumerate(row):
            if not value:
                continue
            ref = f"{column_name(c)}{r + 1}"
            if _is_plain_number(value):
                cells.append(f'<c r="{ref}"><v>{value}</v></c>')
            else:
                text = escape(_ILLEGAL.sub("", value))
                cells.append(f'<c r="{ref}" t="inlineStr"><is><t xml:space="preserve">{text}</t></is></c>')
        body.append(f'<row r="{r + 1}">{"".join(cells)}</row>')
    sheet = (f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n<worksheet xmlns="{_MAIN}">'
             f'<sheetData>{"".join(body)}</sheetData></worksheet>')
    workbook = (f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n<workbook xmlns="{_MAIN}" '
                f'xmlns:r="{_REL}"><sheets><sheet name="{escape(_sheet_name(sheet_name), {chr(34): "&quot;"})}" '
                f'sheetId="1" r:id="rId1"/></sheets></workbook>')
    workbook_rels = (f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n<Relationships xmlns="{_PKG_REL}">'
                     f'<Relationship Id="rId1" Type="{_REL}/worksheet" Target="worksheets/sheet1.xml"/></Relationships>')
    package_rels = (f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n<Relationships xmlns="{_PKG_REL}">'
                    f'<Relationship Id="rId1" Type="{_REL}/officeDocument" Target="xl/workbook.xml"/></Relationships>')
    content_types = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        '<Default Extension="xml" ContentType="application/xml"/>'
        '<Override PartName="/xl/workbook.xml" '
        'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
        '<Override PartName="/xl/worksheets/sheet1.xml" '
        'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/></Types>')
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("[Content_Types].xml", content_types)
        zf.writestr("_rels/.rels", package_rels)
        zf.writestr("xl/workbook.xml", workbook)
        zf.writestr("xl/_rels/workbook.xml.rels", workbook_rels)
        zf.writestr("xl/worksheets/sheet1.xml", sheet)
