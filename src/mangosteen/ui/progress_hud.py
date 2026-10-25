"""A small panel in the bottom-right corner that shows a running job: what it does, which file, how far, and a Stop
button. It never takes focus away from the app you are in."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QGuiApplication, QPainter
from PySide6.QtWidgets import QHBoxLayout, QLabel, QProgressBar, QPushButton, QVBoxLayout, QWidget

from ..core.loc import L, fmt
from . import brand


class ProgressHud(QWidget):
    stop_requested = Signal()
    _open: list[ProgressHud] = []

    def __init__(self, title: str) -> None:
        super().__init__()
        self.setWindowFlags(Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint
                            | Qt.WindowType.WindowDoesNotAcceptFocus)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setFixedWidth(340)
        self.setWindowTitle("Mangosteen")
        self._title = QLabel(title)
        font = self._title.font()
        font.setBold(True)
        self._title.setFont(font)
        self._detail = QLabel("")
        self._detail.setStyleSheet("color: #9A9AA0;")
        self._bar = QProgressBar()
        self._bar.setRange(0, 1000)
        self._bar.setTextVisible(False)
        self._bar.setFixedHeight(6)
        self._bar.setStyleSheet(
            "QProgressBar { background: #3A3A3D; border: none; border-radius: 3px; }"
            f"QProgressBar::chunk {{ background: {brand.BRAND_LIGHT.name()}; border-radius: 3px; }}")
        self._stop = QPushButton(L("Stop"))
        self._stop.setFlat(True)
        self._stop.setCursor(Qt.CursorShape.PointingHandCursor)
        self._stop.setStyleSheet("QPushButton { color: #E6E6EA; background: #3A3A3D; border: none; border-radius: 4px;"
                                 " padding: 3px 12px; } QPushButton:hover { background: #4A4A4E; }")
        self._stop.clicked.connect(self._stopping)
        for label in (self._title,):
            label.setStyleSheet("color: #F2F2F5;")
        top = QHBoxLayout()
        top.addWidget(self._title, 1)
        top.addWidget(self._stop)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 14, 18, 16)
        layout.setSpacing(2)
        layout.addLayout(top)
        layout.addWidget(self._detail)
        layout.addWidget(self._bar)
        self.adjustSize()

    def paintEvent(self, _event) -> None:  # noqa: ANN001, N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(QColor(0x3A, 0x3A, 0x3D))
        painter.setBrush(QColor(0x1C, 0x1C, 0x1E, 245))
        painter.drawRoundedRect(self.rect().adjusted(0, 0, -1, -1), 12, 12)

    def show_hud(self) -> None:
        screen = QGuiApplication.primaryScreen().availableGeometry()
        stack = len(ProgressHud._open)
        self.adjustSize()
        self.move(screen.right() - self.width() - 12, screen.bottom() - self.height() - 12 - stack * (self.height() + 8))
        ProgressHud._open.append(self)
        self.show()

    def closeEvent(self, event) -> None:  # noqa: ANN001, N802
        if self in ProgressHud._open:
            ProgressHud._open.remove(self)
        super().closeEvent(event)

    def report(self, index: int, total: int, name: str, fraction: float | None = None) -> None:
        """`index` files are done; the one called `name` is running, `fraction` of the way."""
        text = name if total <= 1 else f"{name}  ·  {fmt('{0} of {1}', min(index + 1, total), total)}"
        self._detail.setText(self._detail.fontMetrics().elidedText(text, Qt.TextElideMode.ElideMiddle, 300))
        overall = (index + (fraction or 0.0)) / max(total, 1)
        self._bar.setValue(int(max(0.0, min(overall, 1.0)) * 1000))

    def _stopping(self) -> None:
        self._stop.setEnabled(False)
        self._stop.setText(L("Stopping…"))
        self.stop_requested.emit()
