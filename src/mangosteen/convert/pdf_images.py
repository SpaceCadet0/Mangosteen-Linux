"""PDF files made of images: a page per image, written directly so photos keep their original JPEG data."""

from __future__ import annotations

import io
import zlib
from dataclasses import dataclass

from PIL import Image

from . import qtutil


@dataclass
class PdfPage:
    """One page: the decoded image, the original JPEG bytes when they can be embedded untouched, and the
    image's resolution."""

    image: Image.Image
    jpeg: bytes | None = None
    dpi: tuple[float, float] | None = None


class _Writer:
    def __init__(self) -> None:
        self.buffer = io.BytesIO()
        self.buffer.write(b"%PDF-1.5\n%\xe2\xe3\xcf\xd3\n")
        self.offsets: list[int] = []

    def add(self, entries: str, stream: bytes | None = None) -> int:
        """Writes an object (the entries of its dictionary, optionally with a stream) and returns its number."""
        number = len(self.offsets) + 1
        self.offsets.append(self.buffer.tell())
        self.buffer.write(f"{number} 0 obj\n".encode())
        if stream is None:
            self.buffer.write(f"<< {entries} >>\nendobj\n".encode())
        else:
            self.buffer.write(f"<< {entries} /Length {len(stream)} >>\nstream\n".encode())
            self.buffer.write(stream)
            self.buffer.write(b"\nendstream\nendobj\n")
        return number

    def reserve(self) -> int:
        """Reserves an object number to fill in later (the page tree refers to pages before they exist)."""
        self.offsets.append(-1)
        return len(self.offsets)

    def fill(self, number: int, body: bytes) -> None:
        self.offsets[number - 1] = self.buffer.tell()
        self.buffer.write(f"{number} 0 obj\n".encode() + body + b"\nendobj\n")

    def finish(self, root: int) -> bytes:
        start = self.buffer.tell()
        count = len(self.offsets) + 1
        self.buffer.write(f"xref\n0 {count}\n0000000000 65535 f \n".encode())
        for offset in self.offsets:
            self.buffer.write(f"{offset:010d} 00000 n \n".encode())
        self.buffer.write(f"trailer\n<< /Size {count} /Root {root} 0 R >>\nstartxref\n{start}\n%%EOF\n".encode())
        return self.buffer.getvalue()


def _number(value: float) -> str:
    return f"{value:.4f}".rstrip("0").rstrip(".")


def write_pdf(pages: list[PdfPage], output: str) -> None:
    if not pages:
        raise ValueError("There are no images to put into the PDF.")
    writer = _Writer()
    catalog = writer.reserve()
    tree = writer.reserve()
    page_numbers: list[int] = []
    for page in pages:
        image = page.image
        width, height = image.size
        dpi_x, dpi_y = page.dpi if page.dpi and page.dpi[0] > 1 and page.dpi[1] > 1 else (96.0, 96.0)
        page_width, page_height = width * 72.0 / dpi_x, height * 72.0 / dpi_y
        image_object = _add_image(writer, page)
        content = f"q {_number(page_width)} 0 0 {_number(page_height)} 0 0 cm /Im0 Do Q".encode()
        content_object = writer.add("/Filter /FlateDecode", zlib.compress(content))
        number = writer.reserve()
        page_numbers.append(number)
        writer.fill(number, (
            f"<< /Type /Page /Parent {tree} 0 R /MediaBox [0 0 {_number(page_width)} {_number(page_height)}] "
            f"/Resources << /XObject << /Im0 {image_object} 0 R >> >> /Contents {content_object} 0 R >>").encode())
    kids = " ".join(f"{n} 0 R" for n in page_numbers)
    writer.fill(tree, f"<< /Type /Pages /Kids [{kids}] /Count {len(page_numbers)} >>".encode())
    writer.fill(catalog, f"<< /Type /Catalog /Pages {tree} 0 R >>".encode())
    with open(output, "wb") as stream:
        stream.write(writer.finish(catalog))


def _add_image(writer: _Writer, page: PdfPage) -> int:
    image = page.image
    width, height = image.size
    base = f"/Type /XObject /Subtype /Image /Width {width} /Height {height}"
    if page.jpeg is not None and image.mode in ("RGB", "L"):
        space = "/DeviceGray" if image.mode == "L" else "/DeviceRGB"
        return writer.add(f"{base} /ColorSpace {space} /BitsPerComponent 8 /Filter /DCTDecode", page.jpeg)
    mask_object = None
    if image.mode in ("RGBA", "LA") or "transparency" in image.info:
        rgba = image.convert("RGBA")
        alpha = rgba.getchannel("A")
        if alpha.getextrema() != (255, 255):
            mask_object = writer.add(
                f"{base} /ColorSpace /DeviceGray /BitsPerComponent 8 /Filter /FlateDecode", zlib.compress(alpha.tobytes()))
        rgb = rgba.convert("RGB")
    else:
        rgb = image.convert("RGB") if image.mode != "L" else image
    space = "/DeviceGray" if rgb.mode == "L" else "/DeviceRGB"
    mask = f" /SMask {mask_object} 0 R" if mask_object else ""
    return writer.add(f"{base} /ColorSpace {space} /BitsPerComponent 8 /Filter /FlateDecode{mask}",
                      zlib.compress(rgb.tobytes()))


def svg_to_pdf(path: str, output: str) -> None:
    """Keeps vectors: draws the SVG straight into a PDF page."""
    from PySide6.QtCore import QMarginsF, QSizeF
    from PySide6.QtGui import QPageLayout, QPageSize, QPainter, QPdfWriter
    from PySide6.QtSvg import QSvgRenderer

    qtutil.ensure_gui_app()
    renderer = QSvgRenderer(path)
    size = renderer.defaultSize()
    if not renderer.isValid() or size.width() <= 0 or size.height() <= 0:
        raise ValueError(f"Could not read {path}.")
    writer = QPdfWriter(output)
    writer.setResolution(72)
    writer.setPageSize(QPageSize(QSizeF(size.width(), size.height()), QPageSize.Unit.Point))
    writer.setPageMargins(QMarginsF(0, 0, 0, 0), QPageLayout.Unit.Point)
    painter = QPainter(writer)
    renderer.render(painter)
    painter.end()
