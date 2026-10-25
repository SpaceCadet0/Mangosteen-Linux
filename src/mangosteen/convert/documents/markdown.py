"""A practical subset of Markdown: headings, paragraphs, lists, code, bold, italic, code spans and links."""

from __future__ import annotations

import re

from .rich import Block, BlockType, ListNumbering, Run, RichDocument

_HEADING = re.compile(r"^(#{1,6})\s+(.*)$")
_RULE = re.compile(r"^(-{3,}|\*{3,}|_{3,})$")
_LIST = re.compile(r"^(\s*)([-*+]|\d{1,9}[.)])\s+(.*)$")
_LINK = re.compile(r'\[([^\]]*)\]\(([^)\s]*)(?:\s+"[^"]*")?\)')
_ESCAPE = re.compile(r"([\\`*_\[\]])")
_ESCAPABLE = "\\`*_[]()#+-.!<>"


def parse(markdown: str) -> RichDocument:
    document = RichDocument()
    lines = markdown.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    paragraph: list[str] = []

    def flush() -> None:
        if not paragraph:
            return
        block = Block(BlockType.PARAGRAPH)
        pieces: list[str] = []
        for i, line in enumerate(paragraph):
            hard_break = line.endswith("  ") or line.endswith("\\")
            pieces.append(line.rstrip(" \\"))
            if i < len(paragraph) - 1:
                pieces.append("\n" if hard_break else " ")
        add_inline(block, "".join(pieces).strip())
        document.blocks.append(block)
        paragraph.clear()

    i = 0
    while i < len(lines):
        line = lines[i]
        trimmed = line.strip()
        if trimmed.startswith("```") or trimmed.startswith("~~~"):
            flush()
            fence = trimmed[:3]
            code: list[str] = []
            i += 1
            while i < len(lines) and not lines[i].strip().startswith(fence):
                code.append(lines[i])
                i += 1
            block = Block(BlockType.CODE)
            block.add(Run("\n".join(code), code=True))
            document.blocks.append(block)
            i += 1
            continue
        if not trimmed:
            flush()
        elif (heading := _HEADING.match(line)) is not None:
            flush()
            block = Block(BlockType.HEADING, len(heading.group(1)))
            add_inline(block, heading.group(2).rstrip("# "))
            document.blocks.append(block)
        elif _RULE.match(trimmed):
            flush()
        elif (item := _LIST.match(line)) is not None:
            flush()
            indent = len(item.group(1).replace("\t", "    "))
            block = Block(BlockType.LIST_ITEM, min(indent // 2, 8), item.group(2)[0].isdigit())
            add_inline(block, item.group(3).strip())
            document.blocks.append(block)
        else:
            paragraph.append(trimmed.lstrip("> ") if trimmed.startswith(">") else line.lstrip())
        i += 1
    flush()
    return document


def add_inline(block: Block, text: str, bold: bool = False, italic: bool = False, link: str | None = None) -> None:
    """Parses inline markup into runs and appends them to `block`."""
    plain: list[str] = []

    def emit() -> None:
        block.add(Run("".join(plain), bold, italic, link=link))
        plain.clear()

    i = 0
    n = len(text)
    while i < n:
        c = text[i]
        if c == "\\" and i + 1 < n and text[i + 1] in _ESCAPABLE:
            i += 1
            plain.append(text[i])
            i += 1
            continue
        if c == "`":
            end = text.find("`", i + 1)
            if end > 0:
                emit()
                block.add(Run(text[i + 1:end], bold, italic, link=link, code=True))
                i = end + 1
                continue
        if c in "*_" and i + 1 < n and text[i + 1] == c:
            strong_end = text.find(c * 2, i + 2)
            if strong_end > 0:
                emit()
                add_inline(block, text[i + 2:strong_end], True, italic, link)
                i = strong_end + 2
                continue
        if (c in "*_" and i + 1 < n and not text[i + 1].isspace()
                and (c == "*" or i == 0 or not text[i - 1].isalnum())):
            em_end = _closing_emphasis(text, i + 1, c)
            if em_end > 0:
                emit()
                add_inline(block, text[i + 1:em_end], bold, True, link)
                i = em_end + 1
                continue
        if c == "[" and link is None:
            match = _LINK.match(text, i)
            if match is not None:
                emit()
                add_inline(block, match.group(1), bold, italic, match.group(2))
                i += match.end() - i
                continue
        plain.append(c)
        i += 1
    emit()


def _closing_emphasis(text: str, start: int, marker: str) -> int:
    for i in range(start, len(text)):
        if (text[i] == marker and not text[i - 1].isspace()
                and (i + 1 >= len(text) or text[i + 1] != marker)
                and (marker == "*" or i + 1 >= len(text) or not text[i + 1].isalnum())):
            return i
    return -1


def write(document: RichDocument) -> str:
    out: list[str] = []
    numbers = ListNumbering()
    previous: Block | None = None
    for block in document.blocks:
        if previous is not None:
            both_items = previous.type is BlockType.LIST_ITEM and block.type is BlockType.LIST_ITEM
            out.append("\n" if both_items else "\n\n")
        if block.type is BlockType.HEADING:
            numbers.reset()
            out.append("#" * max(1, min(block.level, 6)) + " " + _inline(block.runs).replace("\n", " "))
        elif block.type is BlockType.LIST_ITEM:
            out.append(" " * (block.level * 2))
            out.append(f"{numbers.next(block)}. " if block.ordered else "- ")
            out.append(_inline(block.runs).replace("\n", "  \n" + " " * (block.level * 2 + 2)))
        elif block.type is BlockType.CODE:
            numbers.reset()
            out.append("```\n" + block.text + "\n```")
        else:
            numbers.reset()
            out.append(_inline(block.runs).replace("\n", "  \n"))
        previous = block
    return "".join(out) + "\n"


def _inline(runs: list[Run]) -> str:
    out: list[str] = []
    for run in runs:
        text = "`" + run.text + "`" if run.code else _escape(run.text)
        if not run.text.strip():
            out.append(run.text)
            continue
        # Markers must hug the text: "** bold**" is not bold.
        stripped = text.strip()
        lead = text[: len(text) - len(text.lstrip())]
        trail = text[len(text.rstrip()):]
        text = stripped
        if run.italic:
            text = "*" + text + "*"
        if run.bold:
            text = "**" + text + "**"
        if run.link:
            text = "[" + text + "](" + run.link.replace(" ", "%20").replace(")", "%29") + ")"
        out.append(lead + text + trail)
    return "".join(out)


def _escape(text: str) -> str:
    return _ESCAPE.sub(r"\\\1", text)
