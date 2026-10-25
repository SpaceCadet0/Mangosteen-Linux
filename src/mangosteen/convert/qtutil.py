"""Small helpers for code that needs Qt's painting or text layout outside the GUI thread or without a window."""

from __future__ import annotations

import os
import threading

_lock = threading.Lock()


def ensure_gui_app():  # noqa: ANN201
    """A QGuiApplication for painting, fonts and SVG, created (offscreen) when the process has none yet. The real
    app creates its QApplication first, so this is only the command line and the tests."""
    from PySide6.QtGui import QGuiApplication

    with _lock:
        app = QGuiApplication.instance()
        if app is None:
            os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
            app = QGuiApplication(["mangosteen"])
        return app


def qimage_to_pil(image):  # noqa: ANN001, ANN201
    """A QImage as a PIL RGBA image."""
    from PIL import Image
    from PySide6.QtGui import QImage

    converted = image.convertToFormat(QImage.Format.Format_RGBA8888)
    return Image.frombuffer("RGBA", (converted.width(), converted.height()), bytes(converted.constBits()),
                            "raw", "RGBA", converted.bytesPerLine(), 1).copy()


def pil_to_qimage(image):  # noqa: ANN001, ANN201
    """A PIL image as a QImage (a copy, so the PIL image can go away)."""
    from PySide6.QtGui import QImage

    rgba = image.convert("RGBA")
    data = rgba.tobytes("raw", "RGBA")
    qimage = QImage(data, rgba.width, rgba.height, rgba.width * 4, QImage.Format.Format_RGBA8888)
    return qimage.copy()
