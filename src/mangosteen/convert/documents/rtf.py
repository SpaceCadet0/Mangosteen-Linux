"""Rich Text Format. The reader understands what text editors put in RTF: paragraphs, headings (outline levels),
bold, italic, underline, links, list markers, tables as tab-separated lines, Unicode and legacy code pages
(Cyrillic RTF from old Windows apps included). Pictures, headers and footnotes are skipped."""

from __future__ import annotations

import re
from copy import copy
from dataclasses import dataclass, replace
from enum import Enum

from .rich import Block, BlockType, ListNumbering, Run, RichDocument

_HEADING_SIZES = [36, 30, 26, 24, 22, 22]  # half-points

# MARK: Writing


def write(document: RichDocument) -> str:
    out = [r"{\rtf1\ansi\ansicpg1252\deff0\uc1"
           r"{\fonttbl{\f0\fswiss\fcharset0 Calibri;}{\f1\fmodern\fcharset0 Consolas;}}"
           r"{\colortbl;\red5\green99\blue193;}"
           r"\viewkind4\paperw11906\paperh16838\margl1134\margr1134\margt1134\margb1134" "\n"]
    numbers = ListNumbering()
    for block in document.blocks:
        out.append(r"\pard\plain\sa120\f0\fs22 ")
        if block.type is BlockType.HEADING:
            numbers.reset()
            level = max(1, min(block.level, 6))
            out.append(rf"\outlinelevel{level - 1}\sb240\keepn\b\fs{_HEADING_SIZES[level - 1]} ")
        elif block.type is BlockType.LIST_ITEM:
            indent = 720 * (block.level + 1)
            out.append(rf"\fi-360\li{indent}\sa60 ")
            out.append(rf"{numbers.next(block)}.\tab " if block.ordered else r"\u8226?\tab ")
        elif block.type is BlockType.CODE:
            numbers.reset()
            out.append(r"\sa0\f1\fs20 ")
        else:
            numbers.reset()
        for run in block.runs:
            text = _escape(run.text)
            style = ""
            if run.bold:
                style += r"\b"
            if run.italic:
                style += r"\i"
            if run.underline:
                style += r"\ul"
            if run.code and block.type is not BlockType.CODE:
                style += r"\f1"
            styled = "{" + style + " " + text + "}" if style else text
            if run.link:
                link = _escape(run.link.replace('"', "%22"))
                styled = (r'{\field{\*\fldinst{HYPERLINK "' + link + r'"}}{\fldrslt{\ul\cf1 ' + styled + "}}}")
            out.append(styled)
        out.append("\\par\n")
    out.append("}")
    return "".join(out)


def _escape(text: str) -> str:
    out = []
    for c in text:
        if c in "\\{}":
            out.append("\\" + c)
        elif c == "\n":
            out.append(r"\line ")
        elif c == "\t":
            out.append(r"\tab ")
        elif ord(c) < 0x80:
            if c >= " ":
                out.append(c)
        else:
            code = ord(c)
            if code > 0xFFFF:  # a surrogate pair, as RTF counts UTF-16 units
                code -= 0x10000
                for unit in (0xD800 + (code >> 10), 0xDC00 + (code & 0x3FF)):
                    out.append(rf"\u{unit - 65536 if unit > 32767 else unit}?")
            else:
                out.append(rf"\u{code - 65536 if code > 32767 else code}?")
    return "".join(out)


# MARK: Reading


class _Dest(Enum):
    TEXT = 0
    SKIP = 1
    FONT_TABLE = 2
    FONT_ENTRY = 3
    FIELD_INSTRUCTION = 4
    FIELD_RESULT = 5
    LIST_TEXT = 6


@dataclass
class _State:
    bold: bool = False
    italic: bool = False
    underline: bool = False
    font: int = -1
    unicode_skip: int = 1
    destination: _Dest = _Dest.TEXT
    link: str | None = None
    is_field: bool = False


@dataclass(frozen=True)
class _Font:
    code_page: int
    monospace: bool


_SKIPPED_DESTINATIONS = {
    "colortbl", "stylesheet", "info", "pict", "object", "header", "headerl", "headerr", "headerf", "footer",
    "footerl", "footerr", "footerf", "footnote", "annotation", "listtable", "listoverridetable", "rsidtbl",
    "generator", "themedata", "colorschememapping", "datastore", "latentstyles", "xmlnstbl", "pgdsctbl", "revtbl",
    "filetbl", "nonshppict", "shppict", "bkmkstart", "bkmkend", "atnid", "atnauthor",
}
_SYMBOLS = {"emdash": "—", "endash": "–", "bullet": "•", "lquote": "‘", "rquote": "’", "ldblquote": "“",
            "rdblquote": "”"}
_CHARSETS = {0: 1252, 204: 1251, 238: 1250, 161: 1253, 162: 1254, 177: 1255, 178: 1256, 186: 1257, 163: 1258,
             222: 874, 128: 932, 134: 936, 129: 949, 136: 950}
_LIST_MARKER = re.compile(r"^\s*(•|·|◦|▪|-|\d{1,3}[.)])\t")
_HYPERLINK = re.compile(r'HYPERLINK\s+"([^"]+)"')


def parse(data: bytes | str) -> RichDocument:
    rtf = data.decode("latin-1") if isinstance(data, bytes) else data
    if not rtf.startswith("{\\rtf"):
        raise ValueError("This is not an RTF document.")
    return _Parser(rtf).run()


class _Parser:
    def __init__(self, rtf: str) -> None:
        self.rtf = rtf
        self.document = RichDocument()
        self.fonts: dict[int, _Font] = {}
        self.default_code_page = 1252
        self.default_font = 0
        self.stack: list[_State] = []
        self.state = _State()
        self.bytes = bytearray()
        self.field_instruction: list[str] = []
        self.list_text: list[str] = []
        self.font_name: list[str] = []
        self.font_number = 0
        self.font_charset = -1
        self.outline = -1
        self.left_indent = 0
        self.list_level = -1
        self.block = Block(BlockType.PARAGRAPH)
        self.mono_only = True
        self.pending_skip = 0

    # Helpers

    def _code_page(self, font: int) -> int:
        info = self.fonts.get(self.default_font if font < 0 else font)
        return info.code_page if info is not None and info.code_page > 0 else self.default_code_page

    def _emit(self, text: str) -> None:
        if not text:
            return
        d = self.state.destination
        if d in (_Dest.TEXT, _Dest.FIELD_RESULT):
            font = self.fonts.get(self.default_font if self.state.font < 0 else self.state.font)
            mono = font is not None and font.monospace
            self.mono_only = self.mono_only and (mono or not text.strip())
            self.block.add(Run(text, self.state.bold, self.state.italic,
                               self.state.underline and self.state.link is None, self.state.link, mono))
        elif d is _Dest.FIELD_INSTRUCTION:
            self.field_instruction.append(text)
        elif d is _Dest.LIST_TEXT:
            self.list_text.append(text)
        elif d is _Dest.FONT_ENTRY:
            self.font_name.append(text)

    def _flush_bytes(self) -> None:
        if not self.bytes:
            return
        try:
            text = bytes(self.bytes).decode(f"cp{self._code_page(self.state.font)}", "replace")
        except LookupError:
            text = bytes(self.bytes).decode("latin-1")
        self._emit(text)
        self.bytes.clear()

    def _end_paragraph(self) -> None:
        self._flush_bytes()
        block = self.block
        text = block.text
        marker_match = _LIST_MARKER.match(text)
        if 0 <= self.outline < 6:
            block.type = BlockType.HEADING
            block.level = self.outline + 1
            # Headings are bold by definition; the explicit \b that editors add would only repeat it.
            block.runs = [replace(r, bold=False) for r in block.runs]
        elif self.list_level >= 0 or self.list_text or marker_match:
            marker = "".join(self.list_text).strip() if self.list_text else (marker_match.group(0).strip() if marker_match else "")
            block.type = BlockType.LIST_ITEM
            block.ordered = bool(marker) and marker[0].isdigit()
            block.level = self.list_level if self.list_level >= 0 else max(0, self.left_indent // 720 - 1)
            if not self.list_text and marker_match:
                _strip_leading(block, len(marker_match.group(0)))
        elif self.mono_only and text.strip():
            block.type = BlockType.CODE
            block.runs = [replace(r, code=False) for r in block.runs]
        self.document.blocks.append(block)
        self.block = Block(BlockType.PARAGRAPH)
        self.list_text.clear()
        self.mono_only = True

    # The scanner

    def run(self) -> RichDocument:
        rtf = self.rtf
        n = len(rtf)
        i = 0
        while i < n:
            c = rtf[i]
            if c == "{":
                self._flush_bytes()
                self.stack.append(self.state)
                self.state = copy(self.state)
                self.state.is_field = False
                if self.state.destination is _Dest.FONT_TABLE:
                    self.state.destination = _Dest.FONT_ENTRY
                    self.font_name.clear()
                    self.font_number = 0
                    self.font_charset = -1
                i += 1
                continue
            if c == "}":
                self._flush_bytes()
                if (self.state.destination is _Dest.FONT_ENTRY and self.stack
                        and self.stack[-1].destination is _Dest.FONT_TABLE):
                    name = "".join(self.font_name).rstrip("; ")
                    mono = any(k in name.lower() for k in ("courier", "consolas", "mono", "menlo"))
                    self.fonts[self.font_number] = _Font(_CHARSETS.get(self.font_charset, 0), mono)
                if (self.state.destination is _Dest.FIELD_INSTRUCTION and self.stack
                        and self.stack[-1].destination is not _Dest.FIELD_INSTRUCTION):
                    # The instruction belongs to the enclosing \field group; its result group takes the link.
                    url = _HYPERLINK.search("".join(self.field_instruction))
                    self.stack[-1].link = url.group(1) if url else None
                    self.field_instruction.clear()
                if self.stack:
                    self.state = self.stack.pop()
                i += 1
                if not self.stack:
                    break
                continue
            if c in "\r\n":
                i += 1
                continue
            if c != "\\":
                if self.pending_skip > 0:
                    self.pending_skip -= 1
                    i += 1
                    continue
                self._flush_bytes()
                if self.state.destination in (_Dest.FONT_ENTRY, _Dest.TEXT, _Dest.FIELD_RESULT,
                                              _Dest.FIELD_INSTRUCTION, _Dest.LIST_TEXT):
                    start = i
                    while i < n and rtf[i] not in "\\{}\r\n":
                        i += 1
                    self._emit(rtf[start:i])
                    continue
                i += 1
                continue

            # Control symbol or word
            if i + 1 >= n:
                break
            nxt = rtf[i + 1]
            if nxt == "'":
                try:
                    value = int(rtf[i + 2:i + 4], 16)
                except ValueError:
                    value = None
                if value is not None:
                    if self.pending_skip > 0:
                        self.pending_skip -= 1
                    elif self.state.destination not in (_Dest.SKIP, _Dest.FONT_TABLE):
                        self.bytes.append(value)
                i += 4
                continue
            if not (nxt.isascii() and nxt.isalpha()):
                self._flush_bytes()
                i += 2
                if self.pending_skip > 0 and nxt in "\\{}":
                    self.pending_skip -= 1
                    continue
                if nxt in "\\{}":
                    self._emit(nxt)
                elif nxt == "~":
                    self._emit(" ")
                elif nxt == "_":
                    self._emit("-")
                elif nxt == "*":
                    self.state.destination = _Dest.SKIP
                    # \*\fldinst is the one starred destination worth reading.
                    if rtf.startswith("\\fldinst", i):
                        self.state.destination = _Dest.FIELD_INSTRUCTION
                elif nxt in "\r\n":
                    if self.state.destination is _Dest.TEXT:
                        self._end_paragraph()
                continue
            j = i + 1
            while j < n and rtf[j].isascii() and rtf[j].isalpha():
                j += 1
            word = rtf[i + 1:j]
            parameter: int | None = None
            number_start = j
            if j < n and (rtf[j] == "-" or rtf[j].isdigit()):
                j += 1
                while j < n and rtf[j].isdigit():
                    j += 1
                try:
                    parameter = int(rtf[number_start:j])
                except ValueError:
                    parameter = None
            if j < n and rtf[j] == " ":
                j += 1
            i = j
            if word != "u":
                self._flush_bytes()
            if self.state.destination is _Dest.SKIP:
                if word == "bin" and parameter is not None and parameter > 0:
                    i += parameter
                continue
            if self.pending_skip > 0 and word != "u":
                self.pending_skip = 0
            self._control(word, parameter)
        self._flush_bytes()
        if self.block.runs:
            self._end_paragraph()
        for b in self.document.blocks:
            # Characters beyond the BMP arrive as two \u escapes (a surrogate pair); join them.
            b.runs = [replace(r, text=_join_surrogates(r.text)) for r in b.runs]
            b.trim()
        while self.document.blocks and not self.document.blocks[-1].runs:
            self.document.blocks.pop()
        return self.document

    def _control(self, word: str, parameter: int | None) -> None:
        state = self.state
        if word == "ansicpg" and parameter is not None:
            self.default_code_page = parameter
        elif word == "deff" and parameter is not None:
            self.default_font = parameter
        elif word == "fonttbl":
            state.destination = _Dest.FONT_TABLE
        elif word == "f" and parameter is not None:
            if state.destination is _Dest.FONT_ENTRY:
                self.font_number = parameter
            else:
                state.font = parameter
        elif word == "fcharset" and parameter is not None:
            self.font_charset = parameter
        elif word in _SKIPPED_DESTINATIONS:
            state.destination = _Dest.SKIP
        elif word == "fldinst":
            state.destination = _Dest.FIELD_INSTRUCTION
        elif word == "field":
            state.is_field = True
        elif word == "fldrslt":
            state.destination = _Dest.FIELD_RESULT
        elif word in ("listtext", "pntext"):
            state.destination = _Dest.LIST_TEXT
        elif word == "par":
            if state.destination in (_Dest.TEXT, _Dest.FIELD_RESULT):
                self._end_paragraph()
        elif word == "row":
            if state.destination is _Dest.TEXT:
                self._end_paragraph()
        elif word == "line":
            self._emit("\n")
        elif word in ("tab", "cell"):
            self._emit("\t")
        elif word in _SYMBOLS:
            self._emit(_SYMBOLS[word])
        elif word == "u" and parameter is not None:
            self._flush_bytes()
            self._emit(chr(parameter + 65536 if parameter < 0 else parameter))
            self.pending_skip = state.unicode_skip
        elif word == "uc" and parameter is not None:
            state.unicode_skip = parameter
        elif word == "b":
            state.bold = parameter != 0
        elif word == "i":
            state.italic = parameter != 0
        elif word == "ul":
            state.underline = parameter != 0
        elif word == "ulnone":
            state.underline = False
        elif word == "plain":
            state.bold = state.italic = state.underline = False
            state.font = -1
        elif word == "pard":
            self.outline = -1
            self.left_indent = 0
            self.list_level = -1
        elif word == "outlinelevel" and parameter is not None:
            self.outline = parameter
        elif word == "li" and parameter is not None:
            self.left_indent = parameter
        elif word == "ilvl" and parameter is not None:
            self.list_level = parameter
        elif word == "ls":
            self.list_level = max(self.list_level, 0)


def _join_surrogates(text: str) -> str:
    try:
        text.encode("utf-8")
        return text
    except UnicodeEncodeError:
        return text.encode("utf-16-le", "surrogatepass").decode("utf-16-le", "replace")


def _strip_leading(block: Block, count: int) -> None:
    while count > 0 and block.runs:
        first = block.runs[0]
        if len(first.text) <= count:
            count -= len(first.text)
            block.runs.pop(0)
        else:
            block.runs[0] = replace(first, text=first.text[count:])
            count = 0
