"""Compress: preset, quality or target size, optional resize and format, with a live estimate on the first image."""

from __future__ import annotations

import os
from dataclasses import replace

from PySide6.QtCore import Qt
from PySide6.QtGui import QImage
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDoubleSpinBox, QFormLayout, QHBoxLayout, QLabel, QRadioButton,
                               QSpinBox, QStackedWidget, QVBoxLayout, QWidget)

from ...core import file_format
from ...core.file_format import Category, FileFormat
from ...core.loc import L, fmt
from ...imaging import compress as engine
from ...imaging.compress import CompressionSettings, Mode, Preset
from ...imaging.geometry import MAX_SIDE
from ..widgets import LabeledSlider, LiveTask, PreviewPane, Segmented, hint_label
from . import registry
from .base import ToolWindow

_CUSTOM = -1


class CompressTool(ToolWindow):
    def __init__(self, files: list[str], context) -> None:  # noqa: ANN001
        self.images = [f for f in files if (d := file_format.detect(f)) is not None and d.category is Category.IMAGE]
        self.pdfs = [f for f in files if file_format.detect(f) is FileFormat.PDF]
        super().__init__(L("Compress"), files, L("Compress"), context)
        self._settings = CompressionSettings(preserve_metadata=context.settings.preserve_metadata)
        self._unit = 1_000_000
        self._estimating = False
        self._live = LiveTask(250)
        self._live.finished.connect(self._estimated)
        self._live.failed.connect(self._failed)
        self._live.started.connect(lambda: self._preview.set_busy(True))

        outer = QHBoxLayout()
        outer.setSpacing(16)
        if self.images:
            left = QVBoxLayout()
            self._preview = PreviewPane(340, 260)
            self._name = QLabel(os.path.basename(self.images[0]))
            self._name.setStyleSheet("color: gray; font-size: 11px;")
            self._estimate = QLabel("")
            self._estimate.setWordWrap(True)
            left.addWidget(self._preview)
            left.addWidget(self._name)
            left.addWidget(self._estimate)
            left.addStretch(1)
            outer.addLayout(left)
        else:
            self._preview = PreviewPane(1, 1)
            self._estimate = QLabel()
        outer.addWidget(self._controls())
        self.set_body(layout=outer)
        self.set_action_enabled(bool(self.images or self.pdfs))
        self._changed()

    # MARK: Controls

    def _controls(self) -> QWidget:
        holder = QWidget()
        holder.setFixedWidth(400)
        form = QFormLayout(holder)
        form.setContentsMargins(0, 0, 0, 0)
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.ExpandingFieldsGrow)
        self._mode = Segmented([(L("Preset"), Mode.PRESET), (L("Quality"), Mode.QUALITY), (L("File size"), Mode.TARGET_SIZE)])
        self._mode.changed.connect(self._mode_changed)
        form.addRow(self._mode)

        self._stack = QStackedWidget()
        preset_box = QWidget()
        preset_layout = QVBoxLayout(preset_box)
        preset_layout.setContentsMargins(0, 0, 0, 0)
        self._preset_buttons: dict[Preset, QRadioButton] = {}
        for preset in Preset:
            button = QRadioButton(preset.title)
            button.setChecked(preset is Preset.BALANCED)
            button.toggled.connect(lambda on, p=preset: on and self._set(preset=p))
            self._preset_buttons[preset] = button
            preset_layout.addWidget(button)
            detail = QLabel(preset.detail)
            detail.setStyleSheet("color: gray; font-size: 11px; margin-left: 22px;")
            preset_layout.addWidget(detail)
        self._stack.addWidget(preset_box)

        self._quality = LabeledSlider(0.05, 1.0, 0.7, 0.7, lambda v: f"{round(v * 100)}%")
        self._quality.value_changed.connect(lambda v: self._set(quality=v))
        quality_box = QWidget()
        QVBoxLayout(quality_box).addWidget(self._quality)
        quality_box.layout().setContentsMargins(0, 0, 0, 0)
        self._stack.addWidget(quality_box)

        self._target_value = QDoubleSpinBox()
        self._target_value.setRange(0.001, 100000)
        self._target_value.setDecimals(2)
        self._target_value.setValue(1.0)
        self._target_value.valueChanged.connect(self._target_changed)
        self._target_unit = QComboBox()
        self._target_unit.addItem(L("KB"), 1_000)
        self._target_unit.addItem(L("MB"), 1_000_000)
        self._target_unit.setCurrentIndex(1)
        self._target_unit.currentIndexChanged.connect(self._target_changed)
        target_box = QWidget()
        target_row = QHBoxLayout(target_box)
        target_row.setContentsMargins(0, 0, 0, 0)
        target_row.addWidget(QLabel(L("At most")))
        target_row.addWidget(self._target_value)
        target_row.addWidget(self._target_unit)
        target_row.addStretch(1)
        self._stack.addWidget(target_box)
        form.addRow(self._stack)

        self._side = QComboBox()
        self._side.addItem(L("Unchanged"), None)
        for side in engine.SIZE_LIMITS:
            self._side.addItem(f"{side} px", side)
        self._side.addItem(L("Custom…"), _CUSTOM)
        self._side.currentIndexChanged.connect(self._side_changed)
        form.addRow(L("Longer side"), self._side)
        self._custom = QSpinBox()
        self._custom.setRange(16, MAX_SIDE)
        self._custom.setValue(1600)
        self._custom.setSuffix(" px")
        self._custom.valueChanged.connect(self._side_changed)
        self._custom_label = QLabel(L("Custom…"))
        form.addRow(self._custom_label, self._custom)
        self._custom.setVisible(False)
        self._custom_label.setVisible(False)

        self._format = QComboBox()
        self._format.addItem(L("Same as original"), None)
        for f in engine.selectable_formats():
            self._format.addItem(f.display_name, f)
        self._format.currentIndexChanged.connect(lambda: self._set(format=self._format.currentData()))
        form.addRow(L("Format"), self._format)
        self._metadata = QCheckBox(L("Keep metadata"))
        self._metadata.setChecked(self._settings.preserve_metadata)
        self._metadata.toggled.connect(lambda on: self._set(preserve_metadata=on))
        form.addRow(self._metadata)
        if self.pdfs:
            form.addRow(hint_label(L("Pictures in PDF files are re-encoded as JPEG at screen resolution.")))
        if any((d := file_format.detect(f)) is not None and not d.is_lossy for f in self.images):
            self._lossless_note = hint_label(fmt("PNG, TIFF and other lossless formats are saved as {0}.",
                                                 engine.default_lossy_format().display_name))
            form.addRow(self._lossless_note)
        return holder

    # MARK: State

    def _set(self, **changes) -> None:  # noqa: ANN003
        self._settings = replace(self._settings, **changes)
        self._changed()

    def _mode_changed(self, mode: Mode) -> None:
        self._stack.setCurrentIndex({Mode.PRESET: 0, Mode.QUALITY: 1, Mode.TARGET_SIZE: 2}[mode])
        self._set(mode=mode)

    def _target_changed(self) -> None:
        self._set(target_bytes=int(max(self._target_value.value(), 0.001) * self._target_unit.currentData()))

    def _side_changed(self) -> None:
        choice = self._side.currentData()
        custom = choice == _CUSTOM
        self._custom.setVisible(custom)
        self._custom_label.setVisible(custom)
        self._set(max_pixel_size=self._custom.value() if custom else choice)

    def _changed(self) -> None:
        if not self.images:
            return
        settings = self._settings
        first = self.images[0]
        self._estimate.setText(L("Estimating…"))
        self._live.request(lambda cancelled: engine.compress(first, settings))

    def _estimated(self, result) -> None:  # noqa: ANN001
        data, format_ = result
        self._preview.set_busy(False)
        image = QImage.fromData(data)
        self._preview.set_image(image)
        original = os.path.getsize(self.images[0])
        change = round((len(data) / original - 1) * 100) if original else 0
        sign = "+" if change > 0 else "−"
        self._estimate.setText(f"{engine.human_size(original)} → {engine.human_size(len(data))} "
                               f"{format_.display_name} ({sign}{abs(change)}%)")
        self._done = True

    def _failed(self, message: str) -> None:
        self._preview.set_busy(False)
        self._estimate.setText(message)

    @property
    def is_settled(self) -> bool:
        return getattr(self, "_done", False) or not self.images

    def run(self) -> None:
        settings = self._settings
        self.jobs.run_each(L("Compressing"), L("Compressed"), self.images + self.pdfs,
                           lambda path, _token, _progress: engine.compress_file(path, settings))
        self.close()


@registry.register("tool.compress")
def create(files: list[str], context) -> CompressTool:  # noqa: ANN001
    return CompressTool(files, context)


__all__ = ["CompressTool", "Qt"]
