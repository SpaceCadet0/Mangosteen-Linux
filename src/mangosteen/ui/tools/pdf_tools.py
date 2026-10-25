"""PDF windows: Split (scissors between pages, leave out pages you don't need) and Page order (reorder, rotate,
duplicate and delete pages)."""

from __future__ import annotations

import os
from dataclasses import replace

from PySide6.QtCore import QPointF, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QIcon, QImage, QKeySequence, QPainter, QPen, QPixmap, QShortcut, QTransform
from PySide6.QtWidgets import (QAbstractItemView, QHBoxLayout, QLabel, QListWidget, QListWidgetItem, QPushButton,
                               QScrollArea, QSpinBox, QToolButton, QVBoxLayout, QWidget)

from ...convert import pdf as pdf_engine
from ...convert import qtutil
from ...core import file_format
from ...core.file_format import FileFormat
from ...core.loc import L, count, fmt
from .. import brand, glyphs
from ..widgets import LiveTask, hint_label
from . import registry
from .base import ToolWindow

_CARD = QSize(112, 150)
_GAP = 26


class PageGrid(QWidget):
    """Page thumbnails in rows, with a cut marker after each page; click a page to leave it out."""

    changed = Signal()

    def __init__(self) -> None:
        super().__init__()
        self.setMouseTracking(True)
        self.thumbs: list[QPixmap | None] = []
        self.cuts: set[int] = set()
        self.excluded: set[int] = set()
        self._hover: tuple[str, int] | None = None

    def set_count(self, count_: int) -> None:
        self.thumbs = [None] * count_
        self.cuts.clear()
        self.excluded.clear()
        self._relayout()
        self.update()

    def set_thumb(self, index: int, image: QImage) -> None:
        if 0 <= index < len(self.thumbs):
            self.thumbs[index] = QPixmap.fromImage(image)
            self.update()

    def _columns(self) -> int:
        return max(1, (self.width() - 12) // (_CARD.width() + _GAP))

    def _relayout(self) -> None:
        columns = self._columns()
        rows = -(-len(self.thumbs) // columns) if self.thumbs else 1
        self.setMinimumHeight(rows * (_CARD.height() + 34) + 20)

    def resizeEvent(self, event) -> None:  # noqa: ANN001, N802
        super().resizeEvent(event)
        self._relayout()

    def _card_rect(self, index: int) -> QRectF:
        columns = self._columns()
        row, column = divmod(index, columns)
        x = 12 + column * (_CARD.width() + _GAP)
        y = 12 + row * (_CARD.height() + 34)
        return QRectF(x, y, _CARD.width(), _CARD.height())

    def _marker_rect(self, index: int) -> QRectF:
        card = self._card_rect(index)
        return QRectF(card.right(), card.top(), _GAP, card.height())

    def _hit(self, point: QPointF) -> tuple[str, int] | None:
        for index in range(len(self.thumbs)):
            if index < len(self.thumbs) - 1 and self._marker_rect(index).contains(point):
                return ("cut", index)
            if self._card_rect(index).contains(point):
                return ("page", index)
        return None

    def mouseMoveEvent(self, event) -> None:  # noqa: ANN001, N802
        hit = self._hit(event.position())
        if hit != self._hover:
            self._hover = hit
            self.setCursor(Qt.CursorShape.PointingHandCursor if hit else Qt.CursorShape.ArrowCursor)
            self.update()

    def leaveEvent(self, _event) -> None:  # noqa: ANN001, N802
        self._hover = None
        self.update()

    def mousePressEvent(self, event) -> None:  # noqa: ANN001, N802
        hit = self._hit(event.position())
        if hit is None or event.button() != Qt.MouseButton.LeftButton:
            return
        kind, index = hit
        target = self.cuts if kind == "cut" else self.excluded
        target.symmetric_difference_update({index})
        self.changed.emit()
        self.update()

    def paintEvent(self, _event) -> None:  # noqa: ANN001, N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        text_color = brand.text_color()
        for index, thumb in enumerate(self.thumbs):
            card = self._card_rect(index)
            excluded = index in self.excluded
            painter.setOpacity(0.35 if excluded else 1.0)
            painter.setPen(QPen(QColor(128, 128, 128, 120), 1))
            painter.setBrush(QColor("white"))
            painter.drawRoundedRect(card, 6, 6)
            if thumb is not None:
                target = QRectF(0, 0, 0, 0)
                size = thumb.size().scaled(int(card.width() - 8), int(card.height() - 8), Qt.AspectRatioMode.KeepAspectRatio)
                target.setSize(QSize(size.width(), size.height()).toSizeF() if hasattr(QSize, "toSizeF") else
                               QRectF(0, 0, size.width(), size.height()).size())
                target.moveCenter(card.center())
                painter.drawPixmap(target, thumb, QRectF(thumb.rect()))
            painter.setOpacity(1.0)
            painter.setPen(text_color)
            painter.drawText(QRectF(card.left(), card.bottom() + 2, card.width(), 20), int(Qt.AlignmentFlag.AlignCenter),
                             str(index + 1))
            if excluded:
                painter.setPen(QPen(QColor(220, 50, 50), 3, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
                painter.drawLine(card.topLeft() + QPointF(14, 14), card.bottomRight() - QPointF(14, 14))
                painter.drawLine(card.topRight() + QPointF(-14, 14), card.bottomLeft() + QPointF(14, -14))
            if self._hover == ("page", index) and not excluded:
                painter.setPen(QPen(brand.accent(), 2))
                painter.setBrush(Qt.BrushStyle.NoBrush)
                painter.drawRoundedRect(card, 6, 6)
            if index < len(self.thumbs) - 1:
                marker = self._marker_rect(index)
                cut = index in self.cuts
                hover = self._hover == ("cut", index)
                x = marker.center().x()
                painter.setPen(QPen(QColor(255, 180, 0) if cut else QColor(128, 128, 128, 110 if hover else 40),
                                    2.5 if cut else 1.5, Qt.PenStyle.DashLine))
                painter.drawLine(QPointF(x, marker.top() + 4), QPointF(x, marker.bottom() - 4))
                if cut or hover:
                    glyphs.draw(painter, "split", QRectF(x - 9, marker.center().y() - 9, 18, 18),
                                QColor(255, 180, 0) if cut else QColor(128, 128, 128), 1.8)


class PdfSplitTool(ToolWindow):
    def __init__(self, files: list[str], context) -> None:  # noqa: ANN001
        self.pdfs = [f for f in files if file_format.detect(f) is FileFormat.PDF]
        super().__init__(L("Split PDF"), files, L("Split"), context)
        self._pages = 0
        self._error = ""
        self._grid = PageGrid()
        self._grid.changed.connect(self._update)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(self._grid)
        scroll.setMinimumSize(640, 420)
        self._summary = QLabel("")
        self._summary.setWordWrap(True)

        presets = QHBoxLayout()
        presets.addWidget(QLabel(L("Split into parts:")))
        for title, handler in ((L("Every page"), lambda: self._set_cuts(pdf_engine.cuts_every_page)),
                               (L("In half"), lambda: self._set_cuts(pdf_engine.cuts_in_half))):
            button = QPushButton(title)
            button.clicked.connect(handler)
            presets.addWidget(button)
        presets.addWidget(QLabel(L("Every N pages:")))
        self._n = QSpinBox()
        self._n.setRange(1, 999)
        self._n.setValue(2)
        presets.addWidget(self._n)
        every = QPushButton(L("Split"))
        every.clicked.connect(lambda: self._set_cuts(lambda n: pdf_engine.cuts_every_n(n, self._n.value())))
        presets.addWidget(every)
        presets.addStretch(1)
        clear = QPushButton(L("Reset"))
        clear.clicked.connect(self._reset)
        presets.addWidget(clear)

        layout = QVBoxLayout()
        layout.setSpacing(10)
        layout.addWidget(hint_label(L("Click between two pages to cut there; click a page to leave it out. The original "
                                      "is not changed.")))
        layout.addLayout(presets)
        layout.addWidget(scroll, 1)
        layout.addWidget(self._summary)
        self.set_body(layout=layout)
        self.resize(780, 620)
        self.set_action_enabled(False)
        self._loader = LiveTask(0)
        self._loader.finished.connect(self._loaded)
        self._loader.failed.connect(self._failed)
        self._settled = False
        if self.pdfs:
            first = self.pdfs[0]
            self._loader.request(lambda c: pdf_engine.thumbnails(first, 200, None), immediate=True)
        self._summary.setText("…")

    def _loaded(self, thumbs) -> None:  # noqa: ANN001
        self._pages = len(thumbs)
        self._grid.set_count(self._pages)
        for index, image in enumerate(thumbs):
            self._grid.set_thumb(index, qtutil.pil_to_qimage(image))
        self._settled = True
        self._update()

    def _failed(self, message: str) -> None:
        self._error = message
        self._summary.setText(message)

    @property
    def is_settled(self) -> bool:
        return self._settled or bool(self._error)

    def _set_cuts(self, make) -> None:  # noqa: ANN001
        self._grid.cuts = set(make(self._pages))
        self._grid.update()
        self._update()

    def _reset(self) -> None:
        self._grid.cuts.clear()
        self._grid.excluded.clear()
        self._grid.update()
        self._update()

    def _update(self) -> None:
        groups = pdf_engine.split_documents(self._pages, self._grid.cuts, self._grid.excluded)
        if not groups:
            self._summary.setText(L("No pages left."))
            self.set_action_enabled(False)
            return
        self.set_action_enabled(True)
        if len(groups) == 1 and not self._grid.cuts:
            self._summary.setText(count(len(groups[0]), "page"))
        else:
            self._summary.setText(f"{count(len(groups), 'part')}: " + " · ".join(pdf_engine.ranges(g) for g in groups))

    def run(self) -> None:
        path, cuts, excluded = self.pdfs[0], set(self._grid.cuts), set(self._grid.excluded)
        self.jobs.run_each(L("Splitting"), L("Pages saved"), [path],
                           lambda p, _t, _pr: pdf_engine.split(p, cuts, excluded))
        self.close()


class PdfPagesTool(ToolWindow):
    def __init__(self, files: list[str], context) -> None:  # noqa: ANN001
        self.pdfs = [f for f in files if file_format.detect(f) is FileFormat.PDF]
        super().__init__(L("Page order"), files, L("Save"), context)
        self._items: list[pdf_engine.PageItem] = []
        self._thumbs: dict[tuple[int, int], QImage] = {}
        self._settled = False
        self._list = QListWidget()
        self._list.setViewMode(QListWidget.ViewMode.IconMode)
        self._list.setIconSize(QSize(120, 160))
        self._list.setGridSize(QSize(140, 200))
        self._list.setResizeMode(QListWidget.ResizeMode.Adjust)
        self._list.setMovement(QListWidget.Movement.Snap)
        self._list.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self._list.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self._list.setMinimumSize(660, 420)
        self._list.setWordWrap(True)
        row = QHBoxLayout()
        for glyph, tip, handler in (("rotateLeft", L("Rotate left"), lambda: self._rotate(-90)),
                                    ("rotateRight", L("Rotate right"), lambda: self._rotate(90))):
            button = QToolButton()
            button.setIcon(glyphs.icon(glyph, 18))
            button.setToolTip(tip)
            button.clicked.connect(lambda _c=False, h=handler: h())
            row.addWidget(button)
        duplicate = QPushButton(L("Duplicate"))
        duplicate.clicked.connect(self._duplicate)
        delete = QPushButton(L("Delete"))
        delete.clicked.connect(self._delete)
        row.addWidget(duplicate)
        row.addWidget(delete)
        row.addStretch(1)
        layout = QVBoxLayout()
        layout.addWidget(hint_label(L("Drag pages to reorder; Ctrl or Shift selects several.")))
        layout.addLayout(row)
        layout.addWidget(self._list, 1)
        self.set_body(layout=layout)
        self.resize(780, 620)
        QShortcut(QKeySequence("Delete"), self._list, self._delete)
        self.set_action_enabled(False)
        self._loader = LiveTask(0)
        self._loader.finished.connect(self._loaded)
        self._loader.failed.connect(lambda m: self.set_status(m))
        if self.pdfs:
            paths = list(self.pdfs)

            def load(cancelled):  # noqa: ANN001, ANN202
                items = pdf_engine.page_items(paths)
                thumbs = {}
                for index, path in enumerate(paths):
                    for page, image in enumerate(pdf_engine.thumbnails(path, 220)):
                        thumbs[(index, page)] = image
                return items, thumbs

            self._loader.request(load, immediate=True)

    def _loaded(self, result) -> None:  # noqa: ANN001
        items, thumbs = result
        self._thumbs = {key: qtutil.pil_to_qimage(image) for key, image in thumbs.items()}
        for item in items:
            self._add(item)
        self._settled = True
        self.set_action_enabled(self._list.count() > 0)

    @property
    def is_settled(self) -> bool:
        return self._settled

    def _icon(self, item: pdf_engine.PageItem) -> QIcon:
        image = self._thumbs.get((item.document, item.page))
        if image is None:
            return QIcon()
        pixmap = QPixmap.fromImage(image)
        if item.rotation % 360:
            pixmap = pixmap.transformed(QTransform().rotate(item.rotation % 360), Qt.TransformationMode.SmoothTransformation)
        return QIcon(pixmap)

    def _add(self, item: pdf_engine.PageItem, row: int | None = None) -> None:
        widget_item = QListWidgetItem(self._icon(item), "")
        widget_item.setData(Qt.ItemDataRole.UserRole, item)
        widget_item.setToolTip(os.path.basename(self.pdfs[item.document]) + f" · {item.page + 1}")
        if row is None:
            self._list.addItem(widget_item)
        else:
            self._list.insertItem(row, widget_item)
        self._renumber()

    def _renumber(self) -> None:
        for index in range(self._list.count()):
            item = self._list.item(index)
            page: pdf_engine.PageItem = item.data(Qt.ItemDataRole.UserRole)
            item.setText(str(index + 1))
            item.setTextAlignment(Qt.AlignmentFlag.AlignHCenter)

    def _rotate(self, degrees: int) -> None:
        for widget_item in self._list.selectedItems():
            page: pdf_engine.PageItem = widget_item.data(Qt.ItemDataRole.UserRole)
            updated = replace(page, rotation=(page.rotation + degrees) % 360)
            widget_item.setData(Qt.ItemDataRole.UserRole, updated)
            widget_item.setIcon(self._icon(updated))

    def _duplicate(self) -> None:
        for widget_item in sorted(self._list.selectedItems(), key=self._list.row, reverse=True):
            page = widget_item.data(Qt.ItemDataRole.UserRole)
            self._add(replace(page), self._list.row(widget_item) + 1)

    def _delete(self) -> None:
        for widget_item in self._list.selectedItems():
            self._list.takeItem(self._list.row(widget_item))
        self._renumber()
        self.set_action_enabled(self._list.count() > 0)

    def run(self) -> None:
        items = [self._list.item(i).data(Qt.ItemDataRole.UserRole) for i in range(self._list.count())]
        paths = list(self.pdfs)
        self.jobs.run_once(L("Saving pages"), L("Pages saved"), count(len(items), "page"),
                           lambda: pdf_engine.save_organized(items, paths, paths[0]))
        self.close()


@registry.register("tool.splitPDF")
def create_split(files: list[str], context) -> PdfSplitTool:  # noqa: ANN001
    return PdfSplitTool(files, context)


@registry.register("tool.organizePDF")
def create_pages(files: list[str], context) -> PdfPagesTool:  # noqa: ANN001
    return PdfPagesTool(files, context)


__all__ = ["PdfSplitTool", "PdfPagesTool", "PageGrid"]
