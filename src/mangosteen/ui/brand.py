"""Mangosteen's colours. The brand colour replaces the desktop accent in the wheel, tool windows and selections,
so the app looks the same whatever accent the user has chosen."""

from __future__ import annotations

from PySide6.QtGui import QColor, QGuiApplication, QPalette

# #671E38, the colour of the fruit's rind.
BRAND = QColor(0x67, 0x1E, 0x38)
# In dark mode a lighter wine so tinted text (buttons, links) stays readable on dark backgrounds.
BRAND_ON_DARK = QColor(0xCC, 0x68, 0x90)
BRAND_LIGHT = QColor(0xD1, 0x73, 0x94)


def is_dark(palette: QPalette | None = None) -> bool:
    palette = palette or QGuiApplication.palette()
    return palette.color(QPalette.ColorRole.Window).lightness() < 128


def accent() -> QColor:
    return BRAND_ON_DARK if is_dark() else BRAND


def window_color() -> QColor:
    return QGuiApplication.palette().color(QPalette.ColorRole.Window)


def text_color() -> QColor:
    return QGuiApplication.palette().color(QPalette.ColorRole.WindowText)


def secondary_text_color() -> QColor:
    color = QColor(text_color())
    color.setAlphaF(0.62)
    return color


def apply_palette(app) -> None:  # noqa: ANN001
    """The Fusion style with the desktop's own colours and the brand colour as the highlight."""
    app.setStyle("Fusion")
    palette = app.palette()
    palette.setColor(QPalette.ColorRole.Highlight, accent())
    palette.setColor(QPalette.ColorRole.HighlightedText, QColor("white"))
    palette.setColor(QPalette.ColorRole.Link, accent())
    app.setPalette(palette)
