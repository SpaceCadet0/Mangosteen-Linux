"""Layout helpers."""

from __future__ import annotations


def fit(window, width: int, fixed: bool = True) -> None:  # noqa: ANN001
    """Sizes a window that holds word-wrapped labels: Qt does not raise the minimum height of a top-level window for
    wrapped text by itself, so the height for the chosen width is worked out here."""
    layout = window.layout()
    if fixed:
        window.setFixedWidth(width)
    else:
        window.setMinimumWidth(width)
    height = layout.totalHeightForWidth(width) if layout is not None and layout.hasHeightForWidth() else window.sizeHint().height()
    window.setMinimumHeight(height)
    window.resize(max(window.width(), width), height)
