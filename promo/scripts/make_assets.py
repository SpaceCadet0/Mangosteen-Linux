#!/usr/bin/env python3
"""Prepares promo/public for the demo video: the wheel icons drawn from the app's own glyphs, thumbnails of the sample
photos (docs/samples), a sound-file icon, and snapshots of the real Trim and Float windows (light theme).

    python promo/scripts/make_assets.py        # from the repository root, with the app's dependencies installed
"""

import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PUBLIC = ROOT / "promo" / "public"
SAMPLES = ROOT / "docs" / "samples"
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(ROOT / "src"))

from PIL import Image, ImageDraw  # noqa: E402
from PySide6.QtCore import QRectF  # noqa: E402
from PySide6.QtGui import QColor, QGuiApplication, QImage, QPainter  # noqa: E402

from mangosteen.ui import glyphs  # noqa: E402

GLYPHS = ["image", "document", "trim", "split", "speed", "volume", "bleep", "hide", "crop", "compress", "frames",
          "float", "copy", "move", "path", "terminal"]


def glyph(name: str, color: str, prefix: str) -> None:
    image = QImage(96, 80, QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(0)
    painter = QPainter(image)
    glyphs.draw(painter, name, QRectF(8, 0, 80, 80), QColor(color), 1.9)
    painter.end()
    image.save(str(PUBLIC / "icons" / f"{prefix}-{name}.png"))


def thumbnail(source: Image.Image, target: Path, size: int = 256) -> None:
    """The picture fitted into a square, with rounded corners, as a file manager shows it."""
    picture = source.copy()
    picture.thumbnail((size, size), Image.LANCZOS)
    mask = Image.new("L", picture.size, 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, picture.width - 1, picture.height - 1), 10, fill=255)
    canvas = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    canvas.paste(picture, ((size - picture.width) // 2, (size - picture.height) // 2), mask)
    canvas.save(target)


def sound_icon(target: Path, size: int = 256) -> None:
    """A page with a folded corner and a note, like the sound-file icon of a Linux desktop."""
    image = QImage(size, size, QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(0)
    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    from PySide6.QtGui import QPainterPath

    page = QPainterPath()
    left, top, right, bottom, fold = size * 0.2, size * 0.06, size * 0.8, size * 0.94, size * 0.18
    page.moveTo(left, top)
    page.lineTo(right - fold, top)
    page.lineTo(right, top + fold)
    page.lineTo(right, bottom)
    page.lineTo(left, bottom)
    page.closeSubpath()
    painter.setPen(QColor("#C9C9CF"))
    painter.setBrush(QColor("#F4F4F6"))
    painter.drawPath(page)
    painter.setBrush(QColor("#D8D8DE"))
    corner = QPainterPath()
    corner.moveTo(right - fold, top)
    corner.lineTo(right - fold, top + fold)
    corner.lineTo(right, top + fold)
    corner.closeSubpath()
    painter.drawPath(corner)
    glyphs.draw(painter, "music", QRectF(size * 0.3, size * 0.36, size * 0.4, size * 0.4), QColor("#671E38"), 2.0)
    painter.end()
    image.save(str(target))


def snapshot(what: str, output: Path, files: list[Path], home: Path) -> None:
    environment = dict(os.environ, HOME=str(home), MANGOSTEEN_NO_PLAYER="1", MANGOSTEEN_SNAPSHOT_DEMO="1",
                       MANGOSTEEN_HOME=str(home / ".mangosteen"), LANGUAGE="en", LC_ALL="C.UTF-8", PYTHONPATH=str(ROOT / "src"))
    subprocess.run([sys.executable, "-m", "mangosteen", "--snapshot", what, str(output), *map(str, files)],
                   env=environment, check=True, capture_output=True)


def main() -> int:
    app = QGuiApplication(["assets"])
    (PUBLIC / "icons").mkdir(parents=True, exist_ok=True)
    for name in GLYPHS:
        glyph(name, "#2B2B2E", "g")   # on a light segment
        glyph(name, "#FFFFFF", "gw")  # on the highlighted (wine) segment
    top = Image.open(SAMPLES / "mangosteen-top.webp").convert("RGB")
    plate = Image.open(SAMPLES / "mangosteen-plate.webp").convert("RGB")
    thumbnail(top, PUBLIC / "icons" / "photo-thumb.png")
    thumbnail(plate, PUBLIC / "icons" / "video-thumb.png")
    sound_icon(PUBLIC / "icons" / "song.png")

    # The files the video shows, with real contents, so the windows look as they would.
    work = Path(tempfile.mkdtemp(prefix="mangosteen-promo-"))
    folder = work / "home" / "Pictures"  # the snapshots run with this home, so Float shows "~/Pictures"
    folder.mkdir(parents=True)
    photo, video, song = folder / "photo.heic", folder / "Mangosteen.mp4", folder / "song.mp3"
    import pillow_heif

    pillow_heif.register_heif_opener()
    top.save(photo, quality=80)
    subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i", "sine=frequency=330:duration=8",
                    "-c:a", "libmp3lame", "-q:a", "6", str(song)], check=True)
    subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-loop", "1", "-framerate", "25", "-t", "8", "-i",
                    str(SAMPLES / "mangosteen-plate.webp"), "-i", str(song), "-vf",
                    "zoompan=z='1+0.0008*on':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d=1:s=960x640:fps=25",
                    "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", str(video)], check=True)
    snapshot("tool.trimMedia", PUBLIC / "linux-trim.png", [video], work / "home")
    snapshot("float", PUBLIC / "linux-float.png", [photo, song], work / "home")
    shutil.rmtree(work, ignore_errors=True)
    del app
    print("assets written to", PUBLIC)
    return 0


if __name__ == "__main__":
    sys.exit(main())
