"""Check for Updates: looks for a newer release, shows what changed and installs it."""

from __future__ import annotations

import threading

from PySide6.QtCore import QObject, Qt, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (QHBoxLayout, QLabel, QPlainTextEdit, QProgressBar, QPushButton, QTextBrowser,
                               QVBoxLayout, QWidget)

from .. import __version__
from ..core import updates
from ..core.loc import L, fmt
from . import art


class _Worker(QObject):
    """Carries results from the worker thread to the window."""

    checked = Signal(object)  # Release
    progressed = Signal(float)
    installed = Signal(list)  # the command that starts the new version
    failed = Signal(str)


class UpdateWindow(QWidget):
    restart_requested = Signal(list)  # the command that starts the new version

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle(L("Check for Updates"))
        self.setWindowIcon(art.app_icon())
        self.release: updates.Release | None = None
        self._new_command: list[str] = []
        self._busy = False
        self._worker = _Worker()
        self._worker.checked.connect(self._checked)
        self._worker.progressed.connect(lambda value: self.progress.setValue(round(value * 1000)))
        self._worker.installed.connect(self._installed)
        self._worker.failed.connect(self._failed)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(10)
        top = QHBoxLayout()
        icon = QLabel()
        icon.setPixmap(art.pixmap(56))
        top.addWidget(icon, alignment=Qt.AlignmentFlag.AlignTop)
        self.status = QLabel()
        self.status.setWordWrap(True)
        self.status.setStyleSheet("font-size: 15px; font-weight: 600;")
        self.detail = QLabel()
        self.detail.setWordWrap(True)
        self.detail.setStyleSheet("color: gray;")
        texts = QVBoxLayout()
        texts.addWidget(self.status)
        texts.addWidget(self.detail)
        texts.addStretch(1)
        top.addLayout(texts, 1)
        layout.addLayout(top)

        self.notes = QTextBrowser()
        self.notes.setOpenExternalLinks(True)
        self.notes.setMinimumHeight(220)
        layout.addWidget(self.notes, 1)
        self.steps = QPlainTextEdit()
        self.steps.setReadOnly(True)
        self.steps.setMaximumHeight(90)
        layout.addWidget(self.steps)
        self.progress = QProgressBar()
        self.progress.setRange(0, 1000)
        self.progress.setTextVisible(False)
        layout.addWidget(self.progress)

        buttons = QHBoxLayout()
        self.page_button = QPushButton(L("Release Page"))
        self.page_button.clicked.connect(self._open_page)
        buttons.addWidget(self.page_button)
        buttons.addStretch(1)
        self.close_button = QPushButton(L("Close"))
        self.close_button.clicked.connect(self.close)
        buttons.addWidget(self.close_button)
        self.action_button = QPushButton()
        self.action_button.setDefault(True)
        self.action_button.clicked.connect(self._action)
        buttons.addWidget(self.action_button)
        layout.addLayout(buttons)
        self.resize(560, 220)
        self._show_parts(notes=False)

    def present(self) -> None:
        self.show()
        self.raise_()
        self.activateWindow()
        if not self._busy and not self._new_command:
            self.check()

    # MARK: States

    def _show_parts(self, notes: bool = False, steps: bool = False, progress: bool = False,
                    action: str = "", page: bool = False) -> None:
        self.notes.setVisible(notes)
        self.steps.setVisible(steps)
        self.progress.setVisible(progress)
        self.action_button.setVisible(bool(action))
        self.action_button.setText(action)
        self.page_button.setVisible(page)
        self.resize(560, 480 if notes else 200)

    def check(self) -> None:
        self._busy = True
        self.status.setText(L("Checking for updates…"))
        self.detail.setText(fmt("You have version {0}.", __version__))
        self._show_parts(progress=True)
        self.progress.setRange(0, 0)
        threading.Thread(target=self._check_thread, name="mangosteen-update", daemon=True).start()

    def _check_thread(self) -> None:
        try:
            self._worker.checked.emit(updates.latest_release())
        except updates.UpdateError as error:
            self._worker.failed.emit(fmt("Could not check for updates: {0}", str(error)))

    def _checked(self, release: updates.Release) -> None:
        self._busy = False
        self.release = release
        self.progress.setRange(0, 1000)
        if not updates.is_newer(release):
            self.status.setText(L("Mangosteen is up to date"))
            self.detail.setText(fmt("Version {0} is the latest.", __version__))
            self._show_parts(page=True)
            return
        self.status.setText(fmt("Mangosteen {0} is available", release.version_text))
        self.notes.setMarkdown(release.notes)
        if updates.can_install(release):
            self.detail.setText(fmt("You have version {0}. The update is downloaded from GitHub and installed; "
                                    "Mangosteen then starts again.", __version__))
            self._show_parts(notes=True, action=L("Update"), page=True)
        else:
            self.detail.setText(fmt("You have version {0}. This copy is updated the way it was installed:",
                                    __version__))
            self.steps.setPlainText(updates.manual_steps(release))
            self._show_parts(notes=True, steps=True, page=True)

    def _failed(self, message: str) -> None:
        self._busy = False
        self.progress.setRange(0, 1000)
        self.status.setText(L("Something went wrong"))
        self.detail.setText(message)
        self._show_parts(action=L("Try Again"), page=True, notes=self.release is not None and bool(self.release.notes))

    def _action(self) -> None:
        if self._new_command:
            self.restart_requested.emit(self._new_command)
        elif self.release is not None and updates.is_newer(self.release) and updates.can_install(self.release):
            self._install()
        else:
            self.check()

    def _install(self) -> None:
        self._busy = True
        self.status.setText(fmt("Installing Mangosteen {0}…", self.release.version_text))
        self.detail.setText(L("The system may ask for your password.") if updates.install_method() == updates.DEB
                            else L("Downloading from GitHub…"))
        self._show_parts(notes=True, progress=True)
        self.progress.setValue(0)
        if updates.install_method() == updates.PIP:
            self.progress.setRange(0, 0)
        self.close_button.setEnabled(False)
        release = self.release
        threading.Thread(target=self._install_thread, args=(release,), name="mangosteen-update", daemon=True).start()

    def _install_thread(self, release: updates.Release) -> None:
        try:
            self._worker.installed.emit(updates.install(release, self._worker.progressed.emit))
        except (updates.UpdateError, OSError) as error:
            self._worker.failed.emit(fmt("The update was not installed: {0}", str(error)))

    def _installed(self, command: list) -> None:
        self._busy = False
        self._new_command = list(command)
        self.close_button.setEnabled(True)
        self.progress.setRange(0, 1000)
        self.status.setText(fmt("Mangosteen {0} is installed", self.release.version_text))
        self.detail.setText(L("Restart Mangosteen to use the new version."))
        self._show_parts(notes=True, action=L("Restart Mangosteen"))

    def _open_page(self) -> None:
        QDesktopServices.openUrl(QUrl(self.release.page if self.release else updates.RELEASES_PAGE))

    def closeEvent(self, event) -> None:  # noqa: N802, ANN001
        if self._busy and not self.close_button.isEnabled():
            event.ignore()
            return
        super().closeEvent(event)
