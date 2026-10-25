#!/usr/bin/env python3
"""Draws the app icon from the same code the app uses and writes the PNG sizes and an SVG for the hicolor theme.

    python scripts/make_icons.py            # writes packaging/icons/ and src/mangosteen/assets/mangosteen.png
"""

import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(root / "src"))

from PySide6.QtCore import QRectF, QSize  # noqa: E402
from PySide6.QtGui import QGuiApplication, QPainter  # noqa: E402
from PySide6.QtSvg import QSvgGenerator  # noqa: E402

from mangosteen.ui import art  # noqa: E402

SIZES = [16, 24, 32, 48, 64, 128, 256, 512]


def main() -> int:
    app = QGuiApplication(["icons"])
    theme = root / "packaging" / "icons" / "hicolor"
    for size in SIZES:
        folder = theme / f"{size}x{size}" / "apps"
        folder.mkdir(parents=True, exist_ok=True)
        art.pixmap(size).save(str(folder / "mangosteen.png"))
    scalable = theme / "scalable" / "apps"
    scalable.mkdir(parents=True, exist_ok=True)
    generator = QSvgGenerator()
    generator.setFileName(str(scalable / "mangosteen.svg"))
    generator.setSize(QSize(512, 512))
    generator.setViewBox(QRectF(0, 0, 512, 512))
    generator.setTitle("Mangosteen")
    painter = QPainter(generator)
    art.draw_icon(painter, QRectF(0, 0, 512, 512), True)
    painter.end()
    art.pixmap(256).save(str(root / "src" / "mangosteen" / "assets" / "mangosteen.png"))
    del app
    print("icons written to", theme)
    return 0


if __name__ == "__main__":
    sys.exit(main())
