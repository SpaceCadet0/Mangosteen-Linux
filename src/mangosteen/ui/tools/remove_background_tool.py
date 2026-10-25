"""Remove background: finds the subject on the device and makes the rest transparent or a colour."""

from __future__ import annotations

import numpy as np
from PIL import Image
from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import (QCheckBox, QFormLayout, QHBoxLayout, QLabel, QProgressBar, QPushButton, QVBoxLayout,
                               QWidget)

from ...convert import images, qtutil
from ...core import file_format
from ...core.file_format import Category
from ...core.loc import L, fmt
from ...imaging import subject
from ..widgets import ColorButton, LiveTask, Segmented, hint_label
from . import registry
from .base import ToolWindow

_PREVIEW_SIDE = 1100


class _Preview(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self.setMinimumSize(560, 460)
        self.image = None
        self.message = "…"

    def paintEvent(self, _event) -> None:  # noqa: ANN001, N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(128, 128, 128, 36))
        painter.drawRoundedRect(self.rect(), 10, 10)
        if self.image is None:
            painter.setPen(QColor(128, 128, 128))
            painter.drawText(self.rect().adjusted(16, 16, -16, -16), int(Qt.AlignmentFlag.AlignCenter | Qt.TextFlag.TextWordWrap),
                             self.message)
            return
        area = QRectF(self.rect()).adjusted(10, 10, -10, -10)
        size = self.image.size().scaled(area.size().toSize(), Qt.AspectRatioMode.KeepAspectRatio)
        rect = QRectF(0, 0, size.width(), size.height())
        rect.moveCenter(area.center())
        # A chequerboard shows what is transparent.
        painter.save()
        painter.setClipRect(rect)
        cell = 12
        for row in range(int(rect.height() // cell) + 1):
            for column in range(int(rect.width() // cell) + 1):
                painter.setBrush(QColor(230, 230, 230) if (row + column) % 2 == 0 else QColor(200, 200, 200))
                painter.drawRect(QRectF(rect.x() + column * cell, rect.y() + row * cell, cell, cell))
        painter.restore()
        painter.drawImage(rect, self.image)


class RemoveBackgroundTool(ToolWindow):
    def __init__(self, files: list[str], context) -> None:  # noqa: ANN001
        self.images = [f for f in files if (d := file_format.detect(f)) is not None and d.is_raster_image]
        super().__init__(L("Remove background"), files, L("Remove background"), context)
        self._mask = None
        self._base: Image.Image | None = None
        self._fill: tuple[int, int, int, int] | None = None
        self._settled = False
        self._preview = _Preview()

        side = QWidget()
        side.setFixedWidth(300)
        form = QFormLayout(side)
        form.setContentsMargins(0, 0, 0, 0)
        self._kind = Segmented([(L("Transparent (PNG)"), "transparent"), (L("Colour"), "colour")])
        self._kind.changed.connect(self._kind_changed)
        form.addRow(self._kind)
        self._color = ColorButton(QColor("white"))
        self._color.changed.connect(lambda _c: self._render())
        self._color_label = QLabel(L("Colour"))
        form.addRow(self._color_label, self._color)
        self._color.setVisible(False)
        self._color_label.setVisible(False)
        self._crop = QCheckBox(L("Crop to subject"))
        self._crop.toggled.connect(lambda _on: self._render())
        form.addRow(self._crop)
        self._model_note = hint_label("")
        form.addRow(self._model_note)
        self._get_model = QPushButton(L("Download the better model (170 MB)"))
        self._get_model.clicked.connect(self._download)
        self._progress = QProgressBar()
        self._progress.setRange(0, 1000)
        self._progress.setVisible(False)
        form.addRow(self._get_model)
        form.addRow(self._progress)
        self._refresh_model_ui()

        outer = QHBoxLayout()
        outer.setSpacing(16)
        outer.addWidget(self._preview, 1)
        outer.addWidget(side, alignment=Qt.AlignmentFlag.AlignTop)
        self.set_body(layout=outer)
        self.resize(940, 580)

        self._live = LiveTask(0)
        self._live.finished.connect(self._masked)
        self._live.failed.connect(lambda m: (setattr(self._preview, "message", m), self._preview.update()))
        self._compose = LiveTask(120)
        self._compose.finished.connect(self._composed)
        self._downloader = LiveTask(0)
        self._downloader.finished.connect(self._downloaded)
        self._downloader.failed.connect(self._download_failed)
        if self.images:
            first = self.images[0]
            self._live.request(lambda c: self._detect(first), immediate=True)
            self._preview.message = L("Finding the subject…")
        else:
            self.set_action_enabled(False)

    @staticmethod
    def _detect(path: str):  # noqa: ANN205
        image, _ = images.load(path, _PREVIEW_SIDE)
        return image, subject.subject_mask(image)

    def _refresh_model_ui(self) -> None:
        if subject.has_model():
            self._model_note.setText(L("The subject is found with the IS-Net model on this computer."))
            self._get_model.setVisible(False)
        else:
            from ...core import capabilities

            self._model_note.setText(L("The built-in method is used. A neural model finds the subject more precisely; "
                                       "it is downloaded once and then works offline."))
            self._get_model.setVisible(capabilities.has_onnxruntime())

    def _kind_changed(self, kind: str) -> None:
        colour = kind == "colour"
        self._color.setVisible(colour)
        self._color_label.setVisible(colour)
        self._render()

    def _download(self) -> None:
        self._get_model.setEnabled(False)
        self._progress.setVisible(True)
        self._downloader.request(lambda c: subject.download_model(lambda f: self._progress.setValue(int(f * 1000))),
                                 immediate=True)

    def _downloaded(self, _path) -> None:  # noqa: ANN001
        self._progress.setVisible(False)
        self._refresh_model_ui()
        if self.images:
            first = self.images[0]
            self._live.request(lambda c: self._detect(first), immediate=True)

    def _download_failed(self, message: str) -> None:
        self._progress.setVisible(False)
        self._get_model.setEnabled(True)
        self._model_note.setText(message)

    def _masked(self, result) -> None:  # noqa: ANN001
        self._base, self._mask = result
        if not subject.has_subject(self._mask):
            self._preview.message = fmt("No subject was found in “{0}” to separate from the background.",
                                        self.windowTitle().split(" — ")[-1])
            self._preview.image = None
            self._preview.update()
            self._settled = True
            return
        self._render()

    def _fill_value(self) -> tuple[int, int, int, int] | None:
        if self._kind.value == "transparent":
            return None
        c = self._color.color
        return (c.red(), c.green(), c.blue(), 255)

    def _render(self) -> None:
        if self._base is None or self._mask is None or not subject.has_subject(self._mask):
            return
        base, mask, fill, crop = self._base, self._mask, self._fill_value(), self._crop.isChecked()

        def compose(cancelled):  # noqa: ANN001, ANN202
            cutout = subject.cut(base, mask)
            if crop:
                box = subject.bounds(mask)
                if box is not None:
                    cutout = cutout.crop(box.as_box())
            return subject.on_color(cutout, fill) if fill is not None else cutout

        self._compose.request(compose)

    def _composed(self, image) -> None:  # noqa: ANN001
        self._preview.image = qtutil.pil_to_qimage(image)
        self._preview.update()
        self._settled = True

    @property
    def is_settled(self) -> bool:
        return self._settled or not self.images

    def run(self) -> None:
        fill, crop, options = self._fill_value(), self._crop.isChecked(), self.settings.conversion_options
        self.jobs.run_each(L("Removing the background"), L("Background removed"), self.images,
                           lambda path, _t, _p: subject.remove_file(path, fill, crop, options))
        self.close()


@registry.register("tool.removeBackground")
def create(files: list[str], context) -> RemoveBackgroundTool:  # noqa: ANN001
    return RemoveBackgroundTool(files, context)


__all__ = ["RemoveBackgroundTool", "np", "QVBoxLayout"]
