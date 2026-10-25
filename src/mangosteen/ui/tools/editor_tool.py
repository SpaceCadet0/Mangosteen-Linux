"""Photo editor: light, colour, detail and effects with a live preview; hold the preview to compare with the original,
double-click a slider to reset it."""

from __future__ import annotations

import os
from dataclasses import replace

from PIL import Image
from PySide6.QtCore import Qt
from PySide6.QtGui import QImage
from PySide6.QtWidgets import (QComboBox, QFormLayout, QGroupBox, QHBoxLayout, QLabel, QPushButton, QScrollArea,
                               QVBoxLayout, QWidget)

from ...convert import images, qtutil
from ...core import file_format
from ...core.file_format import Category
from ...core.loc import L
from ...imaging import adjust, cropper
from ...imaging.adjust import PhotoAdjustments, PhotoEffect
from ..widgets import LabeledSlider, LiveTask, hint_label
from . import registry
from .base import ToolWindow

_PREVIEW_SIDE = 1100

# (attribute, title, minimum, maximum, format)
_LIGHT = [("exposure", "Exposure", -2, 2, "{:+.1f}"), ("brightness", "Brightness", -1, 1, "{:+.0%}"),
          ("contrast", "Contrast", -1, 1, "{:+.0%}"), ("highlights", "Highlights", -1, 1, "{:+.0%}"),
          ("shadows", "Shadows", -1, 1, "{:+.0%}")]
_COLOUR = [("temperature", "Temperature", -1, 1, "{:+.0%}"), ("tint", "Tint", -1, 1, "{:+.0%}"),
           ("saturation", "Saturation", -1, 1, "{:+.0%}"), ("vibrance", "Vibrance", -1, 1, "{:+.0%}")]
_DETAIL = [("sharpness", "Sharpness", 0, 1, "{:.0%}"), ("clarity", "Clarity", 0, 1, "{:.0%}"),
           ("noise_reduction", "Noise reduction", 0, 1, "{:.0%}"), ("dehaze", "Dehaze", 0, 1, "{:.0%}")]
_EFFECTS = [("vignette", "Vignette", 0, 1, "{:.0%}"), ("grain", "Grain", 0, 1, "{:.0%}")]

_FILTERS = [(PhotoEffect.NONE, "None"), (PhotoEffect.MONO, "Mono"), (PhotoEffect.NOIR, "Noir"),
            (PhotoEffect.TONAL, "Tonal"), (PhotoEffect.CHROME, "Chrome"), (PhotoEffect.FADE, "Fade"),
            (PhotoEffect.INSTANT, "Instant"), (PhotoEffect.PROCESS, "Process"), (PhotoEffect.TRANSFER, "Transfer")]


class _Compare(QWidget):
    """The preview: shows the original while the mouse button is held."""

    def __init__(self) -> None:
        super().__init__()
        self.setMinimumSize(520, 420)
        self.setToolTip(L("Hold to see the original"))
        self.original: QImage | None = None
        self.edited: QImage | None = None
        self.showing_original = False
        self.busy = False

    def mousePressEvent(self, _event) -> None:  # noqa: ANN001, N802
        self.showing_original = True
        self.update()

    def mouseReleaseEvent(self, _event) -> None:  # noqa: ANN001, N802
        self.showing_original = False
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
        image = self.original if self.showing_original else (self.edited or self.original)
        if image is not None and not image.isNull():
            area = QRectF(self.rect()).adjusted(8, 8, -8, -8)
            size = image.size().scaled(area.size().toSize(), Qt.AspectRatioMode.KeepAspectRatio)
            target = QRectF(0, 0, size.width(), size.height())
            target.moveCenter(area.center())
            painter.drawImage(target, image)
        if self.showing_original:
            painter.setBrush(QColor(0, 0, 0, 150))
            painter.drawRoundedRect(QRectF(12, 12, 96, 24), 6, 6)
            painter.setPen(QColor("white"))
            painter.drawText(QRectF(12, 12, 96, 24), int(Qt.AlignmentFlag.AlignCenter), L("Original"))


class EditorTool(ToolWindow):
    def __init__(self, files: list[str], context) -> None:  # noqa: ANN001
        self.images = [f for f in files if (d := file_format.detect(f)) is not None and d.category is Category.IMAGE]
        super().__init__(L("Photo editor"), files, L("Save"), context)
        self._adjust = PhotoAdjustments()
        self._sliders: dict[str, LabeledSlider] = {}
        self._base: Image.Image | None = None
        self._full_width = 1
        self._settled = False

        self._preview = _Compare()
        left = QVBoxLayout()
        left.addWidget(self._preview, 1)
        left.addWidget(hint_label(L("Hold to see the original")))
        if len(self.images) > 1:
            left.addWidget(hint_label(L("The same adjustments are applied to every image.")))

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        scroll.setFixedWidth(360)
        holder = QWidget()
        column = QVBoxLayout(holder)
        column.setContentsMargins(0, 0, 8, 0)
        for title, rows in ((L("Light"), _LIGHT), (L("Colour"), _COLOUR), (L("Detail"), _DETAIL)):
            column.addWidget(self._group(title, rows))
        effects = QGroupBox(L("Effects"))
        form = QFormLayout(effects)
        self._filter = QComboBox()
        for effect, name in _FILTERS:
            self._filter.addItem(L(name), effect)
        self._filter.currentIndexChanged.connect(lambda: self._set(effect=self._filter.currentData()))
        form.addRow(L("Filter"), self._filter)
        for attribute, title, low, high, pattern in _EFFECTS:
            form.addRow(L(title), self._slider(attribute, low, high, pattern))
        column.addWidget(effects)
        reset = QPushButton(L("Reset all"))
        reset.clicked.connect(self._reset_all)
        column.addWidget(reset, alignment=Qt.AlignmentFlag.AlignRight)
        column.addStretch(1)
        scroll.setWidget(holder)

        outer = QHBoxLayout()
        outer.setSpacing(16)
        outer.addLayout(left, 1)
        outer.addWidget(scroll)
        self.set_body(layout=outer)
        self.resize(940, 640)

        self._live = LiveTask(60)
        self._live.finished.connect(self._edited)
        self._loader = LiveTask(0)
        self._loader.finished.connect(self._loaded)
        first = self.images[0] if self.images else None
        if first:
            self._loader.request(lambda c: self._load_preview(first), immediate=True)
        else:
            self.set_action_enabled(False)

    @staticmethod
    def _load_preview(path: str):  # noqa: ANN205
        image, _ = images.load(path, _PREVIEW_SIDE)
        full = _full_width(path)
        return image, full

    def _group(self, title: str, rows: list) -> QGroupBox:  # noqa: ANN001
        box = QGroupBox(title)
        form = QFormLayout(box)
        for attribute, name, low, high, pattern in rows:
            form.addRow(L(name), self._slider(attribute, low, high, pattern))
        return box

    def _slider(self, attribute: str, low: float, high: float, pattern: str) -> LabeledSlider:
        slider = LabeledSlider(low, high, 0.0, 0.0, lambda v, p=pattern: p.format(v))
        slider.value_changed.connect(lambda v, a=attribute: self._set(**{a: v}))
        self._sliders[attribute] = slider
        return slider

    def _set(self, **changes) -> None:  # noqa: ANN003
        self._adjust = replace(self._adjust, **changes)
        self._render()

    def _reset_all(self) -> None:
        self._adjust = PhotoAdjustments()
        for slider in self._sliders.values():
            slider.set_value(0.0)
        self._filter.setCurrentIndex(0)
        self._render()

    def _loaded(self, result) -> None:  # noqa: ANN001
        image, full = result
        self._base = image
        self._full_width = full
        self._preview.original = qtutil.pil_to_qimage(image)
        self._preview.edited = None
        self._preview.update()
        self._settled = True
        self._render()

    def _render(self) -> None:
        if self._base is None:
            return
        base, adjustments = self._base, self._adjust
        scale = base.width / max(self._full_width, 1)
        if adjustments.is_identity:
            self._preview.edited = None
            self._preview.update()
            return
        self._live.request(lambda cancelled: adjust.apply(base, adjustments, scale, cancelled))

    def _edited(self, image: Image.Image) -> None:
        self._preview.edited = qtutil.pil_to_qimage(image)
        self._preview.update()

    @property
    def is_settled(self) -> bool:
        return self._settled or not self.images

    def run(self) -> None:
        adjustments, options = self._adjust, self.settings.conversion_options
        if adjustments.is_identity:
            self.context.notify(L("Editor"), L("Nothing was changed."))
            return
        self.jobs.run_each(L("Editing"), L("Edited"), self.images,
                           lambda path, _t, _p: cropper.edit_file(path, adjustments, options))
        self.close()


def _full_width(path: str) -> int:
    from .crop_tool import _upright_size

    return _upright_size(path)[0]


@registry.register("tool.edit")
def create(files: list[str], context) -> EditorTool:  # noqa: ANN001
    return EditorTool(files, context)


__all__ = ["EditorTool", "os", "QLabel"]
