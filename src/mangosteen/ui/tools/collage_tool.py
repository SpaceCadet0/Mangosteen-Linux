"""Collage: arrange several images in a grid, row, column or featured layout."""

from __future__ import annotations

import os
from dataclasses import replace

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QIcon, QPixmap
from PySide6.QtWidgets import (QAbstractItemView, QComboBox, QFormLayout, QHBoxLayout, QLabel, QListWidget,
                               QListWidgetItem, QSpinBox, QVBoxLayout, QWidget)

from ...convert import images, qtutil
from ...core import file_format
from ...core.file_format import Category, FileFormat
from ...core.loc import L, count, fmt
from ...imaging import compose
from ...imaging.compose import CanvasAspect, CollageLayout, CollageSettings, RGBA
from ..widgets import ColorButton, LabeledSlider, LiveTask, PreviewPane
from . import registry
from .base import ToolWindow

_WIDTHS = [1080, 1600, 2048, 3000, 4096, 6000]
_FORMATS = [FileFormat.JPG, FileFormat.PNG, FileFormat.HEIC, FileFormat.WEBP]


class CollageTool(ToolWindow):
    def __init__(self, files: list[str], context) -> None:  # noqa: ANN001
        self.order = [f for f in files if (d := file_format.detect(f)) is not None and d.category is Category.IMAGE]
        super().__init__(L("Collage"), files, L("Create"), context)
        self._settings = CollageSettings()
        self._thumbs: dict[str, object] = {}
        self._settled = False
        self._preview = PreviewPane(560, 520)
        self._preview.set_message("…")
        right = QVBoxLayout()
        right.addWidget(self._controls())
        right.addWidget(QLabel(L("Photos keep the order they had in the file manager. Featured photo puts the first one large.")))
        right.itemAt(right.count() - 1).widget().setWordWrap(True)
        right.itemAt(right.count() - 1).widget().setStyleSheet("color: gray; font-size: 11px;")
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
        for path in self.order:
            QListWidgetItem(os.path.basename(path), self._list).setData(Qt.ItemDataRole.UserRole, path)
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
        self._columns_label = QLabel(L("Columns"))
        form.addRow(self._columns_label, self._columns)
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
        self._background = ColorButton(self._settings.background.to_qcolor())
        self._background.changed.connect(lambda c: self._set(background=RGBA.from_qcolor(c)))
        form.addRow(L("Background"), self._background)
        self._format = QComboBox()
        for f in _FORMATS:
            self._format.addItem(f.display_name, f)
        self._format.currentIndexChanged.connect(lambda: self._set(format=self._format.currentData()))
        form.addRow(L("Format"), self._format)
        return holder

    def _layout_changed(self) -> None:
        layout = self._layout.currentData()
        grid = layout is CollageLayout.GRID
        self._columns.setVisible(grid)
        self._columns_label.setVisible(grid)
        self._set(layout=layout)

    def _set(self, **changes) -> None:  # noqa: ANN003
        self._settings = replace(self._settings, **changes)
        self._render()

    def _reordered(self, *_args) -> None:  # noqa: ANN002
        self.order = [self._list.item(i).data(Qt.ItemDataRole.UserRole) for i in range(self._list.count())]
        self._render()

    def _loaded(self, thumbs) -> None:  # noqa: ANN001
        self._thumbs = thumbs
        for index in range(self._list.count()):
            item = self._list.item(index)
            thumb = thumbs.get(item.data(Qt.ItemDataRole.UserRole))
            if thumb is not None:
                small = thumb.copy()
                small.thumbnail((64, 64))
                item.setIcon(QIcon(QPixmap.fromImage(qtutil.pil_to_qimage(small))))
        self._render()

    def _render(self) -> None:
        photos = [self._thumbs.get(p) for p in self.order]
        if not photos or any(p is None for p in photos):
            return
        # Spacing and corners are relative, so a narrower preview looks the same.
        preview = replace(self._settings, width=1000)
        self._live.request(lambda cancelled: compose.compose_collage(photos, preview))

    def _rendered(self, image) -> None:  # noqa: ANN001
        self._preview.set_message("")
        self._preview.set_image(qtutil.pil_to_qimage(image))
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


__all__ = ["CollageTool"]
