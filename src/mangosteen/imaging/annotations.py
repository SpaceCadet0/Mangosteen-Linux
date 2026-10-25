"""Marks on a photo: arrows, shapes, text, numbered steps, pencil, highlighter, magnifier and pasted pictures.

Geometry is in pixels of the full-size upright image, origin at the top-left."""

from __future__ import annotations

import itertools
import math
import os
from dataclasses import dataclass, field, replace

from PIL import Image

from ..convert import images, qtutil
from ..core import format_catalog, output_naming
from ..core.file_format import FileFormat, detect
from ..core.loc import L
from ..core.settings import ConversionOptions
from .compose import RGBA

Point = tuple[float, float]
Rect = tuple[float, float, float, float]  # x, y, width, height

MAGNIFICATION = 2.0
_ids = itertools.count(1)

TOOLS = ["select", "pen", "arrow", "rectangle", "ellipse", "text", "number", "highlight", "magnifier", "image"]

RED = RGBA(1.0, 0.231, 0.188)


@dataclass
class Annotation:
    kind: str  # arrow, rectangle, ellipse, text, number, pen, highlight, magnifier, image
    color: RGBA = RED
    line_width: float = 6.0
    font_size: float = 40.0
    start: Point = (0.0, 0.0)  # arrow start; text origin (top-left); number and magnifier centre
    end: Point = (0.0, 0.0)  # arrow end
    rect: Rect = (0.0, 0.0, 0.0, 0.0)  # rectangle, ellipse, image
    text: str = ""
    number: int = 1
    radius: float = 80.0  # magnifier
    points: list[Point] = field(default_factory=list)  # pen, highlight
    image_path: str | None = None
    id: int = field(default_factory=lambda: next(_ids))


def tool_title(tool: str) -> str:
    return {"select": L("Select"), "arrow": L("Arrow"), "rectangle": L("Rectangle"), "ellipse": L("Oval"),
            "text": L("Text"), "number": L("Number"), "pen": L("Pencil"), "highlight": L("Highlighter"),
            "magnifier": L("Magnifier"), "image": L("Picture")}[tool]


def tool_glyph(tool: str) -> str:
    return {"select": "select", "arrow": "arrow", "rectangle": "background", "ellipse": "ellipse", "text": "textmark",
            "number": "number", "pen": "annotate", "highlight": "highlighter", "magnifier": "magnifier",
            "image": "image"}[tool]


def _standard(rect: Rect) -> Rect:
    x, y, w, h = rect
    return (x + min(w, 0), y + min(h, 0), abs(w), abs(h))


def text_size(text: str, font_size: float) -> tuple[float, float]:
    from PySide6.QtGui import QFontMetricsF

    qtutil.ensure_gui_app()
    metrics = QFontMetricsF(_font(font_size))
    box = metrics.boundingRect(text or " ")
    return max(box.width(), metrics.horizontalAdvance(text or " ")), metrics.height()


def _font(size: float):  # noqa: ANN202
    from PySide6.QtGui import QFont, QGuiApplication

    font = QFont(QGuiApplication.font())
    font.setPixelSize(max(1, int(round(size))))
    font.setBold(True)
    return font


def bounds(a: Annotation) -> Rect:
    if a.kind == "arrow":
        return (min(a.start[0], a.end[0]), min(a.start[1], a.end[1]), abs(a.end[0] - a.start[0]), abs(a.end[1] - a.start[1]))
    if a.kind in ("rectangle", "ellipse", "image"):
        return _standard(a.rect)
    if a.kind == "text":
        w, h = text_size(a.text, a.font_size)
        return (a.start[0], a.start[1], w, h)
    if a.kind == "number":
        r = a.font_size * 0.75
        return (a.start[0] - r, a.start[1] - r, 2 * r, 2 * r)
    if a.kind in ("pen", "highlight"):
        if not a.points:
            return (0.0, 0.0, 0.0, 0.0)
        xs, ys = [p[0] for p in a.points], [p[1] for p in a.points]
        return (min(xs), min(ys), max(xs) - min(xs), max(ys) - min(ys))
    if a.kind == "magnifier":
        return (a.start[0] - a.radius, a.start[1] - a.radius, 2 * a.radius, 2 * a.radius)
    return (0.0, 0.0, 0.0, 0.0)


def translated(a: Annotation, dx: float, dy: float) -> Annotation:
    def move(p: Point) -> Point:
        return (p[0] + dx, p[1] + dy)

    return replace(a, start=move(a.start), end=move(a.end), rect=(a.rect[0] + dx, a.rect[1] + dy, a.rect[2], a.rect[3]),
                   points=[move(p) for p in a.points])


# Handles: ("start" | "end" | "radius" | ("corner", "tl"|"tr"|"br"|"bl"), point)
def handles(a: Annotation) -> list[tuple[object, Point]]:
    if a.kind == "arrow":
        return [("start", a.start), ("end", a.end)]
    if a.kind in ("rectangle", "ellipse", "image"):
        x, y, w, h = _standard(a.rect)
        return [(("corner", "tl"), (x, y)), (("corner", "tr"), (x + w, y)), (("corner", "br"), (x + w, y + h)),
                (("corner", "bl"), (x, y + h))]
    if a.kind == "magnifier":
        return [("radius", (a.start[0] + a.radius, a.start[1]))]
    return []


def moving(a: Annotation, handle: object, point: Point, image_aspect: float | None = None) -> Annotation:
    """Moves one handle of `a` (as it was when the drag began) to `point`."""
    def resize(rect: Rect, corner: str) -> Rect:
        x, y, w, h = _standard(rect)
        opposite = (x + w if "l" in corner else x, y + h if corner[0] == "t" else y)
        width = max(abs(point[0] - opposite[0]), 4.0)
        height = max(abs(point[1] - opposite[1]), 4.0)
        if image_aspect and image_aspect > 0:
            height = width / image_aspect
            width = height * image_aspect
        nx = opposite[0] - width if point[0] < opposite[0] else opposite[0]
        ny = opposite[1] - height if point[1] < opposite[1] else opposite[1]
        return (nx, ny, width, height)

    if a.kind == "arrow" and handle == "start":
        return replace(a, start=point)
    if a.kind == "arrow" and handle == "end":
        return replace(a, end=point)
    if isinstance(handle, tuple) and a.kind in ("rectangle", "ellipse", "image"):
        return replace(a, rect=resize(a.rect, handle[1]))
    if a.kind == "magnifier" and handle == "radius":
        return replace(a, radius=max(math.hypot(point[0] - a.start[0], point[1] - a.start[1]), 8.0))
    return a


def hit_test(annotations: list[Annotation], point: Point, tolerance: float) -> int | None:
    """The topmost annotation under `point`, within `tolerance` pixels."""
    for a in reversed(annotations):
        slop = tolerance + a.line_width
        x, y, w, h = bounds(a)
        if x - slop <= point[0] <= x + w + slop and y - slop <= point[1] <= y + h + slop:
            return a.id
    return None


# MARK: Drawing


def render(annotations: list[Annotation], base: Image.Image, full_size: tuple[float, float],
           pictures: dict[str, Image.Image] | None = None) -> Image.Image:
    """Draws `base` (any size) with annotations given in `full_size` pixel coordinates on top."""
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QImage, QPainter

    qtutil.ensure_gui_app()
    qbase = qtutil.pil_to_qimage(base)
    canvas = QImage(qbase.width(), qbase.height(), QImage.Format.Format_ARGB32_Premultiplied)
    canvas.fill(Qt.GlobalColor.transparent)
    painter = QPainter(canvas)
    painter.setRenderHints(QPainter.RenderHint.Antialiasing | QPainter.RenderHint.SmoothPixmapTransform
                           | QPainter.RenderHint.TextAntialiasing)
    painter.drawImage(0, 0, qbase)
    scale = base.width / max(full_size[0], 1)
    painter.scale(scale, scale)
    pictures = pictures or {}
    for annotation in annotations:
        painter.save()
        draw_annotation(painter, annotation, qbase, scale, pictures)
        painter.restore()
    painter.end()
    return qtutil.qimage_to_pil(canvas)


def draw_annotation(p, a: Annotation, base, scale: float, pictures: dict) -> None:  # noqa: ANN001
    """Draws one annotation with `p` set up in full-size pixel coordinates; `base` is the QImage the magnifier looks
    at and `scale` how many of its pixels make one full-size pixel. `pictures` maps image paths to QImage or PIL."""
    from PySide6.QtCore import QPointF, QRectF, Qt
    from PySide6.QtGui import QBrush, QColor, QPainter, QPainterPath, QPen, QPolygonF

    color = a.color.to_qcolor()
    pen = QPen(color, a.line_width)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    p.setPen(pen)
    p.setBrush(Qt.BrushStyle.NoBrush)

    if a.kind == "arrow":
        length = math.hypot(a.end[0] - a.start[0], a.end[1] - a.start[1])
        if length <= 0:
            return
        dx, dy = (a.end[0] - a.start[0]) / length, (a.end[1] - a.start[1]) / length
        head = min(a.line_width * 4 + 6, length)
        bx, by = a.end[0] - dx * head, a.end[1] - dy * head
        spread = head * 0.6
        p.drawLine(QPointF(*a.start), QPointF(bx, by))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(color))
        p.drawPolygon(QPolygonF([QPointF(*a.end), QPointF(bx - dy * spread, by + dx * spread),
                                 QPointF(bx + dy * spread, by - dx * spread)]))
    elif a.kind == "rectangle":
        x, y, w, h = _standard(a.rect)
        radius = min(a.line_width * 1.5, min(w, h) / 2)
        p.drawRoundedRect(QRectF(x, y, w, h), radius, radius)
    elif a.kind == "ellipse":
        x, y, w, h = _standard(a.rect)
        p.drawEllipse(QRectF(x, y, w, h))
    elif a.kind == "text":
        font = _font(a.font_size)
        p.setFont(font)
        shadow = QColor(0, 0, 0, 115)
        p.setPen(shadow)
        offset = max(1.0, a.font_size * 0.04)
        box = QRectF(a.start[0], a.start[1], 10000, a.font_size * 3)
        flags = int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        p.drawText(box.translated(offset, offset), flags, a.text)
        p.setPen(color)
        p.drawText(box, flags, a.text)
    elif a.kind == "number":
        radius = a.font_size * 0.75
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(color))
        p.drawEllipse(QPointF(*a.start), radius, radius)
        p.setFont(_font(a.font_size * 0.85))
        p.setPen(QColor("white"))
        p.drawText(QRectF(a.start[0] - radius, a.start[1] - radius, 2 * radius, 2 * radius), int(Qt.AlignmentFlag.AlignCenter),
                   str(a.number))
    elif a.kind == "pen":
        _stroke(p, a.points)
    elif a.kind == "highlight":
        p.setCompositionMode(QPainter.CompositionMode.CompositionMode_Multiply)
        p.setOpacity(0.4)
        pen.setWidthF(a.line_width * 5)
        pen.setCapStyle(Qt.PenCapStyle.SquareCap)
        p.setPen(pen)
        _stroke(p, a.points)
    elif a.kind == "magnifier":
        side = a.radius * 2 / MAGNIFICATION
        source = QRectF((a.start[0] - side / 2) * scale, (a.start[1] - side / 2) * scale, side * scale, side * scale)
        circle = QRectF(a.start[0] - a.radius, a.start[1] - a.radius, 2 * a.radius, 2 * a.radius)
        clip = QPainterPath()
        clip.addEllipse(circle)
        p.save()
        p.setClipPath(clip)
        p.drawImage(circle, base, source)
        p.restore()
        p.setPen(QPen(QColor("white"), a.line_width * 2))
        p.drawEllipse(circle)
        p.setPen(QPen(color, a.line_width))
        p.drawEllipse(circle)
    elif a.kind == "image" and a.image_path in pictures:
        x, y, w, h = _standard(a.rect)
        picture = pictures[a.image_path]
        p.drawImage(QRectF(x, y, w, h), picture if hasattr(picture, "isNull") else qtutil.pil_to_qimage(picture))


def _stroke(p, points: list[Point]) -> None:  # noqa: ANN001
    from PySide6.QtCore import QPointF
    from PySide6.QtGui import QPainterPath

    if not points:
        return
    path = QPainterPath(QPointF(*points[0]))
    if len(points) == 1:
        path.lineTo(QPointF(*points[0]))
    for point in points[1:]:
        path.lineTo(QPointF(*point))
    p.drawPath(path)


def annotate_file(path: str, annotations: list[Annotation], pictures: dict[str, Image.Image],
                  options: ConversionOptions) -> str:
    """Writes `<name> (annotated).<ext>` next to the original."""
    source = detect(path)
    if source is None:
        raise ValueError(f"Unknown format of {os.path.basename(path)}.")
    image, metadata = images.load(path)
    result = render(annotations, image, (image.width, image.height), pictures)
    target = source if source in format_catalog.EDITABLE_IMAGE_FORMATS else FileFormat.PNG

    def produce(output: str) -> None:
        images.write(result, target, output, options, metadata if options.preserve_metadata else None)

    return output_naming.write_atomically(os.path.dirname(os.path.abspath(path)),
                                          f"{output_naming.base_name(path)} ({L('annotated')})", target.extension, produce)
