#!/usr/bin/env python3
"""Makes the pictures in the READMEs: docs/images/{en,ru}/<name>.png.

Sample files are drawn here (a landscape, a short video, a song, a PDF), then each window is rendered with
`mangosteen --snapshot`. Nothing from a real computer appears in them.

    python scripts/readme_images.py            # needs ffmpeg for the video and audio windows
"""

import math
import os
import shutil
import struct
import subprocess
import sys
import tempfile
import wave
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

ROOT = Path(__file__).resolve().parent.parent

# (image name, snapshot target, sample file kinds)
WINDOWS = [
    ("wheel-convert", "wheel:convert", ["photo"]),
    ("wheel-tools", "wheel:tools", ["photo"]),
    ("wheel-actions", "wheel:actions", ["photo"]),
    ("settings", "settings", []),
    ("welcome", "welcome", []),
    ("crop", "tool.crop", ["photo"]),
    ("edit", "tool.edit", ["photo"]),
    ("annotate", "tool.annotate", ["photo"]),
    ("compress", "tool.compress", ["photo"]),
    ("hide", "tool.redact", ["photo"]),
    ("collage", "tool.collage", ["photo", "photo2", "photo3"]),
    ("organizePDF", "tool.organizePDF", ["pdf"]),
    ("trimMedia", "tool.trimMedia", ["video"]),
    ("bleep", "tool.bleep", ["song"]),
    ("visualizer", "tool.visualizer", ["song"]),
    ("redactVideo", "tool.redactVideo", ["video"]),
]


def landscape(path: Path, seed: int, size=(1600, 1067)) -> None:
    width, height = size
    rng = np.random.default_rng(seed)
    sky = np.zeros((height, width, 3), dtype=np.float32)
    top, bottom = np.array([70, 110, 190]), np.array([250, 190, 150])
    for y in range(height):
        sky[y] = top + (bottom - top) * (y / height) ** 0.8
    image = Image.fromarray(sky.astype(np.uint8))
    draw = ImageDraw.Draw(image, "RGBA")
    sun_x, sun_y = int(width * (0.3 + 0.4 * rng.random())), int(height * 0.38)
    for radius, alpha in ((170, 40), (110, 70), (70, 255)):
        draw.ellipse((sun_x - radius, sun_y - radius, sun_x + radius, sun_y + radius), fill=(255, 236, 190, alpha))
    for layer, color in enumerate(((120, 100, 140), (86, 74, 112), (52, 46, 76), (30, 28, 48))):
        base = height * (0.52 + layer * 0.1)
        points = [(0, height)]
        phase = rng.random() * 6
        for x in range(0, width + 40, 40):
            points.append((x, base - 90 * math.sin(x / (230 + layer * 70) + phase) - 40 * math.sin(x / 90 + layer)))
        points.append((width, height))
        draw.polygon(points, fill=color + (255,))
    image.filter(ImageFilter.GaussianBlur(0.8)).save(path, quality=92)


def song(path: Path, seconds: float = 8.0, rate: int = 22050) -> None:
    notes = [261.6, 329.6, 392.0, 523.3, 392.0, 329.6, 293.7, 349.2]
    frames = bytearray()
    for i in range(int(rate * seconds)):
        t = i / rate
        note = notes[int(t * 2) % len(notes)]
        envelope = 0.4 + 0.6 * abs(math.sin(math.pi * t * 2))
        value = 9000 * envelope * (math.sin(2 * math.pi * note * t) + 0.4 * math.sin(2 * math.pi * note * 2 * t))
        frames += struct.pack("<h", int(value))
    with wave.open(str(path), "wb") as stream:
        stream.setnchannels(1)
        stream.setsampwidth(2)
        stream.setframerate(rate)
        stream.writeframes(bytes(frames))


def clip(path: Path, picture: Path, audio: Path) -> None:
    subprocess.run(["ffmpeg", "-hide_banner", "-nostdin", "-y", "-loglevel", "error", "-loop", "1", "-framerate", "25",
                    "-t", "8", "-i", str(picture), "-i", str(audio), "-vf",
                    "zoompan=z='1+0.0008*on':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d=1:s=960x640:fps=25",
                    "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", str(path)], check=True)


def report(path: Path) -> None:
    try:
        font = ImageFont.truetype("DejaVuSans.ttf", 22)
        big = ImageFont.truetype("DejaVuSans-Bold.ttf", 40)
    except OSError:
        font = big = ImageFont.load_default()
    pages = []
    for number in range(1, 7):
        page = Image.new("RGB", (794, 1123), "white")
        draw = ImageDraw.Draw(page)
        draw.text((60, 60), f"Quarterly report · {number}", fill=(103, 30, 56), font=big)
        for line in range(24):
            draw.text((60, 160 + line * 34), "Lorem ipsum dolor sit amet, consectetur adipiscing elit " [: 40 + (line * 7) % 22],
                      fill=(60, 60, 60), font=font)
        draw.rectangle((60, 1000, 734, 1004), fill=(103, 30, 56))
        pages.append(page)
    pages[0].save(path, save_all=True, append_images=pages[1:], resolution=100)


def main() -> int:
    if not shutil.which("ffmpeg"):
        print("ffmpeg is needed for the video and audio windows", file=sys.stderr)
        return 1
    work = Path(tempfile.mkdtemp(prefix="mangosteen-readme-"))
    files = {"photo": work / "Holiday.jpg", "photo2": work / "Sunset.jpg", "photo3": work / "Hills.jpg",
             "song": work / "Song.wav", "video": work / "Trip.mp4", "pdf": work / "Report.pdf"}
    landscape(files["photo"], 1)
    landscape(files["photo2"], 2)
    landscape(files["photo3"], 3)
    song(files["song"])
    clip(files["video"], files["photo"], files["song"])
    report(files["pdf"])
    home = work / "home"
    for language in ("en", "ru"):
        target = ROOT / "docs" / "images" / language
        target.mkdir(parents=True, exist_ok=True)
        environment = dict(os.environ, QT_QPA_PLATFORM="offscreen", MANGOSTEEN_NO_PLAYER="1", MANGOSTEEN_HOME=str(home),
                           LANGUAGE=language, LC_ALL=f"{language}_{language.upper()}.UTF-8", LANG=f"{language}_{language.upper()}.UTF-8",
                           PYTHONPATH=str(ROOT / "src"))
        for name, what, kinds in WINDOWS:
            output = target / f"{name}.png"
            result = subprocess.run([sys.executable, "-m", "mangosteen", "--snapshot", what, str(output),
                                     *[str(files[k]) for k in kinds]], env=environment, capture_output=True, text=True)
            print(f"{language}/{name}: {'ok' if result.returncode == 0 and output.exists() else 'FAILED ' + result.stderr[-300:]}")
    shutil.rmtree(work, ignore_errors=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
