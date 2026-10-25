"""Small widgets shared by the tool windows."""

from __future__ import annotations

from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor

from PySide6.QtCore import QObject, QPointF, QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QImage, QPainter, QPixmap
from PySide6.QtWidgets import (QButtonGroup, QColorDialog, QHBoxLayout, QLabel, QPushButton, QSizePolicy, QSlider,
                               QWidget)

from ..core.cancellation import Cancelled
from . import brand


class Segmented(QWidget):
    """A row of mutually exclusive buttons, like a segmented control."""

    changed = Signal(object)

    def __init__(self, options: list[tuple[str, object]], value: object | None = None) -> None:
        super().__init__()
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        self._group = QButtonGroup(self)
        self._group.setExclusive(True)
        self._values: dict[int, object] = {}
        for index, (title, data) in enumerate(options):
            button = QPushButton(title)
            button.setCheckable(True)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.setStyleSheet(self._style(index, len(options)))
            button.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            self._group.addButton(button, index)
            self._values[index] = data
            layout.addWidget(button)
            if (value is None and index == 0) or data == value:
                button.setChecked(True)
        self._group.idClicked.connect(lambda i: self.changed.emit(self._values[i]))

    @staticmethod
    def _style(index: int, count: int) -> str:
        first, last = index == 0, index == count - 1
        radius = "6px"
        corners = (f"border-top-left-radius: {radius if first else '0'}; border-bottom-left-radius: {radius if first else '0'};"
                   f"border-top-right-radius: {radius if last else '0'}; border-bottom-right-radius: {radius if last else '0'};")
        accent = brand.BRAND.name()
        return ("QPushButton { padding: 4px 10px; border: 1px solid rgba(128,128,128,90); "
                f"{corners} }} QPushButton:checked {{ background: {accent}; color: white; border-color: {accent}; }}")

    @property
    def value(self) -> object:
        return self._values[self._group.checkedId()]

    def set_value(self, value: object) -> None:
        for index, data in self._values.items():
            if data == value:
                self._group.button(index).setChecked(True)


class LabeledSlider(QWidget):
    """A slider with its value shown on the right; double-click resets it."""

    value_changed = Signal(float)

    def __init__(self, minimum: float, maximum: float, value: float, reset: float,
                 format_: Callable[[float], str], steps: int = 1000) -> None:
        super().__init__()
        self._min, self._max, self._reset, self._format, self._steps = minimum, maximum, reset, format_, steps
        self.slider = QSlider(Qt.Orientation.Horizontal)
        self.slider.setRange(0, steps)
        self.readout = QLabel()
        self.readout.setMinimumWidth(52)
        self.readout.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.slider, 1)
        layout.addWidget(self.readout)
        self.set_value(value)
        self.slider.valueChanged.connect(self._moved)
        self.slider.mouseDoubleClickEvent = lambda _e: self.set_value(self._reset, emit=True)  # type: ignore[method-assign]

    def _to_value(self, position: int) -> float:
        return self._min + (self._max - self._min) * position / self._steps

    @property
    def value(self) -> float:
        return self._to_value(self.slider.value())

    def set_value(self, value: float, emit: bool = False) -> None:
        position = round((value - self._min) / (self._max - self._min) * self._steps)
        blocked = self.slider.blockSignals(not emit)
        self.slider.setValue(position)
        self.slider.blockSignals(blocked)
        self.readout.setText(self._format(self.value))
        if emit:
            self.value_changed.emit(self.value)

    def _moved(self, _position: int) -> None:
        self.readout.setText(self._format(self.value))
        self.value_changed.emit(self.value)


class ColorButton(QPushButton):
    """A colour swatch; clicking opens the colour dialog."""

    changed = Signal(object)  # QColor

    def __init__(self, color: QColor, alpha: bool = False) -> None:
        super().__init__()
        self._color = QColor(color)
        self._alpha = alpha
        self.setFixedSize(40, 24)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.clicked.connect(self._choose)
        self._paint()

    @property
    def color(self) -> QColor:
        return QColor(self._color)

    def set_color(self, color: QColor) -> None:
        self._color = QColor(color)
        self._paint()

    def _paint(self) -> None:
        self.setStyleSheet(f"QPushButton {{ background: {self._color.name(QColor.NameFormat.HexArgb)};"
                           " border: 1px solid rgba(128,128,128,140); border-radius: 5px; }")

    def _choose(self) -> None:
        options = QColorDialog.ColorDialogOption.ShowAlphaChannel if self._alpha else QColorDialog.ColorDialogOption(0)
        color = QColorDialog.getColor(self._color, self, "", options)
        if color.isValid():
            self.set_color(color)
            self.changed.emit(color)


class PreviewPane(QWidget):
    """A rounded panel that shows an image scaled to fit."""

    def __init__(self, width: int, height: int) -> None:
        super().__init__()
        self.setFixedSize(width, height)
        self._pixmap: QPixmap | None = None
        self._busy = False
        self._message = ""

    def set_image(self, image: QImage | QPixmap | None) -> None:
        self._pixmap = QPixmap.fromImage(image) if isinstance(image, QImage) else image
        self.update()

    def set_busy(self, busy: bool) -> None:
        self._busy = busy
        self.update()

    def set_message(self, text: str) -> None:
        self._message = text
        self.update()

    def paintEvent(self, _event) -> None:  # noqa: ANN001, N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(128, 128, 128, 36))
        painter.drawRoundedRect(self.rect(), 10, 10)
        if self._pixmap is not None and not self._pixmap.isNull():
            area = QRectF(self.rect()).adjusted(6, 6, -6, -6)
            scaled = self._pixmap.size().scaled(area.size().toSize(), Qt.AspectRatioMode.KeepAspectRatio)
            target = QRectF(0, 0, scaled.width(), scaled.height())
            target.moveCenter(area.center())
            painter.drawPixmap(target, self._pixmap, QRectF(self._pixmap.rect()))
        if self._message:
            painter.setPen(brand.secondary_text_color())
            painter.drawText(self.rect().adjusted(12, 12, -12, -12), int(Qt.AlignmentFlag.AlignCenter | Qt.TextFlag.TextWordWrap),
                             self._message)
        if self._busy:
            painter.setPen(QColor(128, 128, 128, 160))
            painter.drawText(self.rect().adjusted(0, 0, -12, -8), int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignBottom), "…")


class LiveTask(QObject):
    """Runs a function off the UI thread after the user stops changing things for a moment. Only the newest request's
    result is delivered; older ones are dropped, and a running one is asked to stop.

    The work runs on a Python thread pool, not a Qt one: Python waits for its own threads before it tears modules
    down at exit, so libraries such as pdfium are never unloaded under a thread that still uses them."""

    finished = Signal(object)  # the function's result
    failed = Signal(str)
    started = Signal()
    _result = Signal(int, object)
    _error = Signal(int, str)

    def __init__(self, delay_ms: int = 250) -> None:
        super().__init__()
        self._delay = delay_ms
        self._serial = 0
        self._function: Callable[[Callable[[], bool]], object] | None = None
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._start)
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="mangosteen-live")
        self._result.connect(self._deliver)
        self._error.connect(self._deliver_error)

    def request(self, function: Callable[[Callable[[], bool]], object], immediate: bool = False) -> None:
        """`function(cancelled)` is called in a worker thread; `cancelled()` turns True when a newer request exists."""
        self._serial += 1
        self._function = function
        self._timer.start(0 if immediate else self._delay)

    def _start(self) -> None:
        serial, function = self._serial, self._function
        if function is None:
            return
        self.started.emit()

        def job() -> None:
            def cancelled() -> bool:
                return self._serial != serial

            if cancelled():
                return
            try:
                result = function(cancelled)
            except (Cancelled, InterruptedError):
                return
            except Exception as error:  # noqa: BLE001
                if not cancelled():
                    self._error.emit(serial, str(error) or type(error).__name__)
                return
            if not cancelled():
                self._result.emit(serial, result)

        self._executor.submit(job)

    def _deliver(self, serial: int, result: object) -> None:
        if serial == self._serial:
            self.finished.emit(result)

    def _deliver_error(self, serial: int, message: str) -> None:
        if serial == self._serial:
            self.failed.emit(message)


def hint_label(text: str) -> QLabel:
    label = QLabel(text)
    label.setWordWrap(True)
    label.setStyleSheet("color: gray; font-size: 12px;")
    return label


def size_hint_of(width: int, height: int) -> QSize:
    return QSize(width, height)


__all__ = ["Segmented", "LabeledSlider", "ColorButton", "PreviewPane", "LiveTask", "hint_label", "QPointF"]
