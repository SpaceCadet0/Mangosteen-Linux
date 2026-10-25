"""Small real files for the tests, generated rather than checked in."""

import math
import os
import struct
import subprocess
import wave

import numpy as np
from PIL import Image, ImageDraw


def photo(path, size=(320, 240), exif_orientation=None, color_seed=3):
    rng = np.random.default_rng(color_seed)
    base = np.zeros((size[1], size[0], 3), dtype=np.uint8)
    for y in range(size[1]):
        base[y, :, 0] = int(255 * y / size[1])
    base[:, :, 1] = np.linspace(0, 255, size[0], dtype=np.uint8)[None, :]
    base[:, :, 2] = rng.integers(0, 60, size=(size[1], size[0]), dtype=np.uint8)
    image = Image.fromarray(base)
    draw = ImageDraw.Draw(image)
    draw.rectangle((20, 20, size[0] // 2, size[1] // 2), outline=(255, 255, 255), width=4)
    draw.text((30, 30), "Mangosteen", fill=(255, 255, 255))
    exif = image.getexif()
    if exif_orientation:
        exif[0x0112] = exif_orientation
    ext = os.path.splitext(path)[1].lower()
    if ext in (".jpg", ".jpeg"):
        image.save(path, quality=90, exif=exif.tobytes(), dpi=(144, 144))
    else:
        image.save(path)
    return path


def tone(path, seconds=1.0, rate=22050, freq=440.0):
    with wave.open(path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        frames = b"".join(struct.pack("<h", int(12000 * math.sin(2 * math.pi * freq * i / rate)))
                          for i in range(int(rate * seconds)))
        w.writeframes(frames)
    return path


def video(path, seconds=1, size="160x120", audio=True):
    command = ["ffmpeg", "-hide_banner", "-nostdin", "-y", "-loglevel", "error", "-f", "lavfi", "-i",
               f"testsrc=duration={seconds}:size={size}:rate=15"]
    if audio:
        command += ["-f", "lavfi", "-i", f"sine=frequency=440:duration={seconds}"]
    command += ["-c:v", "libx264", "-pix_fmt", "yuv420p"]
    if audio:
        command += ["-c:a", "aac", "-shortest"]
    subprocess.run(command + [path], check=True)
    return path
