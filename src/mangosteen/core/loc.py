"""Every user-visible string goes through `L`. The keys are the English texts; the Russian and Spanish tables
are JSON files in `mangosteen/strings` (a key may carry a context after "|", as in "Crop|tab", when one English
word needs two translations; the English text is the part before it)."""

from __future__ import annotations

import json
import locale
import os
from pathlib import Path

LANGUAGES = [("en", "English"), ("es", "Español"), ("ru", "Русский")]

_STRINGS = Path(__file__).resolve().parent.parent / "strings"

_table: dict[str, str] | None = None
language = "en"


def system_language() -> str:
    """Russian or Spanish when the desktop is set to one of them, otherwise English."""
    candidates: list[str] = []
    for variable in ("LANGUAGE", "LC_ALL", "LC_MESSAGES", "LANG"):
        value = os.environ.get(variable)
        if value:
            candidates += value.split(":")
    try:
        default = locale.getlocale()[0]
        if default:
            candidates.append(default)
    except (ValueError, TypeError):
        pass
    for candidate in candidates:
        code = candidate.lower().replace("-", "_").split("_")[0].split(".")[0]
        if code in ("ru", "uk", "be", "kk"):
            return "ru"
        if code == "es":
            return "es"
        if code in ("en", "c", "posix"):
            return "en"
    return "en"


def load(code: str) -> dict[str, str]:
    try:
        with open(_STRINGS / f"{code}.json", encoding="utf-8") as stream:
            return json.load(stream)
    except (OSError, ValueError):
        return {}


def set_language(code: str) -> None:
    """Switches to "en", "es" or "ru"; anything else means English."""
    global language, _table
    language = code if code in ("ru", "es") else "en"
    _table = None if language == "en" else load(language)


def use(table: dict[str, str] | None) -> None:
    """Replaces the current translation table; None restores English. For tests."""
    global _table
    _table = table


def L(english: str) -> str:  # noqa: N802 - the name is the convention of all Mangosteen apps
    if _table is not None:
        text = _table.get(english)
        if text:
            return text
    bar = english.find("|")
    return english[:bar] if bar > 0 else english


def fmt(english: str, *args: object) -> str:
    """Translates `english` and fills its {0}, {1}… placeholders."""
    return L(english).format(*args)


_NOUNS = {
    "file": (("file", "files"), ("файл", "файла", "файлов"), ("archivo", "archivos")),
    "item": (("item", "items"), ("объект", "объекта", "объектов"), ("elemento", "elementos")),
    "path": (("path", "paths"), ("путь", "пути", "путей"), ("ruta", "rutas")),
    "part": (("part", "parts"), ("часть", "части", "частей"), ("parte", "partes")),
    "page": (("page", "pages"), ("страница", "страницы", "страниц"), ("página", "páginas")),
    "frame": (("frame", "frames"), ("кадр", "кадра", "кадров"), ("fotograma", "fotogramas")),
    "document": (("document", "documents"), ("документ", "документа", "документов"), ("documento", "documentos")),
    "bleep": (("bleep", "bleeps"), ("писк", "писка", "писков"), ("pitido", "pitidos")),
}


def count(number: int, noun: str) -> str:
    """"1 file", "5 files"; "1 файл", "2 файла", "5 файлов"; "1 archivo", "5 archivos"."""
    en, ru, es = _NOUNS[noun]
    if language == "ru":
        mod10, mod100 = number % 10, number % 100
        if mod10 == 1 and mod100 != 11:
            word = ru[0]
        elif 2 <= mod10 <= 4 and not 12 <= mod100 <= 14:
            word = ru[1]
        else:
            word = ru[2]
    else:
        word = (es if language == "es" else en)[0 if number == 1 else 1]
    return f"{number} {word}"
