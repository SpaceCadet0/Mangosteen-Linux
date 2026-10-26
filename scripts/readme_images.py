#!/usr/bin/env python3
"""Makes the pictures in the READMEs: docs/images/{en,ru}/<name>.png.

The sample photos are docs/samples/*.webp; a short video, a song and a PDF are made from them here, then each window is
rendered with `mangosteen --snapshot`. Nothing from a real computer appears in them. Screenshots shown side by side are
scaled to the same height, so a row has no staircase, and the script prints the <img width> percentages that keep the
rendered heights equal (each image's share of the row follows its aspect ratio).

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

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent.parent
SAMPLES = ROOT / "docs" / "samples"
# Shown side by side in the READMEs, left and right, rendered at one height so neither needs scaling.
PAIRS = [("crop", "edit", 640), ("annotate", "hide", 600), ("trimMedia", "bleep", 520),
         ("compress", "visualizer", 480), ("organizePDF", "redactVideo", 580)]
HEIGHTS = {name: height for left, right, height in PAIRS for name in (left, right)}
ROW = 98  # per cent of the README width a row of two takes (a little room for the gap)

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
    ("bleep", "tool.bleep", ["video"]),
    ("visualizer", "tool.visualizer", ["song"]),
    ("redactVideo", "tool.redactVideo", ["video"]),
]


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


def report(path: Path, picture: Path | None = None) -> None:
    try:
        font = ImageFont.truetype("DejaVuSans.ttf", 22)
        big = ImageFont.truetype("DejaVuSans-Bold.ttf", 40)
    except OSError:
        font = big = ImageFont.load_default()
    pages = []
    for number in range(1, 7):
        page = Image.new("RGB", (794, 1123), "white")
        draw = ImageDraw.Draw(page)
        draw.text((60, 60), f"Mangosteen · {number}", fill=(103, 30, 56), font=big)
        if picture is not None:
            photo = Image.open(picture).convert("RGB")
            photo = photo.crop((number * 90, 0, number * 90 + 1000, 667)).resize((674, 450))
            page.paste(photo, (60, 140))
        for line in range(24 if picture is None else 11):
            draw.text((60, (160 if picture is None else 620) + line * 34), "Lorem ipsum dolor sit amet, consectetur adipiscing elit " [: 40 + (line * 7) % 22],
                      fill=(60, 60, 60), font=font)
        draw.rectangle((60, 1000, 734, 1004), fill=(103, 30, 56))
        pages.append(page)
    pages[0].save(path, save_all=True, append_images=pages[1:], resolution=100)


def level_pairs(folder: Path, language: str) -> None:
    """Scales each pair to the lower of the two heights and prints the widths that keep the rendered heights equal."""
    for left, right, _height in PAIRS:
        images = [Image.open(folder / f"{name}.png").convert("RGBA") for name in (left, right)]
        height = min(image.height for image in images)
        scaled = [image if image.height == height else
                  image.resize((round(image.width * height / image.height), height), Image.LANCZOS) for image in images]
        total = sum(image.width for image in scaled)
        widths = []
        for name, image in zip((left, right), scaled):
            image.save(folder / f"{name}.png", optimize=True)
            widths.append(f"{name} {image.width * ROW / total:.1f}%")
        print(f"{language}: {', '.join(widths)} (height {height}px)")


def main() -> int:
    if not shutil.which("ffmpeg"):
        print("ffmpeg is needed for the video and audio windows", file=sys.stderr)
        return 1
    work = Path(tempfile.mkdtemp(prefix="mangosteen-readme-"))
    files = {"photo": work / "Mangosteen.jpg", "photo2": work / "Mangosteen on a plate.jpg",
             "photo3": work / "Mangosteen close-up.jpg", "song": work / "Song.wav", "video": work / "Mangosteen.mp4",
             "pdf": work / "Mangosteen recipes.pdf"}
    plate = Image.open(SAMPLES / "mangosteen-plate.webp").convert("RGB")
    top = Image.open(SAMPLES / "mangosteen-top.webp").convert("RGB")
    plate.save(files["photo"], quality=92)
    top.save(files["photo2"], quality=92)
    top.crop((560, 120, 1360, 920)).save(files["photo3"], quality=92)  # the opened fruit, closer
    song(files["song"])
    clip(files["video"], files["photo"], files["song"])
    report(files["pdf"], files["photo2"])
    home = work / "home"
    for language in ("en", "ru"):
        target = ROOT / "docs" / "images" / language
        target.mkdir(parents=True, exist_ok=True)
        environment = dict(os.environ, QT_QPA_PLATFORM="offscreen", MANGOSTEEN_NO_PLAYER="1", MANGOSTEEN_SNAPSHOT_DEMO="1", MANGOSTEEN_HOME=str(home),
                           LANGUAGE=language, LC_ALL=f"{language}_{language.upper()}.UTF-8", LANG=f"{language}_{language.upper()}.UTF-8",
                           PYTHONPATH=str(ROOT / "src"))
        for name, what, kinds in WINDOWS:
            output = target / f"{name}.png"
            sized = dict(environment, MANGOSTEEN_SNAPSHOT_HEIGHT=str(HEIGHTS[name])) if name in HEIGHTS else environment
            result = subprocess.run([sys.executable, "-m", "mangosteen", "--snapshot", what, str(output),
                                     *[str(files[k]) for k in kinds]], env=sized, capture_output=True, text=True)
            print(f"{language}/{name}: {'ok' if result.returncode == 0 and output.exists() else 'FAILED ' + result.stderr[-300:]}")
        level_pairs(target, language)
    shutil.rmtree(work, ignore_errors=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
