"""CSV, TSV (RFC 4180 quoting) and XLSX. An XLSX source contributes its first non-empty sheet; a workbook with
several sheets becomes a folder with one table per sheet (see `converter`)."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field

from ..core import output_naming, text_file
from ..core.file_format import FileFormat
from . import xlsx


@dataclass
class Sheet:
    name: str
    rows: list[list[str]] = field(default_factory=list)


def convert(input_path: str, source: FileFormat, target: FileFormat, output: str) -> None:
    if source is FileFormat.XLSX:
        sheets = xlsx.read(input_path)
        rows = next((s.rows for s in sheets if s.rows), [])
    else:
        rows = parse(text_file.read(input_path), separator(source))
    write(rows, target, output_naming.base_name(input_path), output)


def write(rows: list[list[str]], target: FileFormat, sheet_name: str, output: str) -> None:
    if target is FileFormat.XLSX:
        xlsx.write(rows, sheet_name, output)
    else:
        # Excel opens a CSV without a byte order mark in the ANSI code page, which garbles Cyrillic.
        text_file.write(output, serialize(rows, separator(target)), bom=True)


def write_sheets(sheets: list[Sheet], target: FileFormat, folder: str) -> None:
    """One file per sheet inside `folder`."""
    os.makedirs(folder, exist_ok=True)
    for sheet in sheets:
        name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "-", sheet.name).strip()
        if not name or name.startswith("."):
            name = "_" + name
        write(sheet.rows, target, sheet.name, output_naming.unique_path(folder, name, target.extension))


def separator(fmt: FileFormat) -> str:
    return "\t" if fmt is FileFormat.TSV else ","


def parse(text: str, sep: str) -> list[list[str]]:
    rows: list[list[str]] = []
    row: list[str] = []
    field_chars: list[str] = []
    in_quotes = False
    field_started = False
    i, n = 0, len(text)
    while i < n:
        c = text[i]
        if in_quotes:
            if c == '"':
                if i + 1 < n and text[i + 1] == '"':
                    field_chars.append('"')
                    i += 1
                else:
                    in_quotes = False
            else:
                field_chars.append(c)
            i += 1
            continue
        if c == '"' and not field_chars:
            in_quotes = True
            field_started = True
        elif c == sep:
            row.append("".join(field_chars))
            field_chars = []
            field_started = True
        elif c in "\r\n":
            if c == "\r" and i + 1 < n and text[i + 1] == "\n":
                i += 1
            row.append("".join(field_chars))
            rows.append(row)
            row = []
            field_chars = []
            field_started = False
        else:
            field_chars.append(c)
            field_started = True
        i += 1
    if field_started or field_chars or row:
        row.append("".join(field_chars))
        rows.append(row)
    return rows


def serialize(rows, sep: str) -> str:  # noqa: ANN001
    lines = []
    for row in rows:
        lines.append(sep.join(
            '"' + f.replace('"', '""') + '"' if (sep in f or '"' in f or "\n" in f or "\r" in f) else f
            for f in row))
    return "".join(line + "\n" for line in lines)
