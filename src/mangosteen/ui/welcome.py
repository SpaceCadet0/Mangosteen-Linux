"""The welcome window: how the three wheels work, with a small animation of a drag, a tap and a drop."""

from __future__ import annotations

import math
import time

from PySide6.QtCore import QPointF, QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QFont, QPainter, QPen, QPixmap
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from ..core.loc import L
from ..core.wheel_catalog import WheelItem, WheelKind
from . import art, layoututil, brand, glyphs
from .wheel import DIAMETER, WheelWidget

_LOOP = 7.2


def _ease(t: float) -> float:
    t = max(0.0, min(1.0, t))
    return t * t * (3 - 2 * t)


def _between(t: float, start: float, end: float) -> float:
    return _ease((t - start) / (end - start))


class DemoWidget(QWidget):
    """A looping animation: drag a file, tap Shift, drop it on a segment, find the result next to the original."""

    def __init__(self, modifier: str = "Shift") -> None:
        super().__init__()
        self.setFixedSize(560, 280)
        self._modifier = modifier
        self._started = time.monotonic()
        self._timer = QTimer(self)
        self._timer.timeout.connect(self.update)
        self._wheel_pixmap: QPixmap | None = None

    def showEvent(self, event) -> None:  # noqa: ANN001, N802
        self._started = time.monotonic()
        self._timer.start(16)
        super().showEvent(event)

    def hideEvent(self, event) -> None:  # noqa: ANN001, N802
        self._timer.stop()
        super().hideEvent(event)

    def _wheel(self) -> QPixmap:
        if self._wheel_pixmap is None:
            wheel = WheelWidget()
            titles = [("PNG", "image"), ("WebP", "image"), ("HEIC", "image"), ("TIFF", "image"), ("GIF", "image"),
                      ("PDF", "document")]
            items = [WheelItem(f"demo.{t.lower()}", t, icon) for t, icon in titles]
            wheel.configure(WheelKind.CONVERT, items, 1)
            wheel.highlight_for_test(0)
            self._wheel_pixmap = wheel.grab()
            self._wheel_pixmap.setDevicePixelRatio(1.0)
        return self._wheel_pixmap

    def paintEvent(self, _event) -> None:  # noqa: ANN001, N802
        t = (time.monotonic() - self._started) % _LOOP
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        window = brand.window_color()
        dark = brand.is_dark()
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(window.lighter(108) if dark else window.darker(104))
        painter.drawRoundedRect(self.rect(), 14, 14)

        text = brand.text_color()
        # Where the file card is.
        start, mid = QPointF(120, 170), QPointF(290, 130)
        # The segment at 12 o'clock-ish of the mini wheel (index 0 → straight up).
        scale = 0.62
        wheel_center = mid
        target = QPointF(wheel_center.x(), wheel_center.y() - 112 * scale)
        if t < 1.0:
            pos = start
        elif t < 2.4:
            f = _between(t, 1.0, 2.4)
            pos = QPointF(start.x() + (mid.x() - start.x()) * f, start.y() + (mid.y() - start.y()) * f)
        elif t < 3.8:
            pos = mid
        elif t < 4.6:
            f = _between(t, 3.8, 4.6)
            pos = QPointF(mid.x() + (target.x() - mid.x()) * f, mid.y() + (target.y() - mid.y()) * f)
        else:
            pos = target

        # The wheel.
        wheel_alpha = (_between(t, 3.0, 3.35) if t < 5.0 else 1 - _between(t, 5.0, 5.35))
        if wheel_alpha > 0.01:
            pixmap = self._wheel()
            size = DIAMETER * scale * (0.85 + 0.15 * wheel_alpha)
            painter.setOpacity(wheel_alpha)
            painter.drawPixmap(QRectF(wheel_center.x() - size / 2, wheel_center.y() - size / 2, size, size), pixmap,
                               QRectF(pixmap.rect()))
            painter.setOpacity(1.0)

        # The key cap.
        key_down = 2.45 < t < 2.95
        key_alpha = _between(t, 2.2, 2.45) if t < 3.6 else 1 - _between(t, 3.6, 3.9)
        if key_alpha > 0.01:
            painter.setOpacity(key_alpha)
            rect = QRectF(self.width() - 140, self.height() - 70, 96, 38)
            if key_down:
                rect.translate(0, 2)
            painter.setBrush(brand.BRAND if key_down else window.lighter(125) if dark else window)
            painter.setPen(QPen(QColor(0, 0, 0, 60), 1))
            painter.drawRoundedRect(rect, 8, 8)
            painter.setPen(QColor("white") if key_down else text)
            font = QFont(self.font())
            font.setBold(True)
            painter.setFont(font)
            painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, self._modifier)
            painter.setOpacity(1.0)

        # The original file, and its result.
        card_alpha = 1.0 if t < 4.5 else 1 - _between(t, 4.5, 4.9) if t < 4.9 else 0.0
        if card_alpha > 0.01:
            self._card(painter, pos, "photo.jpg", "image", card_alpha, 1.0 - 0.25 * _between(t, 4.2, 4.6))
        original = QPointF(120, 220)
        if t >= 4.9:
            self._card(painter, original, "photo.jpg", "image", 0.55 + 0.45 * (1 - _between(t, 4.9, 5.2)), 0.8)
            result_alpha = _between(t, 5.2, 5.6) * (1 - _between(t, 6.8, 7.2))
            self._card(painter, QPointF(original.x() + 150, original.y()), "photo.png", "image", result_alpha, 0.8,
                       checked=True)
        # The pointer.
        if 1.0 <= t < 5.0:
            painter.setPen(QPen(text, 1.4))
            painter.setBrush(text)
            tip = QPointF(pos.x() + 22, pos.y() + 16)
            painter.drawPolygon([tip, QPointF(tip.x() + 4, tip.y() + 15), QPointF(tip.x() + 8, tip.y() + 11),
                                 QPointF(tip.x() + 13, tip.y() + 13)])
        painter.end()

    def _card(self, painter: QPainter, center: QPointF, name: str, icon: str, alpha: float, scale: float,
              checked: bool = False) -> None:
        painter.save()
        painter.setOpacity(alpha)
        painter.translate(center)
        painter.scale(scale, scale)
        card = QRectF(-48, -34, 96, 68)
        window = brand.window_color()
        painter.setPen(QPen(QColor(0, 0, 0, 50), 1))
        painter.setBrush(window.lighter(120) if brand.is_dark() else QColor("white"))
        painter.drawRoundedRect(card, 10, 10)
        glyphs.draw(painter, icon, QRectF(-14, -28, 28, 28), brand.accent(), 1.8)
        painter.setPen(brand.text_color())
        font = QFont(self.font())
        font.setPointSizeF(9.5)
        painter.setFont(font)
        painter.drawText(QRectF(-48, 4, 96, 24), Qt.AlignmentFlag.AlignCenter, name)
        if checked:
            painter.setPen(QPen(QColor("#2E9E5B"), 2.4, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
            painter.drawPolyline([QPointF(30, -26), QPointF(35, -21), QPointF(43, -31)])
        painter.restore()


class WelcomeWindow(QWidget):
    def __init__(self, keys: dict[WheelKind, str], drag_available: bool) -> None:
        super().__init__()
        self.setWindowTitle(L("Welcome to Mangosteen"))
        self.setWindowIcon(art.app_icon())
        names = {"shift": "Shift", "ctrl": "Ctrl", "alt": "Alt", "super": "Super", "none": "—"}
        layout = QVBoxLayout(self)
        layout.setContentsMargins(30, 26, 30, 24)
        layout.setSpacing(10)
        head = QHBoxLayout()
        icon = QLabel()
        icon.setPixmap(art.pixmap(56))
        title = QLabel(L("Welcome to Mangosteen"))
        title.setStyleSheet("font-size: 22px; font-weight: 700;")
        head.addWidget(icon)
        head.addWidget(title, 1)
        layout.addLayout(head)
        intro = QLabel(L("Converters and tools for your files, at a drag. Everything runs locally, with no "
                         "third-party services and no limits."))
        intro.setWordWrap(True)
        layout.addWidget(intro)
        self.demo = DemoWidget(names.get(keys.get(WheelKind.CONVERT, "shift"), "Shift"))
        layout.addWidget(self.demo, alignment=Qt.AlignmentFlag.AlignCenter)

        cards = QHBoxLayout()
        for kind, glyph, title_text, body in (
                (WheelKind.CONVERT, "image", L("Convert"),
                 L("Turns files into another format: images, documents, PDF, tables, archives, video and audio.")),
                (WheelKind.TOOLS, "edit", L("Tools"),
                 L("Compress, crop and resize in pixels, photo editor, annotate, trim a video and more, with a live "
                   "preview.")),
                (WheelKind.ACTIONS, "float", L("Actions"),
                 L("Float shelf, copy, move, copy the path or open a terminal."))):
            card = QWidget()
            column = QVBoxLayout(card)
            column.setContentsMargins(0, 0, 0, 0)
            key = QLabel(names.get(keys.get(kind, ""), "—"))
            key.setStyleSheet(f"font-weight: 700; color: {brand.accent().name()};")
            heading = QLabel(title_text)
            heading.setStyleSheet("font-weight: 600; font-size: 14px;")
            text = QLabel(body)
            text.setWordWrap(True)
            text.setStyleSheet("color: gray;")
            top = QHBoxLayout()
            symbol = QLabel()
            symbol.setPixmap(glyphs.pixmap(glyph, 20, brand.accent(), 1.9))
            top.addWidget(symbol)
            top.addWidget(heading, 1)
            top.addWidget(key)
            column.addLayout(top)
            column.addWidget(text)
            column.addStretch(1)
            cards.addWidget(card, 1)
            cards.setSpacing(20)
        layout.addLayout(cards)

        how = (L("Start dragging a file, tap the key without letting go of the mouse, and drop the file on a segment. "
                 "The result appears next to the original.") if drag_available else
               L("Right-click a file in the file manager and choose Mangosteen: the wheel opens at the pointer. "
                 "Click a segment. The result appears next to the original file; the original itself is never changed."))
        how_label = QLabel(how)
        how_label.setWordWrap(True)
        layout.addWidget(how_label)
        other = QLabel(L("Without the keys: click the Mangosteen icon in the panel and choose files, or right-click "
                         "a file in the file manager."))
        other.setWordWrap(True)
        other.setStyleSheet("color: gray;")
        layout.addWidget(other)
        button = QPushButton(L("Got it"))
        button.setDefault(True)
        button.clicked.connect(self.close)
        layout.addWidget(button, alignment=Qt.AlignmentFlag.AlignRight)
        layoututil.fit(self, 620)

    def present(self) -> None:
        self.show()
        self.raise_()
        self.activateWindow()


__all__ = ["WelcomeWindow", "DemoWidget", "math"]
