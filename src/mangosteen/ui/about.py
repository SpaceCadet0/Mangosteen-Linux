"""The About window."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from .. import __version__
from ..core.loc import L
from . import art, layoututil


class AboutWindow(QWidget):
    check_updates = Signal()

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle(L("About Mangosteen"))
        self.setWindowIcon(art.app_icon())
        layout = QVBoxLayout(self)
        layout.setSpacing(6)
        layout.setContentsMargins(28, 24, 28, 24)
        icon = QLabel()
        icon.setPixmap(art.pixmap(96))
        icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title = QLabel("Mangosteen")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title.setStyleSheet("font-size: 22px; font-weight: 700;")
        version = QLabel(f"{L('Version')} {__version__}")
        version.setAlignment(Qt.AlignmentFlag.AlignCenter)
        version.setStyleSheet("color: gray;")
        text = QLabel(L("Zero-click file converter and toolbox for Linux. Everything runs on your computer; nothing is "
                        "uploaded and nothing is tracked."))
        text.setWordWrap(True)
        text.setAlignment(Qt.AlignmentFlag.AlignCenter)
        link = QLabel('<a href="https://github.com/SpaceCadet0/Mangosteen-Linux">github.com/SpaceCadet0/Mangosteen-Linux</a>')
        link.setAlignment(Qt.AlignmentFlag.AlignCenter)
        link.setOpenExternalLinks(True)
        copyright_ = QLabel("Copyright © 2026 Igor Rusakov (SpaceCadet) · MIT")
        copyright_.setAlignment(Qt.AlignmentFlag.AlignCenter)
        copyright_.setStyleSheet("color: gray; font-size: 11px;")
        updates = QPushButton(L("Check for Updates…"))
        updates.clicked.connect(self.check_updates.emit)
        close = QPushButton(L("Close"))
        close.clicked.connect(self.close)
        for widget in (icon, title, version, text, link, copyright_):
            layout.addWidget(widget)
        layout.addSpacing(8)
        buttons = QHBoxLayout()
        buttons.addStretch(1)
        buttons.addWidget(updates)
        buttons.addWidget(close)
        buttons.addStretch(1)
        layout.addLayout(buttons)
        layoututil.fit(self, 380)

    def present(self) -> None:
        self.show()
        self.raise_()
        self.activateWindow()
