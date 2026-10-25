"""HTML into the document model (structure and inline styles), and a clean UTF-8 page out of it."""

from __future__ import annotations

import html as _html
import re
from dataclasses import dataclass, replace
from html.parser import HTMLParser

from .rich import Block, BlockType, Run, RichDocument

_VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"}
_SKIPPED = {"script", "style", "head", "title", "noscript", "template", "svg", "iframe"}
_BLOCKS = {
    "p", "div", "section", "article", "blockquote", "header", "footer", "main", "nav", "aside", "address", "dl", "dt",
    "dd", "figure", "figcaption", "table", "thead", "tbody", "tfoot", "tr", "caption", "form", "fieldset", "hr", "body",
    "center", "details", "summary",
}
# Opening one of these closes an open element of the listed kind (HTML's optional end tags).
_CLOSES = {
    "li": {"li"}, "p": {"p"}, "dt": {"dt", "dd"}, "dd": {"dt", "dd"}, "tr": {"tr", "td", "th"}, "td": {"td", "th"},
    "th": {"td", "th"}, "option": {"option"},
}
_BOUNDARY = {"ul", "ol", "table", "dl", "body", "div", "section", "article", "blockquote", "menu"}
_WS = re.compile(r"\s+")
_BOLD_CSS = re.compile(r"font-weight\s*:\s*(bold|[6-9]00)", re.IGNORECASE)


@dataclass
class _Node:
    tag: str
    attrs: dict[str, str]
    children: list  # of _Node | str


class _TreeBuilder(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.root = _Node("#root", {}, [])
        self.stack = [self.root]

    def handle_starttag(self, tag, attrs):  # noqa: ANN001
        closes = _CLOSES.get(tag)
        if closes:
            for index in range(len(self.stack) - 1, 0, -1):
                name = self.stack[index].tag
                if name in closes:
                    del self.stack[index:]
                    break
                if name in _BOUNDARY or name in ("li", "tr", "td", "th") and tag != "li" and name not in closes:
                    break
        elif tag in _BLOCKS and self.stack[-1].tag == "p":
            self.stack.pop()
        node = _Node(tag, {k: (v or "") for k, v in attrs}, [])
        self.stack[-1].children.append(node)
        if tag not in _VOID:
            self.stack.append(node)

    def handle_startendtag(self, tag, attrs):  # noqa: ANN001
        node = _Node(tag, {k: (v or "") for k, v in attrs}, [])
        self.stack[-1].children.append(node)

    def handle_endtag(self, tag):  # noqa: ANN001
        for index in range(len(self.stack) - 1, 0, -1):
            if self.stack[index].tag == tag:
                del self.stack[index:]
                return

    def handle_data(self, data):  # noqa: ANN001
        self.stack[-1].children.append(data)


@dataclass(frozen=True)
class _Style:
    bold: bool = False
    italic: bool = False
    underline: bool = False
    link: str | None = None
    code: bool = False
    list_depth: int = 0
    ordered: bool = False


class _Reader:
    def __init__(self) -> None:
        self.current: Block | None = None
        self.document = RichDocument()

    def finish(self) -> None:
        self._close()

    def _close(self) -> None:
        if self.current is None:
            return
        self.current.trim()
        if self.current.runs or self.current.type is BlockType.CODE:
            self.document.blocks.append(self.current)
        self.current = None

    def _block(self) -> Block:
        if self.current is None:
            self.current = Block(BlockType.PARAGRAPH)
        return self.current

    def _run(self, text: str, style: _Style) -> None:
        self._block().add(Run(text, style.bold, style.italic, style.underline, style.link, style.code))

    def walk(self, node: _Node, style: _Style) -> None:
        for child in node.children:
            if isinstance(child, str):
                value = _WS.sub(" ", child)
                if self.current is None and not value.strip():
                    continue
                if self.current is not None and self.current.runs and self.current.runs[-1].text.endswith("\n"):
                    value = value.lstrip(" ")  # the line feed after a <br> is only formatting
                self._run(value, style)
            else:
                self._element(child, style)

    def _element(self, element: _Node, style: _Style) -> None:
        tag = element.tag
        if tag in _SKIPPED:
            return
        if tag == "br":
            self._run("\n", style)
        elif tag in ("h1", "h2", "h3", "h4", "h5", "h6"):
            self._close()
            self.current = Block(BlockType.HEADING, int(tag[1]))
            self.walk(element, style)
            self._close()
        elif tag in ("ul", "ol", "menu"):
            self._close()
            self.walk(element, replace(style, list_depth=style.list_depth + 1, ordered=tag == "ol"))
            self._close()
        elif tag == "li":
            self._close()
            self.current = Block(BlockType.LIST_ITEM, max(0, style.list_depth - 1), style.ordered)
            self.walk(element, style)
            self._close()
        elif tag == "pre":
            self._close()
            code = Block(BlockType.CODE)
            code.add(Run(_text_content(element).rstrip("\n"), code=True))
            self.document.blocks.append(code)
        elif tag in ("td", "th"):
            self.walk(element, style)
            self._block().add(Run("\t"))
        elif tag in ("b", "strong"):
            self.walk(element, replace(style, bold=True))
        elif tag in ("i", "em", "cite", "var", "dfn"):
            self.walk(element, replace(style, italic=True))
        elif tag in ("u", "ins"):
            self.walk(element, replace(style, underline=True))
        elif tag in ("code", "kbd", "samp", "tt"):
            self.walk(element, replace(style, code=True))
        elif tag == "a":
            href = element.attrs.get("href", "")
            self.walk(element, style if not href or href.startswith("#") else replace(style, link=href))
        elif tag == "img":
            return
        elif tag in _BLOCKS:
            self._close()
            self.walk(element, style)
            self._close()
        else:
            self.walk(element, _apply_css(element, style))


def _apply_css(element: _Node, style: _Style) -> _Style:
    css = element.attrs.get("style", "")
    if not css:
        return style
    lowered = css.lower()
    return replace(style,
                   bold=style.bold or _BOLD_CSS.search(css) is not None,
                   italic=style.italic or "italic" in lowered,
                   underline=style.underline or "underline" in lowered)


def _text_content(node: _Node) -> str:
    return "".join(c if isinstance(c, str) else _text_content(c) for c in node.children)


def _find(node: _Node, tag: str) -> _Node | None:
    for child in node.children:
        if isinstance(child, _Node):
            if child.tag == tag:
                return child
            found = _find(child, tag)
            if found is not None:
                return found
    return None


def parse(page: str) -> RichDocument:
    builder = _TreeBuilder()
    builder.feed(page)
    builder.close()
    reader = _Reader()
    body = _find(builder.root, "body") or builder.root
    reader.walk(body, _Style())
    reader.finish()
    return reader.document


def write(document: RichDocument, title: str) -> str:
    out = [
        "<!DOCTYPE html>\n<html>\n<head>\n<meta charset=\"utf-8\">\n<title>", _html.escape(title),
        "</title>\n<style>body { font-family: system-ui, \"Segoe UI\", Arial, sans-serif; line-height: 1.5; "
        "max-width: 46em; margin: 2em auto; padding: 0 1em; } pre { background: #f4f4f4; padding: 0.8em; "
        "overflow-x: auto; }</style>\n</head>\n<body>\n",
    ]
    open_lists: list[bool] = []

    def close_lists_to(depth: int) -> None:
        while len(open_lists) > depth:
            out.append("</ol>\n" if open_lists.pop() else "</ul>\n")

    for block in document.blocks:
        if block.type is not BlockType.LIST_ITEM:
            close_lists_to(0)
        if block.type is BlockType.HEADING:
            level = max(1, min(block.level, 6))
            out.append(f"<h{level}>{_inline(block.runs)}</h{level}>\n")
        elif block.type is BlockType.LIST_ITEM:
            close_lists_to(block.level + 1)
            if len(open_lists) == block.level + 1 and open_lists[-1] != block.ordered:
                close_lists_to(block.level)
            while len(open_lists) < block.level + 1:
                out.append("<ol>\n" if block.ordered else "<ul>\n")
                open_lists.append(block.ordered)
            out.append(f"<li>{_inline(block.runs)}</li>\n")
        elif block.type is BlockType.CODE:
            out.append(f"<pre><code>{_html.escape(block.text)}</code></pre>\n")
        else:
            out.append(f"<p>{_inline(block.runs)}</p>\n")
    close_lists_to(0)
    out.append("</body>\n</html>\n")
    return "".join(out)


def _inline(runs) -> str:  # noqa: ANN001
    out = []
    for run in runs:
        text = _html.escape(run.text).replace("\n", "<br>\n").replace("\t", "&emsp;")
        if run.code:
            text = f"<code>{text}</code>"
        if run.underline:
            text = f"<u>{text}</u>"
        if run.italic:
            text = f"<em>{text}</em>"
        if run.bold:
            text = f"<strong>{text}</strong>"
        if run.link:
            text = f'<a href="{_html.escape(run.link)}">{text}</a>'
        out.append(text)
    return "".join(out)
