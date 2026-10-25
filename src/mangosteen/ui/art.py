"""The mangosteen drawn in code: a cross-section whose white segments echo the wheel. Used for the app icon and the
tray icon."""

from __future__ import annotations

import math
import random

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import (QBrush, QColor, QIcon, QPainter, QPainterPath, QPainterPathStroker, QPen, QPixmap,
                           QRadialGradient)

# Segment spans in degrees (sum 360), lengths and tints differ slightly, like a real fruit.
_SPANS = [64, 55, 61, 57, 66, 57]
_LENGTHS = [1.0, 0.95, 0.985, 0.93, 1.0, 0.96]
_TINTS = [(1.0, 0.99, 0.98), (0.99, 0.97, 0.97), (1.0, 0.98, 0.96), (0.98, 0.96, 0.97), (1.0, 0.99, 0.97),
          (0.99, 0.97, 0.96)]
_START_ANGLE = 97.0


def _color(r: float, g: float, b: float, a: float = 1.0) -> QColor:
    return QColor.fromRgbF(r, g, b, a)


def _point(center: QPointF, radius: float, degrees: float) -> QPointF:
    radians = math.radians(degrees)
    return QPointF(center.x() + radius * math.cos(radians), center.y() - radius * math.sin(radians))


def _segment(center: QPointF, radius: float, start: float, span: float, gap: float, corner: float) -> QPainterPath:
    """A wedge with rounded corners whose straight edges stay `gap` away from the neighbours."""
    inset = gap / 2 + corner
    outer = radius - corner
    half_span = math.radians(span / 2)
    tip_radius = inset / math.sin(half_span)
    edge_angle = math.degrees(math.asin(min(inset / outer, 1.0)))
    path = QPainterPath()
    path.moveTo(_point(center, tip_radius, start + span / 2))
    path.lineTo(_point(center, outer, start + edge_angle))
    rect = QRectF(center.x() - outer, center.y() - outer, 2 * outer, 2 * outer)
    path.arcTo(rect, start + edge_angle, span - 2 * edge_angle)
    path.closeSubpath()
    # Growing the shape by its stroke rounds every corner.
    stroker = QPainterPathStroker()
    stroker.setWidth(corner * 2)
    stroker.setCapStyle(Qt.PenCapStyle.RoundCap)
    stroker.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    return path.united(stroker.createStroke(path))


def draw_icon(painter: QPainter, rect: QRectF, detailed: bool = True) -> None:
    """Draws the fruit filling `rect` (transparent outside the circle). `detailed` adds the speckled rind."""
    painter.save()
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    center = rect.center()
    radius = min(rect.width(), rect.height()) / 2 * 0.94

    def circle(r: float) -> QRectF:
        return QRectF(center.x() - r, center.y() - r, 2 * r, 2 * r)

    # Soft drop shadow under the fruit.
    painter.setPen(Qt.PenStyle.NoPen)
    for i in range(6, 0, -1):
        painter.setBrush(_color(0.2, 0.02, 0.1, 0.07))
        r = radius + radius * 0.012 * i
        painter.drawEllipse(QRectF(center.x() - r, center.y() - r + radius * 0.03, 2 * r, 2 * r))

    # Rind: deep wine purple, lighter towards the upper left.
    rind = QRadialGradient(center, radius * 1.05, QPointF(center.x() - radius * 0.3, center.y() - radius * 0.35))
    rind.setColorAt(0, _color(0.58, 0.16, 0.30))
    rind.setColorAt(1, _color(0.36, 0.06, 0.19))
    painter.setBrush(QBrush(rind))
    painter.drawEllipse(circle(radius))

    # The reddish inner layer of the rind, fading into the darker outer skin.
    rim = radius * 0.82
    inner = QRadialGradient(center, rim)
    inner.setColorAt(0, _color(0.62, 0.2, 0.3))
    inner.setColorAt(0.8, _color(0.62, 0.2, 0.3))
    inner.setColorAt(1, _color(0.5, 0.12, 0.24))
    painter.setBrush(QBrush(inner))
    painter.drawEllipse(circle(rim))

    if detailed:
        # A light, deterministic speckle on the rind and the inner layer.
        rng = random.Random(0x9E3779B9)
        for _ in range(160):
            distance = radius * (0.74 + rng.random() * 0.24)
            angle = rng.random() * 360
            size = radius * (0.006 + rng.random() * 0.012)
            spot = _point(center, distance, angle)
            painter.setBrush(_color(0.86, 0.45, 0.45, 0.35) if rng.random() > 0.45 else _color(0.25, 0.03, 0.1, 0.35))
            painter.drawEllipse(QRectF(spot.x() - size, spot.y() - size, 2 * size, 2 * size))

    # Dark well between the segments.
    flesh = radius * 0.72
    painter.setBrush(_color(0.28, 0.04, 0.13))
    painter.drawEllipse(circle(flesh))

    # The white segments.
    angle = _START_ANGLE
    for span, length, tint in zip(_SPANS, _LENGTHS, _TINTS):
        path = _segment(center, flesh * 0.985 * length, angle, span, flesh * 0.035, flesh * 0.14)
        gradient = QRadialGradient(center, flesh)
        gradient.setColorAt(0, _color(tint[0] * 0.86, tint[1] * 0.8, tint[2] * 0.82))
        gradient.setColorAt(0.55, _color(*tint))
        gradient.setColorAt(1, _color(*tint))
        painter.setBrush(QBrush(gradient))
        painter.drawPath(path)
        angle += span
    painter.restore()


def draw_mono(painter: QPainter, rect: QRectF, color: QColor) -> None:
    """The segments alone in one colour, for small monochrome uses."""
    painter.save()
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    center = rect.center()
    flesh = min(rect.width(), rect.height()) / 2 * 0.97
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(color)
    angle = _START_ANGLE
    scale = flesh / 9.0
    for span, length in zip(_SPANS, _LENGTHS):
        painter.drawPath(_segment(center, flesh * length, angle, span, 1.0 * scale, 0.45 * scale))
        angle += span
    painter.restore()


def pixmap(size: int, detailed: bool | None = None) -> QPixmap:
    result = QPixmap(size, size)
    result.fill(Qt.GlobalColor.transparent)
    painter = QPainter(result)
    draw_icon(painter, QRectF(0, 0, size, size), detailed if detailed is not None else size >= 64)
    painter.end()
    return result


def app_icon() -> QIcon:
    icon = QIcon()
    for size in (16, 24, 32, 48, 64, 128, 256, 512):
        icon.addPixmap(pixmap(size))
    return icon
