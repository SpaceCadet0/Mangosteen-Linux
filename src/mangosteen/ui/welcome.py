"""The welcome window: how the three wheels work, next to a short looping video of the three gestures."""

from __future__ import annotations

import os
from pathlib import Path

from PySide6.QtCore import QRectF, Qt, QTimer
from PySide6.QtGui import QPainter, QPainterPath, QPixmap
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from ..core import log
from ..core.loc import L
from ..core.wheel_catalog import WheelKind
from . import art, brand, glyphs, layoututil

_ASSETS = Path(__file__).resolve().parent.parent / "assets"
_SIDE = 300


class DemoVideo(QWidget):
    """The demo from the README, square, looping silently; it stops when the window closes. It is an animated WebP:
    Qt's video player needs a multimedia backend that some builds lack (PySide6 for ARM, on a Raspberry Pi). QMovie
    plays it where Qt has its WebP plugin; otherwise Pillow decodes the frames. Snapshots show a still from it."""

    def __init__(self, use_qmovie: bool = True) -> None:
        super().__init__()
        self.setFixedSize(_SIDE, _SIDE)
        self._movie = None
        self._frames = None
        self._frame: QPixmap | None = None
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._next_frame)
        self._still = QPixmap(str(_ASSETS / "welcome-demo.png"))
        animation = _ASSETS / "welcome-demo.webp"
        if not animation.is_file() or os.environ.get("MANGOSTEEN_NO_PLAYER"):
            return
        if use_qmovie:
            from PySide6.QtGui import QMovie

            movie = QMovie(str(animation), parent=self)
            if movie.isValid() and movie.frameCount() > 1:
                movie.setCacheMode(QMovie.CacheMode.CacheNone)
                movie.frameChanged.connect(lambda _frame: self.update())
                self._movie = movie
                return
        try:
            self._frames = _PillowFrames(animation)
        except Exception as error:  # noqa: BLE001 - the still is shown instead
            log.write(f"welcome animation unavailable: {error}")

    @property
    def is_playing(self) -> bool:
        return self._movie is not None or self._frames is not None

    def _next_frame(self) -> None:
        if self._frames is None:
            return
        image, duration = self._frames.next(self.devicePixelRatioF())
        self._frame = QPixmap.fromImage(image)
        self.update()
        self._timer.start(max(duration, 15))

    def paintEvent(self, _event) -> None:  # noqa: ANN001, N802
        if self._movie is not None:
            frame = self._movie.currentPixmap()
        else:
            frame = self._frame if self._frame is not None else self._still
        if frame.isNull():
            frame = self._still
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        path = QPainterPath()
        path.addRoundedRect(QRectF(self.rect()), 12, 12)
        painter.setClipPath(path)
        painter.drawPixmap(QRectF(self.rect()), frame, QRectF(frame.rect()))
        painter.end()

    def showEvent(self, event) -> None:  # noqa: ANN001, N802
        if self._movie is not None:
            self._movie.start()
        elif self._frames is not None:
            self._next_frame()
        super().showEvent(event)

    def hideEvent(self, event) -> None:  # noqa: ANN001, N802
        if self._movie is not None:
            self._movie.setPaused(True)
        self._timer.stop()
        super().hideEvent(event)

    def stop(self) -> None:
        if self._movie is not None:
            self._movie.stop()
        self._timer.stop()


class _PillowFrames:
    """The frames of an animated WebP, one at a time, decoded by Pillow."""

    def __init__(self, path: Path) -> None:
        from PIL import Image

        self._image = Image.open(path)
        self._count = getattr(self._image, "n_frames", 1)
        if self._count < 2:
            raise ValueError("not an animation")
        self._index = -1

    def next(self, ratio: float) -> tuple:  # (QImage, duration in ms)
        from ..convert import qtutil

        self._index = (self._index + 1) % self._count
        self._image.seek(self._index)
        self._image.load()
        duration = int(self._image.info.get("duration") or 33)
        frame = self._image.convert("RGB")
        side = max(1, round(_SIDE * ratio))
        if frame.width != side:
            from PIL import Image

            frame = frame.resize((side, side), Image.Resampling.BILINEAR)
        image = qtutil.pil_to_qimage(frame)
        image.setDevicePixelRatio(ratio)
        return image, duration


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
