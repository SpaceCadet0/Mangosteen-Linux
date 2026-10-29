"""Collage: arrange several images in a grid, row, column or featured layout."""

from __future__ import annotations

import os
from dataclasses import replace

from PySide6.QtCore import QPointF, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QIcon, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (QAbstractItemView, QApplication, QComboBox, QFormLayout, QHBoxLayout, QLabel,
                               QListWidget, QListWidgetItem, QSpinBox, QVBoxLayout, QWidget)

from ...convert import images, qtutil
from ...core import file_format
from ...core.file_format import Category, FileFormat
from ...core.loc import L, count
from ...imaging import compose
from ...imaging.compose import CanvasAspect, CollageBackground, CollageLayout, CollageSettings, RGBA
from ..widgets import ColorButton, LabeledSlider, LiveTask, PreviewPane
from . import registry
from .base import ToolWindow

_WIDTHS = [1080, 1600, 2048, 3000, 4096, 6000]
_FORMATS = [FileFormat.JPG, FileFormat.PNG, FileFormat.HEIC, FileFormat.WEBP]
_PREVIEW_WIDTH = 1000  # the preview is rendered at this width; spacing and corners are relative, so it looks the same
_DRAG_THUMB = 72
_BRAND = QColor("#671E38")


def _pct(v: float) -> str:
    return f"{round(v * 100)}%"


class CollagePreview(PreviewPane):
    """The preview, where a photo can be picked up and dropped on the place of another one."""

    moved = Signal(int, int)  # from cell, to cell (indices into the order the preview was rendered with)

    def __init__(self, width: int, height: int) -> None:
        super().__init__(width, height)
        self.setMouseTracking(True)
        self._cells: list[tuple[float, float, float, float]] = []
        self._canvas = QSize()
        self._thumbs: list[QPixmap | None] = []
        self._pressed: int | None = None
        self._press_at = QPointF()
        self._dragging = False
        self._target: int | None = None
        self._pointer = QPointF()

    def set_layout(self, canvas: QSize, cells: list, thumbs: list[QPixmap | None]) -> None:
        """Where each photo is on the rendered collage (in its pixels), and its small picture for the pointer."""
        self._canvas, self._cells, self._thumbs = canvas, list(cells), list(thumbs)
        self.update()

    def _image_rect(self) -> QRectF:
        if self._canvas.isEmpty():
            return QRectF()
        area = QRectF(self.rect()).adjusted(6, 6, -6, -6)
        scaled = self._canvas.scaled(area.size().toSize(), Qt.AspectRatioMode.KeepAspectRatio)
        target = QRectF(0, 0, scaled.width(), scaled.height())
        target.moveCenter(area.center())
        return target

    def cell_rect(self, index: int) -> QRectF:
        image = self._image_rect()
        scale = image.width() / self._canvas.width() if self._canvas.width() else 0
        x, y, w, h = self._cells[index]
        return QRectF(image.x() + x * scale, image.y() + y * scale, w * scale, h * scale)

    def cell_at(self, point: QPointF) -> int | None:
        for index in range(len(self._cells)):
            if self.cell_rect(index).contains(point):
                return index
        return None

    def mousePressEvent(self, event) -> None:  # noqa: ANN001, N802
        if event.button() == Qt.MouseButton.LeftButton and len(self._cells) > 1:
            self._pressed = self.cell_at(event.position())
            self._press_at = event.position()

    def mouseMoveEvent(self, event) -> None:  # noqa: ANN001, N802
        if self._pressed is None:
            over = self.cell_at(event.position()) is not None and len(self._cells) > 1
            self.setCursor(Qt.CursorShape.OpenHandCursor if over else Qt.CursorShape.ArrowCursor)
            return
        if not self._dragging and (event.position() - self._press_at).manhattanLength() < QApplication.startDragDistance():
            return
        self._dragging = True
        self.setCursor(Qt.CursorShape.ClosedHandCursor)
        self._pointer = event.position()
        target = self.cell_at(event.position())
        self._target = target if target != self._pressed else None
        self.update()

    def mouseReleaseEvent(self, event) -> None:  # noqa: ANN001, N802
        source, target, dragging = self._pressed, self._target, self._dragging
        self._pressed, self._target, self._dragging = None, None, False
        self.setCursor(Qt.CursorShape.ArrowCursor)
        self.update()
        if dragging and source is not None and target is not None:
            self.moved.emit(source, target)

    def paintEvent(self, event) -> None:  # noqa: ANN001, N802
        super().paintEvent(event)
        if not self._dragging or self._pressed is None or self._pressed >= len(self._cells):
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        painter.fillRect(self.cell_rect(self._pressed), QColor(0, 0, 0, 110))  # the photo being moved
        if self._target is not None:
            pen = QPen(_BRAND, 3)
            pen.setJoinStyle(Qt.PenJoinStyle.MiterJoin)
            painter.setPen(pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRect(self.cell_rect(self._target).adjusted(1.5, 1.5, -1.5, -1.5))
        thumb = self._thumbs[self._pressed] if self._pressed < len(self._thumbs) else None
        if thumb is not None and not thumb.isNull():
            size = thumb.deviceIndependentSize().scaled(QSize(_DRAG_THUMB, _DRAG_THUMB).toSizeF(),
                                                        Qt.AspectRatioMode.KeepAspectRatio)
            box = QRectF(0, 0, size.width(), size.height())
            box.moveCenter(self._pointer)
            painter.setOpacity(0.9)
            painter.drawPixmap(box, thumb, QRectF(thumb.rect()))
            painter.setOpacity(1)
            painter.setPen(QPen(QColor(255, 255, 255, 220), 1.5))
            painter.drawRect(box)


class CollageTool(ToolWindow):
    def __init__(self, files: list[str], context) -> None:  # noqa: ANN001
        self.order = [f for f in files if (d := file_format.detect(f)) is not None and d.category is Category.IMAGE]
        super().__init__(L("Collage"), files, L("Create"), context)
        self._settings = CollageSettings()
        self._thumbs: dict[str, object] = {}
        self._pointer_thumbs: dict[str, QPixmap] = {}
        self._icons: dict[str, QIcon] = {}
        self._rendered_order: list[str] = []
        self._settled = False
        self._preview = CollagePreview(560, 520)
        self._preview.set_message("…")
        self._preview.moved.connect(self._moved_in_preview)
        right = QVBoxLayout()
        right.addWidget(self._controls())
        caption = QLabel(L("Order — drag the rows or the photos in the preview"))
        caption.setWordWrap(True)
        caption.setStyleSheet("color: gray; font-size: 11px;")
        right.addSpacing(4)
        right.addWidget(caption)
        self._list = QListWidget()
        self._list.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self._list.setIconSize(QSize(32, 32))
        self._list.setMinimumHeight(110)
        self._list.model().rowsMoved.connect(self._reordered)
        right.addWidget(self._list, 1)
        outer = QHBoxLayout()
        outer.setSpacing(16)
        outer.addWidget(self._preview, alignment=Qt.AlignmentFlag.AlignTop)
        wrapper = QWidget()
        wrapper.setFixedWidth(340)
        wrapper.setLayout(right)
        outer.addWidget(wrapper)
        self.set_body(layout=outer)
        self.set_action_enabled(len(self.order) >= 2)
        self._fill_list()
        self._live = LiveTask(150)
        self._live.finished.connect(self._rendered)
        self._loader = LiveTask(0)
        self._loader.finished.connect(self._loaded)
        order = list(self.order)
        self._loader.request(lambda c: {p: images.load(p, 700)[0] for p in order}, immediate=True)

    def _controls(self) -> QWidget:
        holder = QWidget()
        form = QFormLayout(holder)
        form.setContentsMargins(0, 0, 0, 0)
        self._form = form
        self._layout = QComboBox()
        for layout, title in ((CollageLayout.GRID, L("Grid")), (CollageLayout.ROW, L("Row")),
                              (CollageLayout.COLUMN, L("Column")), (CollageLayout.FEATURED, L("Featured photo"))):
            self._layout.addItem(title, layout)
        self._layout.currentIndexChanged.connect(self._layout_changed)
        form.addRow(L("Layout"), self._layout)
        self._columns = QSpinBox()
        self._columns.setRange(0, max(len(self.order), 1))
        self._columns.setSpecialValueText(L("Auto"))
        self._columns.valueChanged.connect(lambda v: self._set(columns=v))
        form.addRow(L("Columns"), self._columns)
        self._aspect = QComboBox()
        for aspect in CanvasAspect:
            self._aspect.addItem(aspect.title, aspect)
        self._aspect.currentIndexChanged.connect(lambda: self._set(aspect=self._aspect.currentData()))
        form.addRow(L("Proportions"), self._aspect)
        self._width = QComboBox()
        for width in _WIDTHS:
            self._width.addItem(f"{width} px", width)
        self._width.setCurrentIndex(_WIDTHS.index(3000))
        self._width.currentIndexChanged.connect(lambda: self._set(width=self._width.currentData()))
        form.addRow(L("Width"), self._width)
        self._spacing = LabeledSlider(0, 0.06, 0.015, 0.015, lambda v: f"{round(v / 0.06 * 100)}%")
        self._spacing.value_changed.connect(lambda v: self._set(spacing=v))
        form.addRow(L("Spacing"), self._spacing)
        self._corners = LabeledSlider(0, 0.25, 0.0, 0.0, lambda v: f"{round(v / 0.25 * 100)}%")
        self._corners.value_changed.connect(lambda v: self._set(corner_radius=v))
        form.addRow(L("Corners"), self._corners)
        self._shadow = LabeledSlider(0, 1, 0.0, 0.0, _pct)
        self._shadow.value_changed.connect(lambda v: self._set(shadow=v))
        form.addRow(L("Shadow"), self._shadow)
        self._style = QComboBox()
        self._style.addItem(L("Colour"), CollageBackground.COLOR)
        self._style.addItem(L("Gradient"), CollageBackground.GRADIENT)
        self._style.currentIndexChanged.connect(self._style_changed)
        form.addRow(L("Background"), self._style)
        self._background = ColorButton(self._settings.background.to_qcolor())
        self._background.changed.connect(lambda c: self._set(background=RGBA.from_qcolor(c)))
        form.addRow(L("Colour"), self._background)
        self._start = ColorButton(self._settings.gradient_start.to_qcolor())
        self._start.changed.connect(lambda c: self._set(gradient_start=RGBA.from_qcolor(c)))
        form.addRow(L("Start"), self._start)
        self._end = ColorButton(self._settings.gradient_end.to_qcolor())
        self._end.changed.connect(lambda c: self._set(gradient_end=RGBA.from_qcolor(c)))
        form.addRow(L("End"), self._end)
        self._angle = LabeledSlider(0, 360, 135, 135, lambda v: f"{v:.0f}°")
        self._angle.value_changed.connect(lambda v: self._set(gradient_angle=v))
        form.addRow(L("Angle"), self._angle)
        self._format = QComboBox()
        for f in _FORMATS:
            self._format.addItem(f.display_name, f)
        self._format.currentIndexChanged.connect(lambda: self._set(format=self._format.currentData()))
        form.addRow(L("Format"), self._format)
        self._show_style_rows(CollageBackground.COLOR)
        return holder

    def _show_style_rows(self, style: CollageBackground) -> None:
        gradient = style is CollageBackground.GRADIENT
        self._form.setRowVisible(self._background, not gradient)
        for widget in (self._start, self._end, self._angle):
            self._form.setRowVisible(widget, gradient)

    def _style_changed(self) -> None:
        style = self._style.currentData()
        self._show_style_rows(style)
        self._set(background_style=style)

    def _layout_changed(self) -> None:
        layout = self._layout.currentData()
        self._form.setRowVisible(self._columns, layout is CollageLayout.GRID)
        self._set(layout=layout)

    def _set(self, **changes) -> None:  # noqa: ANN003
        self._settings = replace(self._settings, **changes)
        self._render()

    # MARK: Order

    def _fill_list(self) -> None:
        self._list.clear()
        for path in self.order:
            item = QListWidgetItem(os.path.basename(path), self._list)
            item.setData(Qt.ItemDataRole.UserRole, path)
            if path in self._icons:
                item.setIcon(self._icons[path])

    def _reordered(self, *_args) -> None:  # noqa: ANN002
        self.order = [self._list.item(i).data(Qt.ItemDataRole.UserRole) for i in range(self._list.count())]
        self._render()

    def _moved_in_preview(self, source: int, target: int) -> None:
        """The photo goes to the target's place and the ones between move along, as rows do in the list."""
        if not (0 <= source < len(self._rendered_order) and 0 <= target < len(self._rendered_order)):
            return
        moving, onto = self._rendered_order[source], self._rendered_order[target]
        self.move_photo(self.order.index(moving), self.order.index(onto))

    def move_photo(self, source: int, target: int) -> None:
        path = self.order.pop(source)
        self.order.insert(target, path)
        self._fill_list()
        self._render()

    # MARK: Rendering

    def _loaded(self, thumbs) -> None:  # noqa: ANN001
        self._thumbs = thumbs
        for path, thumb in thumbs.items():
            if thumb is None:
                continue
            small = thumb.copy()
            small.thumbnail((64, 64))
            self._icons[path] = QIcon(QPixmap.fromImage(qtutil.pil_to_qimage(small)))
            ratio = self.devicePixelRatioF()
            pointer = thumb.copy()
            pointer.thumbnail((round(_DRAG_THUMB * ratio), round(_DRAG_THUMB * ratio)))
            pixmap = QPixmap.fromImage(qtutil.pil_to_qimage(pointer))
            pixmap.setDevicePixelRatio(ratio)
            self._pointer_thumbs[path] = pixmap
        self._fill_list()
        self._render()

    def _render(self) -> None:
        order = list(self.order)
        photos = [self._thumbs.get(p) for p in order]
        if not photos or any(p is None for p in photos):
            return
        preview = replace(self._settings, width=_PREVIEW_WIDTH)

        def work(_cancelled):  # noqa: ANN001, ANN202
            aspects = [p.width / max(p.height, 1) for p in photos]
            return order, compose.collage_layout(aspects, preview)[2], compose.compose_collage(photos, preview)

        self._live.request(work)

    def _rendered(self, result) -> None:  # noqa: ANN001
        order, cells, image = result
        self._rendered_order = order
        self._preview.set_message("")
        self._preview.set_image(qtutil.pil_to_qimage(image))
        self._preview.set_layout(QSize(image.width, image.height), cells,
                                 [self._pointer_thumbs.get(p) for p in order])
        self._settled = True

    @property
    def is_settled(self) -> bool:
        return self._settled

    def run(self) -> None:
        settings, options, order = self._settings, self.settings.conversion_options, list(self.order)
        self.jobs.run_once(L("Making a collage"), L("Collage created"), count(len(order), "photo"),
                           lambda: compose.collage_files(order, settings, options))
        self.close()


@registry.register("tool.collage")
def create(files: list[str], context) -> CollageTool:  # noqa: ANN001
    return CollageTool(files, context)


__all__ = ["CollagePreview", "CollageTool"]
