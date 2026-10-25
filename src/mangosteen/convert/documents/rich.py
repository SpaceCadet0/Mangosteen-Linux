"""The common model every document format is read into and written from: paragraphs, headings, lists, code
blocks, and bold, italic, underlined, linked or code text. Images, tables and page layout are not kept."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from enum import Enum


class BlockType(Enum):
    PARAGRAPH = "paragraph"
    HEADING = "heading"
    LIST_ITEM = "list_item"
    CODE = "code"


@dataclass(frozen=True)
class Run:
    """A stretch of text with one style. Line breaks inside a paragraph are "\\n", tabs "\\t"."""

    text: str
    bold: bool = False
    italic: bool = False
    underline: bool = False
    link: str | None = None
    code: bool = False

    def same_style(self, other: Run) -> bool:
        return (self.bold, self.italic, self.underline, self.link, self.code) == (
            other.bold, other.italic, other.underline, other.link, other.code)


@dataclass
class Block:
    """A paragraph, heading (level 1-6), list item (level 0 = top, `ordered`) or code block."""

    type: BlockType = BlockType.PARAGRAPH
    level: int = 0
    ordered: bool = False
    runs: list[Run] = field(default_factory=list)

    @property
    def text(self) -> str:
        return "".join(r.text for r in self.runs)

    def add(self, run: Run) -> None:
        """Appends text, merging it with the last run when the style matches."""
        if not run.text:
            return
        if self.runs and self.runs[-1].same_style(run):
            self.runs[-1] = replace(self.runs[-1], text=self.runs[-1].text + run.text)
        else:
            self.runs.append(run)

    def trim(self) -> None:
        """Drops leading and trailing whitespace of the paragraph (but not of code blocks)."""
        if self.type is BlockType.CODE or not self.runs:
            return
        self.runs[0] = replace(self.runs[0], text=self.runs[0].text.lstrip(" \n"))
        self.runs[-1] = replace(self.runs[-1], text=self.runs[-1].text.rstrip(" \n"))
        self.runs = [r for r in self.runs if r.text]


class ListNumbering:
    """Counts ordered list items per nesting level; any non-list block restarts the count."""

    def __init__(self) -> None:
        self._counters: list[int] = []

    def next(self, item: Block) -> int:
        while len(self._counters) <= item.level:
            self._counters.append(0)
        del self._counters[item.level + 1:]
        self._counters[item.level] += 1
        return self._counters[item.level]

    def reset(self) -> None:
        self._counters.clear()


@dataclass
class RichDocument:
    blocks: list[Block] = field(default_factory=list)

    @staticmethod
    def from_plain_text(text: str) -> RichDocument:
        document = RichDocument()
        for line in text.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
            block = Block(BlockType.PARAGRAPH)
            block.add(Run(line))
            document.blocks.append(block)
        while document.blocks and not document.blocks[-1].runs:
            document.blocks.pop()
        return document

    def to_plain_text(self) -> str:
        """Plain text: one line per paragraph; list items get a bullet or their number."""
        lines: list[str] = []
        numbers = ListNumbering()
        for block in self.blocks:
            prefix = ""
            if block.type is BlockType.LIST_ITEM:
                prefix = " " * (block.level * 4) + (f"{numbers.next(block)}. " if block.ordered else "• ")
            else:
                numbers.reset()
            lines.append(prefix + block.text)
        return "".join(line + "\n" for line in lines)
