"""The icons on the wheel and in the tool windows, drawn in code on a 24 × 24 grid with round line ends.

Every glyph is a function that draws with the painter's current pen, so the caller chooses colour and weight."""

from __future__ import annotations

import math
from collections.abc import Callable

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QBrush, QColor, QPainter, QPainterPath, QPen, QPolygonF


def _line(p: QPainter, x1: float, y1: float, x2: float, y2: float) -> None:
    p.drawLine(QPointF(x1, y1), QPointF(x2, y2))


def _poly(p: QPainter, *points: float) -> None:
    p.drawPolyline(QPolygonF([QPointF(points[i], points[i + 1]) for i in range(0, len(points), 2)]))


def _rect(p: QPainter, x: float, y: float, w: float, h: float, r: float = 2.0) -> None:
    p.drawRoundedRect(QRectF(x, y, w, h), r, r)


def _circle(p: QPainter, cx: float, cy: float, r: float) -> None:
    p.drawEllipse(QPointF(cx, cy), r, r)


def _dot(p: QPainter, cx: float, cy: float, r: float = 0.9) -> None:
    pen = p.pen()
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QBrush(pen.color()))
    p.drawEllipse(QPointF(cx, cy), r, r)
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.setPen(pen)


def _path(p: QPainter, build: Callable[[QPainterPath], None]) -> None:
    path = QPainterPath()
    build(path)
    p.drawPath(path)


def _arc(p: QPainter, cx: float, cy: float, r: float, start: float, span: float) -> None:
    """An arc in degrees, 0 at 3 o'clock, counter-clockwise like Qt."""
    p.drawArc(QRectF(cx - r, cy - r, 2 * r, 2 * r), int(start * 16), int(span * 16))


def image(p):
    _rect(p, 3, 4, 18, 16)
    _circle(p, 9, 10, 1.6)
    _poly(p, 3, 17, 9, 12.5, 13, 16, 16, 13.5, 21, 18)


def document(p):
    _path(p, lambda q: (q.moveTo(6, 3), q.lineTo(14, 3), q.lineTo(19, 8), q.lineTo(19, 21), q.lineTo(6, 21), q.closeSubpath()))
    _poly(p, 14, 3, 14, 8, 19, 8)
    _line(p, 9, 13, 16, 13)
    _line(p, 9, 17, 16, 17)


def film(p):
    _rect(p, 3, 5, 18, 14)
    _line(p, 7, 5, 7, 19)
    _line(p, 17, 5, 17, 19)
    for y in (9, 12, 15):
        _line(p, 3, y, 7, y)
        _line(p, 17, y, 21, y)


def music(p):
    _circle(p, 8, 17, 2.5)
    _circle(p, 17, 15, 2.5)
    _line(p, 10.5, 17, 10.5, 6)
    _line(p, 19.5, 15, 19.5, 4)
    _line(p, 10.5, 6, 19.5, 4)


def archive(p):
    _rect(p, 3, 4, 18, 5, 1.2)
    _path(p, lambda q: (q.moveTo(5, 9), q.lineTo(5, 19), q.arcTo(QRectF(5, 18, 2, 2), 180, 90), q.lineTo(17, 20),
                        q.arcTo(QRectF(17, 18, 2, 2), 270, 90), q.lineTo(19, 9)))
    _line(p, 10, 13, 14, 13)


def table(p):
    _rect(p, 3, 4, 18, 16)
    _line(p, 3, 10, 21, 10)
    _line(p, 3, 15, 21, 15)
    _line(p, 9, 4, 9, 20)


def subtitle(p):
    _rect(p, 3, 5, 18, 14)
    _line(p, 7, 11, 11, 11)
    _line(p, 13, 11, 17, 11)
    _line(p, 7, 15, 14, 15)


def trim(p):
    _poly(p, 9, 5, 5, 5, 5, 19, 9, 19)
    _poly(p, 15, 5, 19, 5, 19, 19, 15, 19)
    _line(p, 9, 12, 15, 12)


def split(p):
    _circle(p, 6, 6, 2.5)
    _circle(p, 6, 18, 2.5)
    _line(p, 8, 7.6, 20, 17)
    _line(p, 8, 16.4, 20, 7)


def speed(p):
    _arc(p, 12, 16, 8.5, 0, 180)
    _line(p, 3.5, 16, 5.5, 16)
    _line(p, 18.5, 16, 20.5, 16)
    _line(p, 12, 16, 16, 10.5)
    _dot(p, 12, 16, 1.2)


def volume(p):
    _path(p, lambda q: (q.moveTo(4, 9.5), q.lineTo(8, 9.5), q.lineTo(13, 5), q.lineTo(13, 19), q.lineTo(8, 14.5),
                        q.lineTo(4, 14.5), q.closeSubpath()))
    _arc(p, 13, 12, 5, -45, 90)
    _arc(p, 13, 12, 8.5, -45, 90)


def bleep(p):
    for x, h in ((5, 3), (8.5, 6), (12, 9), (15.5, 5), (19, 2.5)):
        _line(p, x, 12 - h, x, 12 + h)
    _line(p, 3, 21, 21, 3)


def channels(p):
    _arc(p, 12, 13, 8.5, 0, 180)
    _rect(p, 3, 13, 4.5, 7, 1.8)
    _rect(p, 16.5, 13, 4.5, 7, 1.8)


def visualizer(p):
    _circle(p, 12, 12, 9)
    for x, h in ((8.5, 2), (12, 5), (15.5, 3)):
        _line(p, x, 12 - h, x, 12 + h)


def hide(p):
    _path(p, lambda q: (q.moveTo(2, 12), q.quadTo(12, 3.5, 22, 12), q.quadTo(12, 20.5, 2, 12)))
    _circle(p, 12, 12, 3)
    _line(p, 4, 20, 20, 4)


def crop(p):
    _poly(p, 6, 2, 6, 18, 22, 18)
    _poly(p, 2, 6, 18, 6, 18, 22)


def join(p):
    _rect(p, 3, 3, 13, 11)
    _rect(p, 8, 10, 13, 11)


def compress(p):
    _poly(p, 10, 4, 10, 10, 4, 10)
    _poly(p, 14, 20, 14, 14, 20, 14)
    _line(p, 10, 10, 3.5, 3.5)
    _line(p, 14, 14, 20.5, 20.5)


def frames(p):
    _rect(p, 7, 3, 14, 12)
    _path(p, lambda q: (q.moveTo(3, 8), q.lineTo(3, 19), q.arcTo(QRectF(3, 17, 4, 4), 180, 90), q.lineTo(15, 21)))
    _poly(p, 7, 12, 11, 8, 15, 12.5)
    _circle(p, 17, 6.5, 1.2)


def edit(p):
    for y, knob in ((7, 8.5), (12, 15.5), (17, 9)):
        _line(p, 3.5, y, knob - 2.4, y)
        _line(p, knob + 2.4, y, 20.5, y)
        _circle(p, knob, y, 2.2)


def annotate(p):
    _path(p, lambda q: (q.moveTo(4, 20), q.lineTo(5, 15), q.lineTo(16, 4), q.lineTo(20, 8), q.lineTo(9, 19), q.closeSubpath()))
    _line(p, 13.5, 6.5, 17.5, 10.5)
    _line(p, 5, 15, 9, 19)


def pages(p):
    for y in (6, 12, 18):
        _line(p, 10, y, 20, y)
    _line(p, 5, 4.5, 5, 8)
    _poly(p, 4, 11, 6, 11, 6, 13, 4, 13, 4, 14.5, 6.2, 14.5)
    _dot(p, 5, 18)


def background(p):
    _rect(p, 3, 3, 18, 18)
    _rect(p, 7, 7, 10, 10, 1)


def collage(p):
    for x, y in ((3, 3), (13, 3), (3, 13), (13, 13)):
        _rect(p, x, y, 8, 8, 1.6)


def info(p):
    _circle(p, 12, 12, 9)
    _line(p, 12, 11, 12, 17)
    _dot(p, 12, 7.6, 1.1)


def create_pdf(p):
    document(p)
    _line(p, 17, 15, 17, 21)
    _line(p, 14, 18, 20, 18)


def extract(p):
    _path(p, lambda q: (q.moveTo(4, 12), q.lineTo(4, 19), q.arcTo(QRectF(4, 18, 2, 2), 180, 90), q.lineTo(18, 20),
                        q.arcTo(QRectF(18, 18, 2, 2), 270, 90), q.lineTo(20, 12)))
    _line(p, 12, 16, 12, 3.5)
    _poly(p, 8, 7.5, 12, 3.5, 16, 7.5)


def merge(p):
    _rect(p, 8, 8, 12, 13)
    _path(p, lambda q: (q.moveTo(16, 4.5), q.lineTo(6, 4.5), q.quadTo(4, 4.5, 4, 6.5), q.lineTo(4, 16)))
    _line(p, 11, 13, 17, 13)
    _line(p, 11, 17, 17, 17)


def text(p):
    _poly(p, 3, 8, 3, 3, 8, 3)
    _poly(p, 16, 3, 21, 3, 21, 8)
    _poly(p, 21, 16, 21, 21, 16, 21)
    _poly(p, 8, 21, 3, 21, 3, 16)
    _line(p, 8, 9, 16, 9)
    _line(p, 12, 9, 12, 16)


def remove_background(p):
    _line(p, 4, 20, 14, 10)
    _line(p, 12, 8, 16, 12)
    _line(p, 18, 3, 18, 8)
    _line(p, 15.5, 5.5, 20.5, 5.5)
    _line(p, 19.5, 14, 19.5, 18)
    _line(p, 17.5, 16, 21.5, 16)
    _dot(p, 8, 5, 0.9)


def float_(p):
    _poly(p, 3, 14, 3, 19, 21, 19, 21, 14)
    _line(p, 12, 3.5, 12, 14)
    _poly(p, 8, 10.5, 12, 14.5, 16, 10.5)


def copy(p):
    _rect(p, 5, 5, 14, 16)
    _rect(p, 9, 3, 6, 4, 1.2)
    _line(p, 8.5, 12, 15.5, 12)
    _line(p, 8.5, 16, 13.5, 16)


def move(p):
    _path(p, lambda q: (q.moveTo(3, 7), q.lineTo(3, 18), q.arcTo(QRectF(3, 17, 2, 2), 180, 90), q.lineTo(19, 19),
                        q.arcTo(QRectF(19, 17, 2, 2), 270, 90), q.lineTo(21, 9), q.lineTo(12, 9), q.lineTo(10, 5.5),
                        q.lineTo(3, 5.5), q.closeSubpath()))
    _line(p, 9, 14, 15, 14)
    _poly(p, 13, 12, 15.5, 14, 13, 16)


def path(p):
    p.save()
    p.translate(12, 12)
    p.rotate(-45)
    _rect(p, -10.5, -3, 11.5, 6, 3)
    _rect(p, -1, -3, 11.5, 6, 3)
    p.restore()


def terminal(p):
    _rect(p, 3, 4, 18, 16)
    _poly(p, 7, 9, 11, 12, 7, 15)
    _line(p, 13, 15.5, 17, 15.5)


def rotate_left(p):
    _arc(p, 12, 13, 7.5, 90, 250)
    _poly(p, 7, 2.5, 4.5, 6.5, 9.5, 8)


def rotate_right(p):
    _arc(p, 12, 13, 7.5, -160, 250)
    _poly(p, 17, 2.5, 19.5, 6.5, 14.5, 8)


def flip_h(p):
    _line(p, 12, 3, 12, 21)
    _poly(p, 9, 7, 3.5, 17, 9, 17, 9, 7)
    _poly(p, 15, 7, 20.5, 17, 15, 17, 15, 7)


def flip_v(p):
    _line(p, 3, 12, 21, 12)
    _poly(p, 7, 9, 17, 9, 17, 3.5, 7, 9)
    _poly(p, 7, 15, 17, 15, 17, 20.5, 7, 15)


def select(p):
    _poly(p, 6, 3, 6, 19, 10.5, 15, 13.5, 21)
    _line(p, 10.5, 15, 16, 15)


def arrow(p):
    _line(p, 5, 19, 19, 5)
    _poly(p, 9, 5, 19, 5, 19, 15)


def ellipse(p):
    p.drawEllipse(QPointF(12, 12), 9, 6.5)


def textmark(p):
    _line(p, 5, 6, 19, 6)
    _line(p, 12, 6, 12, 19)
    _line(p, 9, 19, 15, 19)


def number(p):
    _circle(p, 12, 12, 9)
    _poly(p, 10, 9, 12.5, 7.5, 12.5, 16.5)


def highlighter(p):
    _poly(p, 4, 20, 8, 20, 9.5, 17)
    _path(p, lambda q: (q.moveTo(8.5, 15.5), q.lineTo(16, 4), q.lineTo(20, 8), q.lineTo(11, 17.5), q.closeSubpath()))


def magnifier(p):
    _circle(p, 10.5, 10.5, 6.5)
    _line(p, 15.5, 15.5, 21, 21)
    _line(p, 8, 10.5, 13, 10.5)
    _line(p, 10.5, 8, 10.5, 13)


GLYPHS: dict[str, Callable[[QPainter], None]] = {
    "image": image, "document": document, "film": film, "music": music, "archive": archive, "table": table,
    "subtitle": subtitle, "trim": trim, "split": split, "speed": speed, "volume": volume, "bleep": bleep,
    "channels": channels, "visualizer": visualizer, "hide": hide, "crop": crop, "join": join, "compress": compress,
    "frames": frames, "edit": edit, "annotate": annotate, "pages": pages, "background": background, "collage": collage,
    "info": info, "createPdf": create_pdf, "extract": extract, "merge": merge, "text": text,
    "removeBackground": remove_background, "float": float_, "copy": copy, "move": move, "path": path,
    "terminal": terminal, "rotateLeft": rotate_left, "rotateRight": rotate_right, "flipH": flip_h, "flipV": flip_v,
    "select": select, "arrow": arrow, "ellipse": ellipse, "textmark": textmark, "number": number,
    "highlighter": highlighter, "magnifier": magnifier,
}


def draw(painter: QPainter, name: str, rect: QRectF, color: QColor, weight: float = 1.7) -> None:
    """Draws glyph `name` filling `rect` in `color`; `weight` is the line width on the 24-unit grid."""
    glyph = GLYPHS.get(name, document)
    painter.save()
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.translate(rect.center())
    scale = min(rect.width(), rect.height()) / 24.0
    painter.scale(scale, scale)
    painter.translate(-12, -12)
    pen = QPen(color, weight)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    painter.setPen(pen)
    painter.setBrush(Qt.BrushStyle.NoBrush)
    glyph(painter)
    painter.restore()


def pixmap(name: str, size: int, color: QColor, weight: float = 1.7):  # noqa: ANN201
    from PySide6.QtGui import QGuiApplication, QPixmap

    ratio = QGuiApplication.primaryScreen().devicePixelRatio() if QGuiApplication.primaryScreen() else 1.0
    result = QPixmap(int(size * ratio), int(size * ratio))
    result.setDevicePixelRatio(ratio)
    result.fill(Qt.GlobalColor.transparent)
    painter = QPainter(result)
    draw(painter, name, QRectF(0, 0, size, size), color, weight)
    painter.end()
    return result


def icon(name: str, size: int = 18, color: QColor | None = None):  # noqa: ANN201
    from PySide6.QtGui import QIcon

    from . import brand

    return QIcon(pixmap(name, size, color or brand.text_color()))


__all__ = ["GLYPHS", "draw", "pixmap", "icon", "math"]
