"""A tool window: content with a live preview, and a footer with the file count, Cancel and the main action.
Esc cancels, Enter runs."""

from __future__ import annotations

import os

from PySide6.QtCore import QTimer
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (QFormLayout, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget)

from ...core.loc import L, count, fmt
from .. import art, screenfit


class ToolWindow(QWidget):
    def __init__(self, title: str, files: list[str], action_title: str, context) -> None:  # noqa: ANN001
        super().__init__()
        self.context = context
        self.files = list(files)
        self.setWindowIcon(art.app_icon())
        first = os.path.basename(files[0].rstrip("/\\")) if files else ""
        if not files:
            self.setWindowTitle(title)
        elif len(files) == 1:
            self.setWindowTitle(f"{title} — {first}")
        else:
            self.setWindowTitle(f"{title} — {first} {fmt('and {0} more', len(files) - 1)}")
        self._status = QLabel(count(len(files), "file"))
        self._status.setStyleSheet("color: gray;")
        self._action = QPushButton(action_title)
        self._action.setDefault(True)
        self._action.setMinimumWidth(96)
        self._action.clicked.connect(self.run)
        self._cancel = QPushButton(L("Cancel"))
        self._cancel.setMinimumWidth(96)
        self._cancel.clicked.connect(self.close)
        footer = QHBoxLayout()
        footer.addWidget(self._status, 1)
        footer.addWidget(self._cancel)
        footer.addWidget(self._action)
        self._root = QVBoxLayout(self)
        self._root.setContentsMargins(20, 20, 20, 16)
        self._root.setSpacing(14)
        self._body_holder = QVBoxLayout()
        self._root.addLayout(self._body_holder, 1)
        self._root.addLayout(footer)
        QShortcut(QKeySequence("Esc"), self, self.close)
        QShortcut(QKeySequence("Return"), self, self._enter)
        QShortcut(QKeySequence("Enter"), self, self._enter)

    def _enter(self) -> None:
        if self._action.isEnabled():
            self.run()

    # MARK: For subclasses

    def set_body(self, widget: QWidget | None = None, layout=None) -> None:  # noqa: ANN001
        if layout is not None:
            self._body_holder.addLayout(layout)
        elif widget is not None:
            self._body_holder.addWidget(widget)

    @property
    def action_title(self) -> str:
        return self._action.text()

    @action_title.setter
    def action_title(self, text: str) -> None:
        self._action.setText(text)

    def set_action_enabled(self, enabled: bool) -> None:
        self._action.setEnabled(enabled)

    def set_status(self, text: str) -> None:
        self._status.setText(text)

    def run(self) -> None:
        raise NotImplementedError

    @property
    def jobs(self):  # noqa: ANN201
        return self.context.jobs

    @property
    def settings(self):  # noqa: ANN201
        return self.context.settings

    @property
    def is_settled(self) -> bool:
        """For snapshots: True once the preview has been drawn."""
        return True

    def present(self) -> None:
        """Shows the window in front of everything, on the screen under the pointer, inside its work area. On a screen
        too small for it the content scrolls and the footer with the buttons stays in view."""
        self.adjustSize()
        screenfit.fit(self, wrap=ToolWindow._scroll_body, center=True)
        self.show()
        self.raise_()
        self.activateWindow()

    def _scroll_body(self) -> None:
        self._root.removeItem(self._body_holder)
        self._body_holder.setParent(None)
        self._root.insertWidget(0, screenfit.scroll_layout(self._body_holder), 1)
        screenfit.unlock(self)

    def run_and_close(self) -> None:
        QTimer.singleShot(0, self.close)


def form_row(form: QFormLayout, label: str, widget: QWidget) -> None:
    form.addRow(label, widget)


__all__ = ["ToolWindow", "form_row"]
