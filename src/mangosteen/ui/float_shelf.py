"""A floating shelf that holds references to files so they can be dragged into another app later. Files are never
copied onto the shelf; it only remembers where they are. Dragging out copies unless Move is on, so originals are
never taken by accident."""

from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor

from PySide6.QtCore import QMimeData, QPoint, QSize, Qt, QUrl, Signal
from PySide6.QtGui import QColor, QDrag, QFont, QGuiApplication, QIcon, QImage, QImageReader, QPainter, QPixmap
from PySide6.QtWidgets import (QFileIconProvider, QHBoxLayout, QLabel, QPushButton, QScrollArea, QVBoxLayout, QWidget)
from PySide6.QtCore import QFileInfo

from ..core import file_format
from ..core.loc import L, count, fmt
from . import brand, glyphs

_THUMB = 48


class _Colors:
    """The shelf's colours, following the desktop's light or dark theme."""

    def __init__(self, dark: bool) -> None:
        self.panel = QColor(0x1C, 0x1C, 0x1E) if dark else QColor(0xF7, 0xF7, 0xF8)
        self.line = QColor(0x3A, 0x3A, 0x3D) if dark else QColor(0xD9, 0xD9, 0xDD)
        self.hover = QColor(0x2C, 0x2C, 0x2F) if dark else QColor(0xE9, 0xE9, 0xEC)
        self.text = "#E6E6EA" if dark else "#1E1E21"
        self.secondary = "#9A9AA0" if dark else "#6E6E74"
        self.strong = "white" if dark else "black"


def _colors() -> _Colors:
    return _Colors(brand.is_dark())


def _exists(path: str) -> bool:
    return os.path.lexists(path)


def folder_label(folder: str) -> str:
    """A folder as a file manager names it: inside the home folder it starts with "~"."""
    home = os.path.expanduser("~")
    if home not in ("", "/") and (folder == home or folder.startswith(home.rstrip("/") + "/")):
        return "~" + folder[len(home.rstrip("/")):]
    return folder


def make_thumbnail(path: str, side: int) -> QImage | None:
    """A real thumbnail for photos and PDFs; None when the file type has none (the shelf then shows an icon)."""
    fmt_ = file_format.detect(path)
    try:
        if fmt_ is not None and fmt_.is_raster_image:
            reader = QImageReader(path)
            reader.setAutoTransform(True)
            size = reader.size()
            if size.isValid():
                scale = side / max(size.width(), size.height())
                reader.setScaledSize(QSize(max(1, int(size.width() * scale)), max(1, int(size.height() * scale))))
            image = reader.read()
            if not image.isNull():
                return image
            from ..convert import images, qtutil

            pil, _ = images.load(path, side)
            return qtutil.pil_to_qimage(pil)
        if fmt_ is file_format.FileFormat.PDF:
            from ..convert import pdf, qtutil

            return qtutil.pil_to_qimage(pdf.render_page(path, 0, dpi=72.0 * side / 600, max_side=side * 2))
    except Exception:  # noqa: BLE001 - a missing thumbnail is not an error
        return None
    return None


class _Row(QWidget):
    removed = Signal(str)

    def __init__(self, shelf: FloatShelf, paths: list[str], title: str, subtitle: str, single: str | None) -> None:
        super().__init__()
        self.shelf = shelf
        self.paths = paths
        self.single = single
        self.setAttribute(Qt.WidgetAttribute.WA_Hover)
        self.setCursor(Qt.CursorShape.OpenHandCursor)
        self._hover = False
        self._press: QPoint | None = None
        self.setToolTip(L("Drag them all at once") if single is None else (single))
        picture = QLabel()
        picture.setFixedSize(_THUMB, _THUMB)
        picture.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.picture = picture
        icon = QFileIconProvider().icon(QFileInfo(single)) if single else QIcon()
        if single is None:
            picture.setPixmap(glyphs.pixmap("float", 28, QColor(_colors().secondary)))
        else:
            picture.setPixmap(icon.pixmap(32, 32))
        name = QLabel(title)
        name.setStyleSheet(f"color: {_colors().text}; font-weight: 600;")
        detail = QLabel(subtitle)
        detail.setStyleSheet(f"color: {_colors().secondary}; font-size: 11px;")
        name.setMinimumWidth(10)
        detail.setMinimumWidth(10)
        self._name, self._detail = name, detail
        self._full_title, self._full_subtitle = title, subtitle
        text = QVBoxLayout()
        text.setSpacing(0)
        text.addWidget(name)
        text.addWidget(detail)
        self.remove = QPushButton("✕")
        self.remove.setFixedSize(22, 22)
        self.remove.setFlat(True)
        self.remove.setCursor(Qt.CursorShape.PointingHandCursor)
        self.remove.setToolTip(L("Remove from the shelf"))
        colors = _colors()
        self.remove.setStyleSheet(f"QPushButton {{ color: {colors.secondary}; border: none; }} "
                                  f"QPushButton:hover {{ color: {colors.strong}; }}")
        self.remove.setVisible(False)
        self.remove.clicked.connect(lambda: self.removed.emit(single or ""))
        layout = QHBoxLayout(self)
        layout.setContentsMargins(6, 5, 6, 5)
        layout.addWidget(picture)
        layout.addLayout(text, 1)
        layout.addWidget(self.remove)
        if single is not None and _exists(single):
            shelf.request_thumbnail(single, self)
        elif single is not None:
            detail.setText(L("Moved or deleted"))

    def set_thumbnail(self, image: QImage) -> None:
        pixmap = QPixmap.fromImage(image).scaled(_THUMB, _THUMB, Qt.AspectRatioMode.KeepAspectRatio,
                                                 Qt.TransformationMode.SmoothTransformation)
        self.picture.setPixmap(pixmap)

    def resizeEvent(self, event) -> None:  # noqa: ANN001, N802
        super().resizeEvent(event)
        room = max(40, self.width() - _THUMB - 56)
        self._name.setText(self._name.fontMetrics().elidedText(self._full_title, Qt.TextElideMode.ElideMiddle, room))
        self._detail.setText(self._detail.fontMetrics().elidedText(self._full_subtitle, Qt.TextElideMode.ElideMiddle, room)
                             if _exists(self.single or self.paths[0]) else self._detail.text())

    def enterEvent(self, event) -> None:  # noqa: ANN001, N802
        self._hover = True
        self.remove.setVisible(self.single is not None)
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:  # noqa: ANN001, N802
        self._hover = False
        self.remove.setVisible(False)
        self.update()
        super().leaveEvent(event)

    def paintEvent(self, _event) -> None:  # noqa: ANN001, N802
        if self._hover:
            painter = QPainter(self)
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(_colors().hover)
            painter.drawRoundedRect(self.rect(), 8, 8)

    def mousePressEvent(self, event) -> None:  # noqa: ANN001, N802
        if event.button() == Qt.MouseButton.LeftButton:
            self._press = event.position().toPoint()

    def mouseMoveEvent(self, event) -> None:  # noqa: ANN001, N802
        if self._press is None or not event.buttons() & Qt.MouseButton.LeftButton:
            return
        if (event.position().toPoint() - self._press).manhattanLength() < QGuiApplication.styleHints().startDragDistance():
            return
        self._press = None
        self.shelf.drag_out([p for p in self.paths if _exists(p)], self.picture.pixmap())


class FloatShelf(QWidget):
    """The shelf window. `moves_files` says whether dragging out should offer a move instead of a copy."""

    # A thumbnail made on the worker pool, delivered to the interface thread (row, image).
    _thumbnail_ready = Signal(object, object)

    def __init__(self, moves_files=lambda: False, on_dragging=None) -> None:  # noqa: ANN001
        super().__init__()
        self._thumbnail_ready.connect(self._show_thumbnail)
        self.setWindowTitle("Float")
        self.setWindowFlags(Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAcceptDrops(True)
        self.setFixedWidth(320)
        self._moves_files = moves_files
        self._on_dragging = on_dragging or (lambda _urls: None)
        self.items: list[str] = []
        self._pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix="mangosteen-thumbs")
        self._drag_offset: QPoint | None = None
        self._positioned = False

        title = QLabel("Float")
        title.setStyleSheet(f"color: {_colors().strong}; font-size: 14px; font-weight: 600;")
        self._mode = QPushButton(L("Copy"))
        self._mode.setCheckable(True)
        self._mode.setCursor(Qt.CursorShape.PointingHandCursor)
        self._mode.toggled.connect(self._mode_changed)
        self._style_mode(False)
        clear = self._header_button("⌫", L("Remove all"))
        clear.clicked.connect(self.clear)
        close = self._header_button("✕", L("Hide the shelf (it keeps its files)"))
        close.clicked.connect(self.hide)
        header = QHBoxLayout()
        header.addWidget(title, 1)
        header.addWidget(self._mode)
        header.addWidget(clear)
        header.addWidget(close)
        self._header = QWidget()
        self._header.setLayout(header)
        header.setContentsMargins(0, 0, 0, 0)
        self._empty = QLabel(L("Drop files here, or use Float on the Actions wheel."))
        self._empty.setWordWrap(True)
        self._empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._empty.setStyleSheet(f"color: {_colors().secondary}; font-size: 12px; padding: 14px 4px;")
        self._rows = QVBoxLayout()
        self._rows.setSpacing(2)
        self._rows.setContentsMargins(0, 0, 0, 0)
        holder = QWidget()
        holder.setLayout(self._rows)
        self._scroll = QScrollArea()
        self._scroll.setWidget(holder)
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        self._scroll.setMaximumHeight(420)
        self._scroll.viewport().setStyleSheet("background: transparent;")
        holder.setStyleSheet("background: transparent;")
        outer = QVBoxLayout(self)
        outer.setContentsMargins(24, 20, 24, 24)
        outer.addWidget(self._header)
        outer.addWidget(self._empty)
        outer.addWidget(self._scroll)
        self.reload()

    # MARK: Building

    def _header_button(self, text: str, tip: str) -> QPushButton:
        button = QPushButton(text)
        button.setFlat(True)
        button.setToolTip(tip)
        button.setFixedSize(26, 26)
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        button.setStyleSheet(f"QPushButton {{ color: {_colors().secondary}; border: none; font-size: 13px; }}"
                             f"QPushButton:hover {{ color: {_colors().strong}; }}")
        return button

    def _style_mode(self, moving: bool) -> None:
        background = brand.BRAND.name() if moving else _colors().line.name()
        text = "white" if moving else _colors().text
        self._mode.setStyleSheet(f"QPushButton {{ color: {text}; background: {background}; border: none;"
                                 " border-radius: 4px; padding: 2px 10px; }")
        self._mode.setText(L("Move") if moving else L("Copy"))
        self._mode.setToolTip(L("Dragging out moves the files. Click to copy them instead.") if moving
                              else L("Dragging out copies the files. Click to move them instead."))

    def _mode_changed(self, checked: bool) -> None:
        self._style_mode(checked)

    @property
    def move_mode(self) -> bool:
        return self._mode.isChecked() or bool(self._moves_files())

    def set_move_mode(self, moving: bool) -> None:
        self._mode.setChecked(moving)

    @property
    def is_settled(self) -> bool:
        """For snapshots: every thumbnail asked for has been made."""
        return all(future.done() for future in getattr(self, "_pending", []))

    def request_thumbnail(self, path: str, row: _Row) -> None:
        future = self._pool.submit(make_thumbnail, path, _THUMB * 2)
        self._pending = [f for f in getattr(self, "_pending", []) if not f.done()] + [future]

        def done(f) -> None:  # noqa: ANN001 - runs on the pool's thread, which has no event loop for timers
            image = f.result()
            if image is not None and not image.isNull():
                self._thumbnail_ready.emit(row, image)

        future.add_done_callback(done)

    def _show_thumbnail(self, row: _Row, image: QImage) -> None:
        import shiboken6

        if shiboken6.isValid(row):  # the list may have been rebuilt in the meantime
            row.set_thumbnail(image)

    def paintEvent(self, _event) -> None:  # noqa: ANN001, N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        colors = _colors()
        painter.setPen(colors.line)
        painter.setBrush(QColor(colors.panel.red(), colors.panel.green(), colors.panel.blue(), 248))
        painter.drawRoundedRect(self.rect().adjusted(10, 10, -10, -10), 12, 12)

    # MARK: Items

    def add(self, paths: list[str]) -> None:
        for path in paths:
            full = os.path.abspath(path.rstrip("/\\"))
            if full not in self.items:
                self.items.append(full)
        self.reload()
        if not self.isVisible():
            self.show_shelf()

    def toggle(self) -> None:
        if self.isVisible():
            self.hide()
        else:
            self.reload()
            self.show_shelf()

    def show_shelf(self) -> None:
        if not self._positioned:
            self._positioned = True
            area = QGuiApplication.primaryScreen().availableGeometry()
            self.adjustSize()
            self.move(area.right() - self.width() - 8, area.top() + (area.height() - self.height()) // 3)
        self.show()
        self.raise_()

    def clear(self) -> None:
        self.items.clear()
        self.reload()

    def remove(self, path: str) -> None:
        if path in self.items:
            self.items.remove(path)
        self.reload()

    def reload(self) -> None:
        while self._rows.count():
            item = self._rows.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self._empty.setVisible(not self.items)
        self._scroll.setVisible(bool(self.items))
        present = [p for p in self.items if _exists(p)]
        if len(present) > 1:
            self._add_row(present, fmt("All {0}", count(len(present), "item")), L("Drag them all at once"), None)
        for item in self.items:
            self._add_row([item], os.path.basename(item) or item, folder_label(os.path.dirname(item)), item)
        self.adjustSize()

    def _add_row(self, paths: list[str], title: str, subtitle: str, single: str | None) -> None:
        row = _Row(self, paths, title, subtitle, single)
        row.removed.connect(self.remove)
        self._rows.addWidget(row)

    # MARK: Dragging

    def drag_out(self, paths: list[str], pixmap: QPixmap | None) -> None:
        if not paths:
            return
        mime = QMimeData()
        mime.setUrls([QUrl.fromLocalFile(p) for p in paths])
        drag = QDrag(self)
        drag.setMimeData(mime)
        if pixmap is not None and not pixmap.isNull():
            drag.setPixmap(pixmap)
        self._on_dragging(paths)
        move = self.move_mode
        drag.exec(Qt.DropAction.CopyAction | Qt.DropAction.MoveAction,
                  Qt.DropAction.MoveAction if move else Qt.DropAction.CopyAction)

    def dragEnterEvent(self, event) -> None:  # noqa: ANN001, N802
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event) -> None:  # noqa: ANN001, N802
        self.add([u.toLocalFile() for u in event.mimeData().urls() if u.isLocalFile()])
        event.acceptProposedAction()

    # Moving the frameless window by its header

    def mousePressEvent(self, event) -> None:  # noqa: ANN001, N802
        if event.button() == Qt.MouseButton.LeftButton and self._header.geometry().contains(event.position().toPoint()):
            self._drag_offset = event.globalPosition().toPoint() - self.frameGeometry().topLeft()

    def mouseMoveEvent(self, event) -> None:  # noqa: ANN001, N802
        if self._drag_offset is not None and event.buttons() & Qt.MouseButton.LeftButton:
            self.move(event.globalPosition().toPoint() - self._drag_offset)

    def mouseReleaseEvent(self, _event) -> None:  # noqa: ANN001, N802
        self._drag_offset = None


__all__ = ["FloatShelf", "make_thumbnail", "QFont"]
