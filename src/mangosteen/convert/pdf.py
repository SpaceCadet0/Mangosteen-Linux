"""PDF files: pages to images, text extraction, merge, split and page organising.

pdfium (through pypdfium2) draws pages and reads text; pypdf copies, rotates and reorders pages."""

from __future__ import annotations

import os
import threading
from collections.abc import Callable
from dataclasses import dataclass

from PIL import Image

from ..core import loc, output_naming
from ..core.cancellation import CancellationToken
from ..core.file_format import FileFormat, detect
from ..core.settings import ConversionOptions
from . import images
from .documents.rich import Block, BlockType, RichDocument, Run

# pdfium is not thread safe; every call into it goes through this lock.
_lock = threading.RLock()

# Pages are rendered at this resolution, like the other Mangosteen apps.
DPI = 300
# Very large pages (posters, drawings) are scaled down so a page stays a reasonable image.
MAX_SIDE = 10000


class PdfLocked(Exception):
    """The PDF is protected with a password."""

    def __init__(self, name: str) -> None:
        super().__init__(loc.fmt("“{0}” is locked with a password.", name))
        self.name = name


class PdfUnreadable(Exception):
    pass


def _open(path: str):  # noqa: ANN202
    import pypdfium2 as pdfium

    try:
        return pdfium.PdfDocument(path)
    except pdfium.PdfiumError as error:
        if getattr(error, "err_code", None) == 4 or "password" in str(error).lower():
            raise PdfLocked(os.path.basename(path)) from error
        raise PdfUnreadable(f"{os.path.basename(path)}: {error}") from error


def page_count(path: str) -> int:
    with _lock:
        document = _open(path)
        try:
            return len(document)
        finally:
            document.close()


def _render(document, index: int, dpi: float = DPI, max_side: float = MAX_SIDE) -> Image.Image:  # noqa: ANN001
    page = document[index]
    try:
        width, height = page.get_size()  # in points, already rotated
        scale = dpi / 72.0
        fit = min(1.0, max_side / max(width * scale, height * scale))
        image = page.render(scale=scale * fit).to_pil()
        return image.convert("RGB")
    finally:
        page.close()


def _page_size(document, index: int) -> tuple[float, float]:  # noqa: ANN001
    """The page size in points. The page object is closed here, before its document can be."""
    page = document[index]
    try:
        return page.get_size()
    finally:
        page.close()


def render_page(path: str, index: int = 0, dpi: float = DPI, max_side: float = MAX_SIDE) -> Image.Image:
    """A page on white, honouring its rotation."""
    with _lock:
        document = _open(path)
        try:
            return _render(document, index, dpi, max_side)
        finally:
            document.close()


def thumbnails(path: str, max_side: int, cancellation: CancellationToken | None = None) -> list[Image.Image]:
    """Small images of every page, the longer side at most `max_side` pixels."""
    result: list[Image.Image] = []
    with _lock:
        document = _open(path)
        try:
            for index in range(len(document)):
                if cancellation is not None:
                    cancellation.throw_if_cancelled()
                width, height = _page_size(document, index)
                result.append(_render(document, index, dpi=72.0 * max_side / max(width, height, 1), max_side=max_side))
        finally:
            document.close()
    return result


def render_pages(path: str, target: FileFormat, folder: str, base_name: str, options: ConversionOptions,
                 cancellation: CancellationToken | None = None,
                 progress: Callable[[float], None] | None = None) -> None:
    """Writes `name 1.png`, `name 2.png`… (numbers padded to the page count) into a new folder."""
    os.makedirs(folder, exist_ok=True)
    with _lock:
        document = _open(path)
        try:
            count = len(document)
            digits = len(str(count))
            for index in range(count):
                if cancellation is not None:
                    cancellation.throw_if_cancelled()
                image = _render(document, index, options.pdf_render_dpi)
                file = os.path.join(folder, f"{base_name} {str(index + 1).rjust(digits, '0')}.{target.extension}")
                images.write(image, target, file, options)
                if progress:
                    progress((index + 1) / count)
        finally:
            document.close()


def plain_text(path: str) -> str:
    """The text of every page in reading order, pages separated by a blank line."""
    pages: list[str] = []
    with _lock:
        document = _open(path)
        try:
            for index in range(len(document)):
                page = document[index]
                try:
                    textpage = page.get_textpage()
                    try:
                        pages.append(textpage.get_text_range().replace("\r\n", "\n").replace("\r", "\n").strip())
                    finally:
                        textpage.close()
                finally:
                    page.close()
        finally:
            document.close()
    return "\n\n".join(pages)


def read_document(path: str) -> RichDocument:
    """Paragraphs from the text layer: blank lines separate paragraphs, and lines inside a paragraph are joined
    (a word split by a hyphen at the end of a line is put back together)."""
    document = RichDocument()
    for chunk in plain_text(path).split("\n\n"):
        lines = [line.strip() for line in chunk.split("\n") if line.strip()]
        if not lines:
            continue
        text = lines[0]
        for line in lines[1:]:
            if len(text) > 1 and text[-1] == "-" and text[-2].isalpha() and line[0].islower():
                text = text[:-1]
            else:
                text += " "
            text += line
        block = Block(BlockType.PARAGRAPH)
        block.add(Run(text))
        document.blocks.append(block)
    return document


def convert(input_path: str, target: FileFormat, output: str, options: ConversionOptions) -> None:
    from .documents import converter as documents

    if target.category.value == "image":
        images.write(render_page(input_path, 0, options.pdf_render_dpi), target, output, options)
    elif target is FileFormat.TXT:
        from ..core import text_file

        text_file.write(output, plain_text(input_path) + "\n")
    else:
        documents.write(read_document(input_path), target, output, output_naming.base_name(input_path))


# MARK: Several PDFs


def create_from_images(paths: list[str]) -> str:
    """One PDF with a page per image, next to the first image: its name for one image, "Images" for several."""
    from . import pdf_images

    sources = [p for p in paths if (f := detect(p)) is not None and f.is_raster_image]
    if not sources:
        raise ValueError("There are no images to put into a PDF.")
    first = os.path.abspath(sources[0])
    name = output_naming.base_name(first) if len(sources) == 1 else "Images"

    def produce(output: str) -> None:
        pages = []
        for source in sources:
            image, metadata = images.load(source)
            jpeg = None
            if detect(source) is FileFormat.JPG and images._is_upright_jpeg(source):  # noqa: SLF001
                jpeg = images._jpeg_bytes(source)  # noqa: SLF001
            pages.append(pdf_images.PdfPage(image, jpeg, metadata.dpi))
        pdf_images.write_pdf(pages, output)

    return output_naming.write_atomically(os.path.dirname(first), name, "pdf", produce)


def _reader(path: str):  # noqa: ANN202
    from pypdf import PdfReader
    from pypdf.errors import PdfReadError

    try:
        reader = PdfReader(path)
    except (PdfReadError, OSError, ValueError) as error:
        raise PdfUnreadable(f"{os.path.basename(path)} could not be opened: {error}") from error
    if reader.is_encrypted:
        try:
            if reader.decrypt("") == 0:
                raise PdfLocked(os.path.basename(path))
        except PdfLocked:
            raise
        except Exception as error:  # noqa: BLE001
            raise PdfLocked(os.path.basename(path)) from error
    return reader


def merge(paths: list[str]) -> str:
    """The PDFs in the given order as one "Merged.pdf" next to the first."""
    from pypdf import PdfWriter

    pdfs = [p for p in paths if detect(p) is FileFormat.PDF]
    if len(pdfs) < 2:
        raise ValueError("Merging needs at least two PDFs.")
    first = os.path.abspath(pdfs[0])

    def produce(output: str) -> None:
        writer = PdfWriter()
        for path in pdfs:
            for page in _reader(path).pages:
                writer.add_page(page)
        with open(output, "wb") as stream:
            writer.write(stream)

    return output_naming.write_atomically(os.path.dirname(first), "Merged", "pdf", produce)


# MARK: Splitting


def split_documents(page_count: int, cuts, excluded) -> list[list[int]]:  # noqa: ANN001
    """A cut `i` falls after page `i` (0-based); excluded pages are left out; a part left with no pages is dropped."""
    cut_set, excluded_set = set(cuts), set(excluded)
    documents: list[list[int]] = []
    current: list[int] = []
    for page in range(page_count):
        if page not in excluded_set:
            current.append(page)
        if page in cut_set or page == page_count - 1:
            if current:
                documents.append(current)
            current = []
    return documents


def cuts_every_page(page_count: int) -> set[int]:
    return set(range(max(page_count - 1, 0)))


def cuts_in_half(page_count: int) -> set[int]:
    """One cut in the middle; an odd page goes to the first half."""
    return {(page_count + 1) // 2 - 1} if page_count >= 2 else set()


def cuts_every_n(page_count: int, n: int) -> set[int]:
    """A cut after every `n` pages."""
    return set() if n < 1 else {p - 1 for p in range(1, max(page_count - 1, 0) + 1) if p % n == 0}


def ranges(pages: list[int]) -> str:
    """Page numbers as ranges for people, 1-based: "1–3, 5, 7–8"."""
    parts: list[str] = []
    i = 0
    while i < len(pages):
        j = i
        while j + 1 < len(pages) and pages[j + 1] == pages[j] + 1:
            j += 1
        parts.append(f"{pages[i] + 1}" if i == j else f"{pages[i] + 1}–{pages[j] + 1}")
        i = j + 1
    return ", ".join(parts)


def split(path: str, cuts, excluded) -> str:  # noqa: ANN001
    """Writes the documents next to the original: several go into a `<name> (parts)` folder as `<name> 1.pdf`,
    `<name> 2.pdf`…; a single one becomes `<name> (pages).pdf`."""
    from pypdf import PdfWriter

    reader = _reader(path)
    groups = split_documents(len(reader.pages), cuts, excluded)
    if not groups:
        raise ValueError(loc.L("No suitable files."))
    base = output_naming.base_name(path)
    directory = os.path.dirname(os.path.abspath(path))

    def build(pages: list[int], target: str) -> None:
        writer = PdfWriter()
        for index in pages:
            writer.add_page(reader.pages[index])
        with open(target, "wb") as stream:
            writer.write(stream)

    if len(groups) == 1:
        return output_naming.write_atomically(directory, f"{base} ({loc.L('pages')})", "pdf",
                                              lambda out: build(groups[0], out))

    def produce(folder: str) -> None:
        os.makedirs(folder)
        for index, pages in enumerate(groups):
            number = output_naming.part_number(index, len(groups))
            build(pages, os.path.join(folder, f"{base} {number}.pdf"))

    return output_naming.write_atomically(directory, f"{base} ({loc.L('parts')})", "", produce)


# MARK: Organising


@dataclass
class PageItem:
    """One page in the organised document: which source it comes from and how much to turn it."""

    document: int
    page: int
    rotation: int = 0  # extra clockwise rotation in degrees (a multiple of 90)


def page_items(paths: list[str]) -> list[PageItem]:
    items = []
    for index, path in enumerate(paths):
        items += [PageItem(index, page) for page in range(len(_reader(path).pages))]
    return items


def save_organized(items: list[PageItem], paths: list[str], next_to: str) -> str:
    """Writes `<first name> (pages).pdf` next to the first PDF."""
    from pypdf import PdfWriter

    if not items:
        raise ValueError(loc.L("No suitable files."))
    readers = [_reader(p) for p in paths]

    def produce(output: str) -> None:
        writer = PdfWriter()
        for item in items:
            page = writer.add_page(readers[item.document].pages[item.page])
            if item.rotation % 360:
                page.rotate(item.rotation % 360)
        with open(output, "wb") as stream:
            writer.write(stream)

    directory = os.path.dirname(os.path.abspath(next_to))
    return output_naming.write_atomically(directory, f"{output_naming.base_name(next_to)} ({loc.L('pages')})", "pdf",
                                          produce)
