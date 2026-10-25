"""Reads text files whatever their encoding, so Russian files saved by old Windows apps open too."""

from __future__ import annotations

import codecs


def read(path: str) -> str:
    with open(path, "rb") as stream:
        return decode(stream.read())


def decode(data: bytes) -> str:
    """UTF-8 (with or without BOM), UTF-16 with BOM, then Windows-1251 as the fallback."""
    if data.startswith(codecs.BOM_UTF8):
        return data[3:].decode("utf-8", "replace")
    if data.startswith(codecs.BOM_UTF16_LE):
        return data[2:].decode("utf-16-le", "replace")
    if data.startswith(codecs.BOM_UTF16_BE):
        return data[2:].decode("utf-16-be", "replace")
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        return data.decode("cp1251", "replace")


def write(path: str, text: str, bom: bool = False) -> None:
    """Results are written as UTF-8 without a byte order mark (CSV for Excel is the exception)."""
    with open(path, "w", encoding="utf-8-sig" if bom else "utf-8", newline="") as stream:
        stream.write(text)
