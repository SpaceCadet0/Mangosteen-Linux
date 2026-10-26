"""The welcome window: how the three wheels work, next to a short looping video of the three gestures."""

from __future__ import annotations

import os
from pathlib import Path

from PySide6.QtCore import QRectF, Qt, QUrl
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPixmap
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from ..core.loc import L
from ..core.wheel_catalog import WheelKind
from . import art, brand, glyphs, layoututil

_ASSETS = Path(__file__).resolve().parent.parent / "assets"
_SIDE = 300


class DemoVideo(QWidget):
    """The demo from the README, square, looping silently with no controls; it stops when the window closes. Without
    Qt's multimedia backend (or in snapshots) it shows a still from the same video."""

    def __init__(self) -> None:
        super().__init__()
        self.setFixedSize(_SIDE, _SIDE)
        self._player = None
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        video = _ASSETS / "welcome-demo.mp4"
        if video.is_file() and not os.environ.get("MANGOSTEEN_NO_PLAYER"):
            try:
                from PySide6.QtMultimedia import QMediaPlayer
                from PySide6.QtMultimediaWidgets import QVideoWidget

                self._player = QMediaPlayer(self)
                view = QVideoWidget()
                view.setAspectRatioMode(Qt.AspectRatioMode.KeepAspectRatioByExpanding)
                self._player.setVideoOutput(view)
                self._player.setLoops(QMediaPlayer.Loops.Infinite)
                self._player.setSource(QUrl.fromLocalFile(str(video)))
                layout.addWidget(view)
                return
            except ImportError:
                self._player = None
        still = QLabel()
        still.setPixmap(_rounded(QPixmap(str(_ASSETS / "welcome-demo.png")), _SIDE, 12))
        layout.addWidget(still)

    def showEvent(self, event) -> None:  # noqa: ANN001, N802
        if self._player is not None:
            self._player.play()
        super().showEvent(event)

    def hideEvent(self, event) -> None:  # noqa: ANN001, N802
        if self._player is not None:
            self._player.pause()
        super().hideEvent(event)

    def stop(self) -> None:
        if self._player is not None:
            self._player.stop()
            self._player.setSource(QUrl())


def _rounded(pixmap: QPixmap, side: int, radius: float) -> QPixmap:
    ratio = 2.0
    result = QPixmap(int(side * ratio), int(side * ratio))
    result.setDevicePixelRatio(ratio)
    result.fill(QColor(0, 0, 0, 0))
    if pixmap.isNull():
        return result
    painter = QPainter(result)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
    path = QPainterPath()
    path.addRoundedRect(QRectF(0, 0, side, side), radius, radius)
    painter.setClipPath(path)
    painter.drawPixmap(QRectF(0, 0, side, side), pixmap, QRectF(pixmap.rect()))
    painter.end()
    return result


class WelcomeWindow(QWidget):
    def __init__(self, keys: dict[WheelKind, str], drag_available: bool) -> None:
        super().__init__()
        self.setWindowTitle(L("Welcome to Mangosteen"))
        self.setWindowIcon(art.app_icon())
        names = {"shift": "Shift", "ctrl": "Ctrl", "alt": "Alt", "super": "Super", "none": "—"}
        layout = QVBoxLayout(self)
        layout.setContentsMargins(30, 26, 30, 24)
        layout.setSpacing(12)
        # Like the macOS and Windows apps: the title and how it works on the left, the video on the right.
        top = QHBoxLayout()
        top.setSpacing(24)
        left = QVBoxLayout()
        left.setSpacing(12)
        head = QHBoxLayout()
        icon = QLabel()
        icon.setPixmap(art.pixmap(56))
        title = QLabel(L("Welcome to Mangosteen"))
        title.setStyleSheet("font-size: 22px; font-weight: 700;")
        title.setWordWrap(True)
        head.addWidget(icon)
        head.addWidget(title, 1)
        left.addLayout(head)
        intro = QLabel(L("Converters and tools for your files, at a drag. Everything runs locally, with no "
                         "third-party services and no limits."))
        intro.setWordWrap(True)
        left.addWidget(intro)
        top.addLayout(left, 1)
        self.demo = DemoVideo()
        top.addWidget(self.demo, alignment=Qt.AlignmentFlag.AlignTop)
        layout.addLayout(top)

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
        left.addWidget(how_label)
        left.addStretch(1)
        other = QLabel(L("Without the keys: click the Mangosteen icon in the panel and choose files, or right-click "
                         "a file in the file manager."))
        other.setWordWrap(True)
        other.setStyleSheet("color: gray;")
        layout.addWidget(other)
        button = QPushButton(L("Got it"))
        button.setDefault(True)
        button.clicked.connect(self.close)
        layout.addWidget(button, alignment=Qt.AlignmentFlag.AlignRight)
        layoututil.fit(self, 780)

    def closeEvent(self, event) -> None:  # noqa: ANN001, N802
        self.demo.stop()
        super().closeEvent(event)

    def present(self) -> None:
        self.show()
        self.raise_()
        self.activateWindow()


__all__ = ["WelcomeWindow", "DemoVideo"]
