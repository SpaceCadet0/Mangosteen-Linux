"""Deleting every window while the application object still exists.

Left to interpreter shutdown, Qt objects are destroyed in an arbitrary order, some after the QApplication; the
process then crashes on exit (heap corruption while an icon or pixmap is freed)."""

from __future__ import annotations


def delete_windows(qapp) -> None:  # noqa: ANN001
    from PySide6.QtCore import QCoreApplication, QEvent
    from PySide6.QtWidgets import QApplication

    for widget in QApplication.topLevelWidgets():
        widget.close()
        widget.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    QCoreApplication.processEvents()
