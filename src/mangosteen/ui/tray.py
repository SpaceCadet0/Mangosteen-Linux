"""The tray icon and its menu."""

from __future__ import annotations

import os
import time
from datetime import datetime

from PySide6.QtCore import QObject, Signal
from PySide6.QtGui import QAction
from PySide6.QtWidgets import QMenu, QSystemTrayIcon

from ..core import history as history_module
from ..core.loc import L, count, fmt
from ..core.wheel_catalog import WheelKind, wheel_title
from . import art, glyphs


class TrayController(QObject):
    choose_files = Signal(object)  # WheelKind
    toggle_shelf = Signal()
    open_settings = Signal()
    open_welcome = Signal()
    open_about = Signal()
    check_updates = Signal()
    open_log = Signal()
    quit_requested = Signal()
    reveal_result = Signal(object)  # ResultEntry
    open_result = Signal(object)
    delete_result = Signal(object)
    clear_history = Signal()

    def __init__(self, history: history_module.ResultHistory) -> None:
        super().__init__()
        self.history = history
        self.icon = QSystemTrayIcon(art.app_icon())
        self.icon.setToolTip("Mangosteen")
        self.menu = QMenu()
        self.menu.aboutToShow.connect(self.rebuild)
        self.icon.setContextMenu(self.menu)
        self.icon.activated.connect(self._activated)
        self.rebuild()

    @property
    def available(self) -> bool:
        return QSystemTrayIcon.isSystemTrayAvailable()

    def show(self) -> None:
        self.icon.show()

    def hide(self) -> None:
        self.icon.hide()

    def popup_at_cursor(self) -> None:
        """For desktops without a tray: the same menu where the pointer is."""
        from PySide6.QtGui import QCursor

        self.rebuild()
        self.menu.popup(QCursor.pos())

    def _activated(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        # A left click opens the same menu as a right click (the right click is handled by Qt itself).
        if reason == QSystemTrayIcon.ActivationReason.Trigger:
            self.popup_at_cursor()

    def rebuild(self) -> None:
        menu = self.menu
        menu.clear()
        title = menu.addAction("Mangosteen")
        title.setEnabled(False)
        menu.addSeparator()
        for kind, glyph in ((WheelKind.CONVERT, "image"), (WheelKind.TOOLS, "edit"), (WheelKind.ACTIONS, "actions")):
            action = menu.addAction(glyphs.icon(glyph), wheel_title(kind) + "…")
            action.triggered.connect(lambda _checked=False, k=kind: self.choose_files.emit(k))
        menu.addAction(glyphs.icon("float"), L("Float shelf")).triggered.connect(lambda: self.toggle_shelf.emit())
        menu.addSeparator()
        self._results(menu.addMenu(glyphs.icon("info"), L("Recent Results")))
        menu.addSeparator()
        menu.addAction(L("Settings…")).triggered.connect(lambda: self.open_settings.emit())
        menu.addAction(L("Welcome…")).triggered.connect(lambda: self.open_welcome.emit())
        menu.addAction(L("Open log")).triggered.connect(lambda: self.open_log.emit())
        menu.addAction(L("Check for Updates…")).triggered.connect(lambda: self.check_updates.emit())
        menu.addAction(L("About Mangosteen")).triggered.connect(lambda: self.open_about.emit())
        menu.addSeparator()
        menu.addAction(L("Quit Mangosteen")).triggered.connect(lambda: self.quit_requested.emit())

    def _results(self, menu: QMenu) -> None:
        entries = self.history.live()
        if not entries:
            note = menu.addAction(L("Nothing here yet"))
            note.setEnabled(False)
            return
        for entry in entries:
            submenu = menu.addMenu(f"{label(entry)}")
            submenu.setToolTip(f"{entry.title} · {datetime.fromtimestamp(entry.time):%H:%M}")
            header = submenu.addAction(f"{entry.title} · {datetime.fromtimestamp(entry.time):%H:%M}")
            header.setEnabled(False)
            submenu.addSeparator()
            submenu.addAction(L("Show in the file manager")).triggered.connect(
                lambda _c=False, e=entry: self.reveal_result.emit(e))
            submenu.addAction(L("Open")).triggered.connect(lambda _c=False, e=entry: self.open_result.emit(e))
            submenu.addAction(L("Delete Result")).triggered.connect(lambda _c=False, e=entry: self.delete_result.emit(e))
        menu.addSeparator()
        menu.addAction(L("Clear History")).triggered.connect(lambda: self.clear_history.emit())


def label(entry: history_module.ResultEntry) -> str:
    """"photo.png", or "photo.png and 2 more"."""
    first = os.path.basename(entry.outputs[0].rstrip("/\\"))
    if len(entry.outputs) == 1:
        return first
    return f"{first} {fmt('and {0} more', len(entry.outputs) - 1)}"


__all__ = ["TrayController", "label", "QAction", "count", "time"]
