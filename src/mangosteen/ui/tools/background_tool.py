"""Background: puts a photo on a colour, gradient, image or blurred copy of itself, with margin, rounded corners and
a shadow."""

from __future__ import annotations

import os
from dataclasses import replace

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (QCheckBox, QComboBox, QFileDialog, QFormLayout, QHBoxLayout, QPushButton, QStackedWidget,
                               QVBoxLayout, QWidget)

from ...convert import images, qtutil
from ...core import file_format
from ...core.file_format import Category
from ...core.loc import L
from ...imaging import compose
from ...imaging.compose import CanvasAspect, FrameBackground, FrameSettings, RGBA
from ..widgets import ColorButton, LabeledSlider, LiveTask, PreviewPane, Segmented
from . import registry
from .base import ToolWindow


def _pct(v: float) -> str:
    return f"{round(v * 100)}%"


class BackgroundTool(ToolWindow):
    def __init__(self, files: list[str], context) -> None:  # noqa: ANN001
        self.images = [f for f in files if (d := file_format.detect(f)) is not None and d.category is Category.IMAGE]
        super().__init__(L("Background"), files, L("Save"), context)
        self._settings = FrameSettings()
        self._photo = None
        self._backdrop = None
        self._settled = False
        self._preview = PreviewPane(560, 480)
        self._preview.set_message("…")
        outer = QHBoxLayout()
        outer.setSpacing(16)
        outer.addWidget(self._preview, alignment=Qt.AlignmentFlag.AlignTop)
        outer.addWidget(self._controls(), alignment=Qt.AlignmentFlag.AlignTop)
        self.set_body(layout=outer)
        self._loader = LiveTask(0)
        self._loader.finished.connect(self._loaded)
        self._live = LiveTask(120)
        self._live.finished.connect(self._rendered)
        if self.images:
            first = self.images[0]
            self._loader.request(lambda c: images.load(first, 1200)[0], immediate=True)
        else:
            self.set_action_enabled(False)

    def _controls(self) -> QWidget:
        holder = QWidget()
        holder.setFixedWidth(340)
        form = QFormLayout(holder)
        form.setContentsMargins(0, 0, 0, 0)
        self._kind = QComboBox()
        for kind, title in ((FrameBackground.COLOR, L("Colour")), (FrameBackground.GRADIENT, L("Gradient")),
                            (FrameBackground.IMAGE, L("Image")), (FrameBackground.BLUR, L("Source image"))):
            self._kind.addItem(title, kind)
        self._kind.setCurrentIndex(1)
        self._kind.currentIndexChanged.connect(self._kind_changed)
        form.addRow(L("Background"), self._kind)

        self._stack = QStackedWidget()
        # Colour
        color_page = QWidget()
        color_form = QFormLayout(color_page)
        color_form.setContentsMargins(0, 0, 0, 0)
        self._color = ColorButton(self._settings.color.to_qcolor())
        self._color.changed.connect(lambda c: self._set(color=RGBA.from_qcolor(c)))
        color_form.addRow(L("Colour"), self._color)
        self._stack.addWidget(color_page)
        # Gradient
        gradient_page = QWidget()
        gradient_form = QFormLayout(gradient_page)
        gradient_form.setContentsMargins(0, 0, 0, 0)
        self._from = ColorButton(self._settings.gradient_start.to_qcolor())
        self._from.changed.connect(lambda c: self._set(gradient_start=RGBA.from_qcolor(c)))
        self._to = ColorButton(self._settings.gradient_end.to_qcolor())
        self._to.changed.connect(lambda c: self._set(gradient_end=RGBA.from_qcolor(c)))
        self._angle = LabeledSlider(0, 360, 135, 135, lambda v: f"{v:.0f}°")
        self._angle.value_changed.connect(lambda v: self._set(gradient_angle=v))
        gradient_form.addRow(L("From"), self._from)
        gradient_form.addRow(L("To"), self._to)
        gradient_form.addRow(L("Angle"), self._angle)
        self._stack.addWidget(gradient_page)
        # Image
        image_page = QWidget()
        image_form = QFormLayout(image_page)
        image_form.setContentsMargins(0, 0, 0, 0)
        self._choose = QPushButton(L("Choose…"))
        self._choose.clicked.connect(self._choose_background)
        image_form.addRow(L("Image"), self._choose)
        self._stack.addWidget(image_page)
        # Source image (blur only)
        self._stack.addWidget(QWidget())
        form.addRow(self._stack)
        self._stack.setCurrentIndex(1)

        self._blur = LabeledSlider(0, 1, 0.5, 0.5, _pct)
        self._blur.value_changed.connect(lambda v: self._set(blur=v))
        self._blur_label = L("Blur")
        form.addRow(self._blur_label, self._blur)
        self._blur_row = (form.labelForField(self._blur), self._blur)
        self._set_blur_visible(False)

        self._aspect = QComboBox()
        for aspect in CanvasAspect:
            self._aspect.addItem(L("Same as original") if aspect is CanvasAspect.AUTO else aspect.title, aspect)
        self._aspect.currentIndexChanged.connect(lambda: self._set(aspect=self._aspect.currentData()))
        form.addRow(L("Proportions"), self._aspect)
        self._padding = LabeledSlider(0, 0.4, 0.08, 0.08, lambda v: _pct(v / 0.4))
        self._padding.value_changed.connect(lambda v: self._set(padding=v))
        form.addRow(L("Margin"), self._padding)
        self._corners = LabeledSlider(0, 0.5, 0.03, 0.03, lambda v: _pct(v / 0.5))
        self._corners.value_changed.connect(lambda v: self._set(corner_radius=v))
        form.addRow(L("Corners"), self._corners)
        self._circle = QCheckBox(L("Circle"))
        self._circle.setToolTip(L("Crop the photo to a centred square and make it round"))
        self._circle.toggled.connect(self._circle_toggled)
        form.addRow(self._circle)
        self._shadow = LabeledSlider(0, 1, 0.5, 0.5, _pct)
        self._shadow.value_changed.connect(lambda v: self._set(shadow=v))
        form.addRow(L("Shadow"), self._shadow)
        return holder

    def _set_blur_visible(self, visible: bool) -> None:
        for widget in self._blur_row:
            if widget is not None:
                widget.setVisible(visible)

    def _kind_changed(self) -> None:
        kind = self._kind.currentData()
        self._stack.setCurrentIndex({FrameBackground.COLOR: 0, FrameBackground.GRADIENT: 1, FrameBackground.IMAGE: 2,
                                     FrameBackground.BLUR: 3}[kind])
        self._set_blur_visible(kind in (FrameBackground.IMAGE, FrameBackground.BLUR))
        self._set(background=kind)

    def _circle_toggled(self, on: bool) -> None:
        self._corners.setEnabled(not on)
        self._set(circle=on)

    def _choose_background(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, L("Image"))
        if path:
            self._backdrop = images.load(path, 1600)[0]
            self._choose.setText(os.path.basename(path))
            self._set(background_image=path)

    def _set(self, **changes) -> None:  # noqa: ANN003
        self._settings = replace(self._settings, **changes)
        self._render()

    def _loaded(self, photo) -> None:  # noqa: ANN001
        self._photo = photo
        self._render()

    def _render(self) -> None:
        if self._photo is None:
            return
        photo, settings, backdrop = self._photo, self._settings, self._backdrop
        self._live.request(lambda cancelled: compose.compose_frame(photo, settings, backdrop))

    def _rendered(self, image) -> None:  # noqa: ANN001
        self._preview.set_message("")
        self._preview.set_image(qtutil.pil_to_qimage(image))
        self._settled = True

    @property
    def is_settled(self) -> bool:
        return self._settled or not self.images

    def run(self) -> None:
        settings, options = self._settings, self.settings.conversion_options
        self.jobs.run_each(L("Adding background"), L("Background added"), self.images,
                           lambda path, _t, _p: compose.frame_file(path, settings, options))
        self.close()


@registry.register("tool.frame")
def create(files: list[str], context) -> BackgroundTool:  # noqa: ANN001
    return BackgroundTool(files, context)


__all__ = ["BackgroundTool", "Segmented", "QCheckBox", "QVBoxLayout", "QColor"]
