"""Crop: drag the frame or its handles, pick an aspect ratio, or enter exact output pixels; turn and mirror the
picture, and cut the result into a grid of parts. The Size tab scales whole pictures instead: by pixels, percent or
the long side, one rule for every file."""

from __future__ import annotations

import os

from PySide6.QtCore import Qt
from PySide6.QtGui import QImage
from PySide6.QtWidgets import (QCheckBox, QComboBox, QHBoxLayout, QLabel, QMenu, QPushButton, QSpinBox, QStackedWidget,
                               QToolButton, QVBoxLayout, QWidget)

from ...convert import images, qtutil
from ...core import file_format
from ...core.file_format import Category
from ...core.loc import L, fmt
from ...imaging import cropper, geometry as g
from ...imaging.geometry import ImageTransform, ResizeRule, UnitRect
from .. import glyphs
from ..widgets import LiveTask, Segmented
from . import registry
from .base import ToolWindow
from .crop_canvas import CropCanvas

_ASPECTS = [("free", "Free", None), ("original", "Same as original", None), ("1:1", "1:1", 1.0), ("4:3", "4:3", 4 / 3),
            ("3:2", "3:2", 3 / 2), ("16:9", "16:9", 16 / 9), ("9:16", "9:16", 9 / 16), ("3:4", "3:4", 3 / 4),
            ("2:3", "2:3", 2 / 3), ("4:5", "4:5", 4 / 5), ("exact", "Exact size…", None)]


class CropTool(ToolWindow):
    def __init__(self, files: list[str], context) -> None:  # noqa: ANN001
        self.images = [f for f in files if (d := file_format.detect(f)) is not None and d.category is Category.IMAGE]
        super().__init__(L("Crop"), files, L("Save"), context)
        self._source: QImage | None = None
        self._source_size = (1, 1)
        self._display: QImage | None = None
        self._image_size = (1, 1)
        self._transform = ImageTransform()
        self._columns = 1
        self._rows = 1
        self._rule = ResizeRule("percent", 100)
        self._keep_aspect = True
        self._loaded = False

        self._mode = Segmented([(L("Crop|tab"), "crop"), (L("Size"), "size")], context.settings.crop_tab)
        self._mode.setFixedWidth(240)
        self._mode.changed.connect(self._mode_changed)
        self._canvas = CropCanvas()
        self._canvas.rect_changed.connect(lambda _r: self._update_labels())
        self._canvas.cuts_changed.connect(self._update_action)
        self._size_preview = _SizePreview()
        self._stack = QStackedWidget()
        self._stack.addWidget(self._canvas)
        self._stack.addWidget(self._size_preview)
        self._stack.setMinimumSize(620, 420)

        layout = QVBoxLayout()
        layout.setSpacing(12)
        layout.addWidget(self._mode, alignment=Qt.AlignmentFlag.AlignHCenter)
        layout.addWidget(self._stack, 1)
        layout.addWidget(self._crop_controls())
        layout.addWidget(self._size_controls())
        layout.addLayout(self._transform_row())
        self.set_body(layout=layout)
        self._mode_changed(self._mode.value, save=False)

        self._live = LiveTask(0)
        self._live.finished.connect(self._loaded_image)
        self._live.failed.connect(lambda m: (self._canvas.set_image(None, m), self._size_preview.set_message(m)))
        first = self.images[0] if self.images else None
        if first:
            self._live.request(lambda cancelled: (images.load(first, 1800)[0], _upright_size(first)), immediate=True)
        else:
            self._canvas.set_image(None, L("No image chosen"))
            self.set_action_enabled(False)

    # MARK: Controls

    def _crop_controls(self) -> QWidget:
        self._crop_box = QWidget()
        row = QHBoxLayout(self._crop_box)
        row.setContentsMargins(0, 0, 0, 0)
        self._aspect = QComboBox()
        for key, title, _ in _ASPECTS:
            self._aspect.addItem(L(title), key)
        self._aspect.currentIndexChanged.connect(self._aspect_changed)
        self._exact_width = QSpinBox()
        self._exact_width.setRange(1, 20000)
        self._exact_width.setValue(1080)
        self._exact_height = QSpinBox()
        self._exact_height.setRange(1, 20000)
        self._exact_height.setValue(1080)
        for box in (self._exact_width, self._exact_height):
            box.valueChanged.connect(self._aspect_changed)
        self._exact_widgets = [self._exact_width, QLabel("×"), self._exact_height, QLabel("px")]
        row.addWidget(QLabel(L("Proportions")))
        row.addWidget(self._aspect)
        for widget in self._exact_widgets:
            row.addWidget(widget)
            widget.setVisible(False)
        row.addStretch(1)
        self._pixels = QLabel("")
        self._pixels.setStyleSheet("color: gray;")
        row.addWidget(self._pixels)
        reset = QPushButton(L("Reset"))
        reset.clicked.connect(self._reset_crop)
        row.addWidget(reset)
        return self._crop_box

    def _size_controls(self) -> QWidget:
        self._size_box = QWidget()
        column = QVBoxLayout(self._size_box)
        column.setContentsMargins(0, 0, 0, 0)
        row = QHBoxLayout()
        self._width = QSpinBox()
        self._width.setRange(1, g.MAX_SIDE)
        self._height = QSpinBox()
        self._height.setRange(1, g.MAX_SIDE)
        self._width.valueChanged.connect(lambda v: self._size_edited("width", v))
        self._height.valueChanged.connect(lambda v: self._size_edited("height", v))
        self._lock = QToolButton()
        self._lock.setCheckable(True)
        self._lock.setChecked(True)
        self._lock.setToolTip(L("Keep proportions"))
        self._lock.toggled.connect(self._lock_toggled)
        self._lock.setText("🔒")
        row.addWidget(QLabel(L("Width")))
        row.addWidget(self._width)
        row.addWidget(self._lock)
        row.addWidget(QLabel(L("Height")))
        row.addWidget(self._height)
        row.addWidget(QLabel("px"))
        row.addStretch(1)
        for percent in g.PERCENTS:
            button = QPushButton(f"{percent}%")
            button.clicked.connect(lambda _c=False, p=percent: self._set_rule(ResizeRule("percent", p)))
            row.addWidget(button)
        menu = QMenu(self)
        for side in g.LONG_SIDES:
            menu.addAction(f"{side} px").triggered.connect(lambda _c=False, s=side: self._set_rule(ResizeRule("long_side", s)))
        long_side = QPushButton(L("Longer side"))
        long_side.setMenu(menu)
        row.addWidget(long_side)
        reset = QPushButton(L("Reset"))
        reset.clicked.connect(self._reset_size)
        row.addWidget(reset)
        column.addLayout(row)
        self._batch = QLabel("")
        self._batch.setStyleSheet("color: gray;")
        self._batch.setVisible(len(self.images) > 1)
        column.addWidget(self._batch)
        return self._size_box

    def _transform_row(self) -> QHBoxLayout:
        row = QHBoxLayout()
        for glyph, tip, action in (
                ("rotateLeft", L("Rotate left"), lambda: self._transform_to(self._transform.rotate(False))),
                ("rotateRight", L("Rotate right"), lambda: self._transform_to(self._transform.rotate(True))),
                ("flipH", L("Flip horizontally"), lambda: self._transform_to(self._transform.flip(True))),
                ("flipV", L("Flip vertically"), lambda: self._transform_to(self._transform.flip(False)))):
            button = QToolButton()
            button.setIcon(glyphs.icon(glyph, 18))
            button.setToolTip(tip)
            button.clicked.connect(lambda _c=False, a=action: a())
            row.addWidget(button)
        row.addStretch(1)
        self._split_label = QLabel(L("Split into parts:"))
        self._columns_box = QSpinBox()
        self._columns_box.setRange(1, 10)
        self._columns_box.setPrefix("↔ ")
        self._rows_box = QSpinBox()
        self._rows_box.setRange(1, 10)
        self._rows_box.setPrefix("↕ ")
        self._columns_box.valueChanged.connect(self._columns_changed)
        self._rows_box.valueChanged.connect(self._rows_changed)
        self._split_widgets = [self._split_label, self._columns_box, self._rows_box]
        for widget in self._split_widgets:
            row.addWidget(widget)
        return row

    # MARK: Mode

    def _mode_changed(self, mode: str, save: bool = True) -> None:
        crop = mode == "crop"
        self._stack.setCurrentIndex(0 if crop else 1)
        self._crop_box.setVisible(crop)
        self._size_box.setVisible(not crop)
        for widget in self._split_widgets:
            widget.setVisible(crop)
        if save:
            self.settings.crop_tab = mode
            self.settings.save()
        self._update_action()
        self._update_labels()

    @property
    def _crop_mode(self) -> bool:
        return self._mode.value == "crop"

    def _update_action(self) -> None:
        if not self._crop_mode:
            self.action_title = L("Resize")
        elif self._canvas.column_cuts or self._canvas.row_cuts:
            self.action_title = L("Split")
        else:
            self.action_title = L("Save")

    # MARK: Loading and display

    def _loaded_image(self, result) -> None:  # noqa: ANN001
        image, size = result
        self._source = qtutil.pil_to_qimage(image)
        self._source_size = size
        self._loaded = True
        self._update_display()

    @property
    def is_settled(self) -> bool:
        return self._loaded or not self.images

    def _update_display(self) -> None:
        if self._source is None:
            return
        # Turning is done on the preview image; the file itself is turned when saved.
        from PIL import Image

        preview = qtutil_to_pil(self._source)
        turned = self._transform.apply(preview)
        self._display = qtutil.pil_to_qimage(turned)
        self._image_size = self._transform.size(*self._source_size)
        self._canvas.set_image(self._display)
        self._size_preview.set_image(self._display)
        self._canvas.set_rect(g.FULL)
        self._apply_aspect()
        self._update_labels()

    def _transform_to(self, transform: ImageTransform) -> None:
        self._transform = transform
        self._update_display()

    # MARK: Crop frame

    def _pixel_aspect(self, size: tuple[int, int]) -> float | None:
        key = self._aspect.currentData()
        if key == "free":
            return None
        if key == "original":
            return size[0] / size[1]
        if key == "exact":
            return max(self._exact_width.value(), 1) / max(self._exact_height.value(), 1)
        return next(ratio for k, _t, ratio in _ASPECTS if k == key)

    def _apply_aspect(self) -> None:
        aspect = self._pixel_aspect(self._image_size)
        for widget in self._exact_widgets:
            widget.setVisible(self._aspect.currentData() == "exact" and self._crop_mode)
        self._canvas.set_aspect(aspect * self._image_size[1] / self._image_size[0] if aspect else None)
        if aspect:
            self._canvas.set_rect(g.centered_rect(aspect, *self._image_size))
        self._update_labels()

    def _aspect_changed(self) -> None:
        self._apply_aspect()

    def _reset_crop(self) -> None:
        self._aspect.setCurrentIndex(0)
        self._transform = ImageTransform()
        self._columns_box.setValue(1)
        self._rows_box.setValue(1)
        self._canvas.set_cuts([], [])
        self._update_display()

    def _columns_changed(self, value: int) -> None:
        self._columns = value
        self._canvas.set_cuts(g.even_cuts(value), self._canvas.row_cuts)
        self._update_action()

    def _rows_changed(self, value: int) -> None:
        self._rows = value
        self._canvas.set_cuts(self._canvas.column_cuts, g.even_cuts(value))
        self._update_action()

    def _update_labels(self) -> None:
        width, height = self._image_size
        area = self._canvas.unit_rect.to_pixels(width, height)
        self._pixels.setText(f"{area.width} × {area.height} px")
        result = self._rule.apply(width, height)
        self._size_preview.set_sizes((width, height), result)
        for box, value in ((self._width, result[0]), (self._height, result[1])):
            blocked = box.blockSignals(True)
            box.setValue(value)
            box.blockSignals(blocked)
        self._batch.setText(self._batch_note())

    # MARK: Size

    def _set_rule(self, rule: ResizeRule) -> None:
        self._rule = rule
        self._update_labels()

    def _size_edited(self, which: str, value: int) -> None:
        if not self._loaded:
            return
        value = min(max(value, 1), g.MAX_SIDE)
        current = self._rule.apply(*self._image_size)
        if which == "width":
            self._rule = ResizeRule("width", value) if self._keep_aspect else ResizeRule("exact", value, current[1])
        else:
            self._rule = ResizeRule("height", value) if self._keep_aspect else ResizeRule("exact", current[0], value)
        self._update_labels()

    def _lock_toggled(self, on: bool) -> None:
        self._keep_aspect = on
        self._lock.setText("🔒" if on else "🔓")
        if on and self._loaded:
            self._rule = ResizeRule("width", self._rule.apply(*self._image_size)[0])
            self._update_labels()

    def _reset_size(self) -> None:
        self._rule = ResizeRule("percent", 100)
        self._lock.setChecked(True)
        self._transform = ImageTransform()
        self._update_display()

    def _batch_note(self) -> str:
        rule = self._rule
        if rule.kind == "percent":
            return fmt("All files: {0}% of their size", int(rule.value))
        if rule.kind == "long_side":
            return fmt("All files: long side {0} px", int(rule.value))
        if rule.kind == "width":
            return fmt("All files: {0} px wide, height to scale", int(rule.value))
        if rule.kind == "height":
            return fmt("All files: {0} px high, width to scale", int(rule.value))
        return fmt("All files: {0} × {1} px", int(rule.value), rule.height)

    # MARK: Work

    def run(self) -> None:
        if not self.images:
            return
        options = self.settings.conversion_options
        transform = self._transform
        if not self._crop_mode:
            rule = self._rule
            self.jobs.run_each(L("Resizing"), L("Resized"), self.images,
                               lambda path, _t, _p: cropper.resize_file(path, rule, transform, options))
            self.close()
            return
        first = self.images[0]
        first_rect = self._canvas.unit_rect
        key = self._aspect.currentData()
        exact = (self._exact_width.value(), self._exact_height.value())
        output_size = exact if key == "exact" else None
        column_cuts, row_cuts = list(self._canvas.column_cuts), list(self._canvas.row_cuts)

        def work(path: str, _token, _progress) -> str:  # noqa: ANN001
            rect = first_rect
            if path != first and key != "free":
                size = transform.size(*_upright_size(path))
                if key == "original":
                    aspect = size[0] / size[1]
                elif key == "exact":
                    aspect = exact[0] / max(exact[1], 1)
                else:
                    aspect = next(r for k, _t, r in _ASPECTS if k == key) or size[0] / size[1]
                rect = g.centered_rect(aspect, *size)
            return cropper.crop_file(path, rect, output_size, transform, column_cuts, row_cuts, options)

        self.jobs.run_each(L("Cropping"), L("Cropped"), self.images, work)
        self.close()


class _SizePreview(QWidget):
    """The picture with the old and new size in the corner."""

    def __init__(self) -> None:
        super().__init__()
        self._image: QImage | None = None
        self._text = ""
        self._message = ""

    def set_image(self, image: QImage | None) -> None:
        self._image = image
        self.update()

    def set_message(self, text: str) -> None:
        self._message = text
        self.update()

    def set_sizes(self, before: tuple[int, int], after: tuple[int, int]) -> None:
        self._text = f"{before[0]} × {before[1]} → {after[0]} × {after[1]} px"
        self.update()

    def paintEvent(self, _event) -> None:  # noqa: ANN001, N802
        from PySide6.QtCore import QRectF
        from PySide6.QtGui import QColor, QPainter

        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(128, 128, 128, 36))
        painter.drawRoundedRect(self.rect(), 10, 10)
        if self._image is not None and not self._image.isNull():
            area = QRectF(self.rect()).adjusted(16, 16, -16, -16)
            size = self._image.size().scaled(area.size().toSize(), Qt.AspectRatioMode.KeepAspectRatio)
            target = QRectF(0, 0, size.width(), size.height())
            target.moveCenter(area.center())
            painter.drawImage(target, self._image)
            metrics = painter.fontMetrics()
            width = metrics.horizontalAdvance(self._text) + 16
            badge = QRectF(self.width() - width - 10, self.height() - 34, width, 24)
            painter.setBrush(QColor(0, 0, 0, 150))
            painter.drawRoundedRect(badge, 6, 6)
            painter.setPen(QColor("white"))
            painter.drawText(badge, int(Qt.AlignmentFlag.AlignCenter), self._text)
        elif self._message:
            painter.setPen(QColor(128, 128, 128))
            painter.drawText(self.rect(), int(Qt.AlignmentFlag.AlignCenter), self._message)


def _upright_size(path: str) -> tuple[int, int]:
    """Pixel size of the image as displayed (EXIF orientation applied)."""
    from PIL import Image, ImageOps

    if file_format.detect(path) is not file_format.FileFormat.SVG:
        try:
            images.register_plugins()
            with Image.open(path) as image:
                width, height = image.size
                orientation = image.getexif().get(0x0112, 1)
                return (height, width) if orientation >= 5 else (width, height)
        except (OSError, ValueError):
            pass
    loaded, _ = images.load(path)
    return loaded.size


def qtutil_to_pil(qimage: QImage):  # noqa: ANN201
    from PIL import Image

    converted = qimage.convertToFormat(QImage.Format.Format_RGBA8888)
    return Image.frombuffer("RGBA", (converted.width(), converted.height()), bytes(converted.constBits()), "raw", "RGBA",
                            converted.bytesPerLine(), 1).copy()


@registry.register("tool.crop")
def create(files: list[str], context) -> CropTool:  # noqa: ANN001
    return CropTool(files, context)


__all__ = ["CropTool", "os"]
