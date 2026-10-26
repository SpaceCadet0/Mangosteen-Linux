"""Keeps windows inside a small screen: a window whose content does not fit the free area of the screen under the
pointer gets its content in a scroll area and is sized to the screen. On a screen where it fits nothing changes."""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import QRect, QSize, Qt
from PySide6.QtGui import QCursor, QGuiApplication
from PySide6.QtWidgets import QLayout, QScrollArea, QStyle, QVBoxLayout, QWidget

# Room left for the window frame and title bar, which the window's own geometry does not include.
FRAME_WIDTH = 12
FRAME_HEIGHT = 44
_UNLIMITED = 16777215


class FitScrollArea(QScrollArea):
    """A frameless scroll area that asks for its whole content, so a window keeps its natural size where it fits,
    but can be made smaller than the content."""

    def __init__(self, inner: QWidget) -> None:
        super().__init__()
        self.setObjectName("screenFit")
        self.setWidgetResizable(True)
        self.setFrameShape(QScrollArea.Shape.NoFrame)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.setStyleSheet("QScrollArea#screenFit, QScrollArea#screenFit > QWidget > QWidget#screenFitInner "
                           "{ background: transparent; }")
        inner.setObjectName("screenFitInner")
        self.setWidget(inner)

    def sizeHint(self) -> QSize:  # noqa: N802
        bar = self.style().pixelMetric(QStyle.PixelMetric.PM_ScrollBarExtent)
        hint = self.widget().sizeHint()
        return QSize(hint.width() + bar, hint.height() + bar)

    def minimumSizeHint(self) -> QSize:  # noqa: N802
        return QSize(160, 120)


def scroll_layout(layout: QLayout) -> FitScrollArea:
    """Moves `layout`, with its widgets, into a new scroll area. The layout must not be inside another layout."""
    inner = QWidget()
    inner.setLayout(layout)
    return FitScrollArea(inner)


def wrap_window(window: QWidget) -> None:
    """Puts everything in `window` into a scroll area."""
    layout = window.layout()
    area = scroll_layout(layout)  # setLayout takes the layout, and its widgets, away from the window
    outer = QVBoxLayout(window)
    outer.setContentsMargins(0, 0, 0, 0)
    outer.addWidget(area)
    unlock(window)


def unlock(window: QWidget) -> None:
    """Drops fixed and minimum sizes so the window can be made as small as the screen."""
    window.setMinimumSize(0, 0)
    window.setMaximumSize(_UNLIMITED, _UNLIMITED)


def available_area() -> QRect:
    """The free part (without panels) of the screen under the pointer, less the window frame."""
    screen = QGuiApplication.screenAt(QCursor.pos()) or QGuiApplication.primaryScreen()
    area = screen.availableGeometry()
    return QRect(area.x(), area.y(), area.width() - FRAME_WIDTH, area.height() - FRAME_HEIGHT)


def needed(window: QWidget) -> QSize:
    layout = window.layout()
    hint = layout.totalMinimumSize() if layout is not None else window.minimumSizeHint()
    return hint.expandedTo(window.minimumSize())


def fit(window: QWidget, wrap: Callable[[QWidget], None] = wrap_window, center: bool = False) -> bool:
    """Makes `window` fit the screen before it is shown. Returns True when it had to be changed."""
    area = available_area()
    changed = False
    need = needed(window)
    if (need.width() > area.width() or need.height() > area.height()) and not window.property("screenFitted"):
        wrap(window)
        window.setProperty("screenFitted", True)
        changed = True
    size = window.size().expandedTo(window.sizeHint()) if changed else window.size()
    bounded = size.boundedTo(area.size())
    if bounded != window.size():
        window.resize(bounded)
        changed = True
    if changed or center:
        window.move(area.x() + (area.width() - bounded.width()) // 2,
                    area.y() + (area.height() - bounded.height()) // 2)
    return changed


__all__ = ["FitScrollArea", "available_area", "fit", "needed", "scroll_layout", "unlock", "wrap_window"]
