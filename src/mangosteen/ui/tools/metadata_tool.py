"""Metadata: see everything a picture carries, edit the common fields, remove the location or all of it."""

from __future__ import annotations

import os
from datetime import datetime

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QCheckBox, QFormLayout, QHBoxLayout, QLabel, QLineEdit, QTableWidget, QTableWidgetItem,
                               QVBoxLayout, QWidget)

from ...core import file_format
from ...core.file_format import Category
from ...core.loc import L, fmt
from ...imaging import metadata as engine
from ...imaging.metadata import MetadataChanges, MetadataField
from ..widgets import hint_label
from . import registry
from .base import ToolWindow


class MetadataTool(ToolWindow):
    def __init__(self, files: list[str], context) -> None:  # noqa: ANN001
        self.images = [f for f in files if (d := file_format.detect(f)) is not None and d.category is Category.IMAGE]
        super().__init__(L("Metadata"), files, L("Save"), context)
        self._info: engine.MetadataInfo | None = None
        self._error = ""
        first = self.images[0] if self.images else None
        if first is not None:
            try:
                self._info = engine.read(first)
            except Exception as error:  # noqa: BLE001
                self._error = str(error)

        self._table = QTableWidget(0, 3)
        self._table.setHorizontalHeaderLabels([L("Field"), L("Value"), ""])
        self._table.setColumnCount(2)
        self._table.setHorizontalHeaderLabels([L("Field"), L("Value")])
        self._table.horizontalHeader().setStretchLastSection(True)
        self._table.verticalHeader().setVisible(False)
        self._table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._table.setMinimumSize(380, 360)
        self._fill_table()

        right = QWidget()
        right.setFixedWidth(340)
        column = QVBoxLayout(right)
        column.setContentsMargins(0, 0, 0, 0)
        form = QFormLayout()
        self._fields: dict[MetadataField, QLineEdit] = {}
        self._original: dict[MetadataField, str] = {}
        for field in MetadataField:
            edit = QLineEdit(self._info.text[field] if self._info else "")
            self._fields[field] = edit
            self._original[field] = edit.text()
            form.addRow(field.title, edit)
        taken = self._info.date_taken if self._info else None
        self._date = QLineEdit(taken.strftime("%Y-%m-%d %H:%M") if taken else "")
        self._original_date = self._date.text()
        form.addRow(L("Date taken"), self._date)
        column.addLayout(form)
        column.addWidget(hint_label(L("Format: 2024-05-31 18:45. An empty field is removed.")))
        self._location = QLabel(fmt("Location: {0:0.#####}, {1:0.#####}", *self._info.location)
                                if self._info and self._info.location else L("No location"))
        column.addWidget(self._location)
        self._remove_location = QCheckBox(L("Remove location"))
        self._remove_location.setEnabled(bool(self._info and self._info.location))
        column.addWidget(self._remove_location)
        self._remove_all = QCheckBox(L("Remove all metadata"))
        self._remove_all.toggled.connect(self._all_toggled)
        column.addWidget(self._remove_all)
        if self._error:
            column.addWidget(hint_label(self._error))
        elif self._info is not None and not self._info.entries:
            column.addWidget(hint_label(L("This image has no metadata.")))
        column.addWidget(hint_label(L("Only JPG, PNG and TIFF metadata can be edited; other files are skipped.")))
        if len(self.images) > 1:
            column.addWidget(hint_label(L("The fields show the first image; the changes are applied to every image.")))
        column.addStretch(1)

        outer = QHBoxLayout()
        outer.setSpacing(16)
        outer.addWidget(self._table, 1)
        outer.addWidget(right)
        self.set_body(layout=outer)
        self.resize(860, 520)
        editable = [f for f in self.images if file_format.detect(f) in engine.SUPPORTED]
        self.set_action_enabled(bool(editable))

    def _fill_table(self) -> None:
        entries = self._info.entries if self._info else []
        self._table.setRowCount(len(entries))
        for row, (group, key, value) in enumerate(entries):
            self._table.setItem(row, 0, QTableWidgetItem(f"{group} · {key}"))
            self._table.setItem(row, 1, QTableWidgetItem(value))
        self._table.resizeColumnToContents(0)

    def _all_toggled(self, on: bool) -> None:
        for edit in (*self._fields.values(), self._date):
            edit.setEnabled(not on)
        self._remove_location.setEnabled(not on and bool(self._info and self._info.location))

    def _changes(self) -> MetadataChanges | None:
        if self._remove_all.isChecked():
            return MetadataChanges(remove_all=True)
        changes = MetadataChanges(remove_location=self._remove_location.isChecked())
        for field, edit in self._fields.items():
            if edit.text() != self._original[field]:
                changes.text[field] = edit.text().strip()
        if self._date.text() != self._original_date and self._date.text().strip():
            try:
                changes.date_taken = datetime.strptime(self._date.text().strip(), "%Y-%m-%d %H:%M")
            except ValueError:
                self.context.notify(L("Metadata"), L("The date is not in the format 2024-05-31 18:45."), error=True)
                return None
        return changes

    def run(self) -> None:
        changes = self._changes()
        if changes is None:
            return
        if changes.is_empty:
            self.context.notify(L("Metadata"), L("Nothing was changed."))
            return
        targets = [f for f in self.images if file_format.detect(f) in engine.SUPPORTED]
        self.jobs.run_each(L("Saving metadata"), L("Metadata saved"), targets,
                           lambda path, _t, _p: engine.apply(path, changes))
        self.close()


@registry.register("tool.metadata")
def create(files: list[str], context) -> MetadataTool:  # noqa: ANN001
    return MetadataTool(files, context)


__all__ = ["MetadataTool", "os", "Qt"]
