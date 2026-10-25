"""SRT and WebVTT into each other, and either into plain text."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass

from ..core import text_file
from ..core.file_format import FileFormat


@dataclass(frozen=True)
class Cue:
    start: float
    end: float
    text: str


def convert(input_path: str, target: FileFormat, output: str) -> None:
    cues = parse(text_file.read(input_path))
    if not cues:
        raise ValueError(f"No subtitles found in {os.path.basename(input_path)}.")
    if target is FileFormat.SRT:
        text = to_srt(cues)
    elif target is FileFormat.VTT:
        text = to_vtt(cues)
    elif target is FileFormat.TXT:
        text = "\n".join(strip_tags(c.text) for c in cues)
    else:
        raise ValueError(f"Subtitles cannot be converted to {target.display_name}.")
    text_file.write(output, text + "\n")


def parse(text: str) -> list[Cue]:
    """Parses both SRT and VTT: blocks separated by blank lines, each with a `start --> end` line."""
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    cues: list[Cue] = []
    for block in normalized.split("\n\n"):
        lines = block.split("\n")
        timing = next((i for i, line in enumerate(lines) if "-->" in line), -1)
        if timing < 0:
            continue
        parts = lines[timing].split("-->")
        if len(parts) != 2:
            continue
        start = timestamp(parts[0])
        tail = parts[1].strip().split(" ")
        end = timestamp(tail[0]) if tail else None
        if start is None or end is None:
            continue
        body = "\n".join(line for line in lines[timing + 1:] if line.strip())
        if body:
            cues.append(Cue(start, end, body))
    return cues


def timestamp(raw: str) -> float | None:
    """Accepts HH:MM:SS,mmm, HH:MM:SS.mmm and MM:SS.mmm."""
    fields = raw.strip().replace(",", ".").split(":")
    if not 2 <= len(fields) <= 3:
        return None
    seconds = 0.0
    for field in fields:
        try:
            seconds = seconds * 60 + float(field)
        except ValueError:
            return None
    return seconds


def format_time(time: float, decimal_separator: str) -> str:
    ms = int(round(time * 1000))
    return f"{ms // 3_600_000:02}:{ms // 60_000 % 60:02}:{ms // 1000 % 60:02}{decimal_separator}{ms % 1000:03}"


def to_srt(cues: list[Cue]) -> str:
    return "\n\n".join(
        f"{i + 1}\n{format_time(c.start, ',')} --> {format_time(c.end, ',')}\n{c.text}" for i, c in enumerate(cues))


def to_vtt(cues: list[Cue]) -> str:
    return "WEBVTT\n\n" + "\n\n".join(
        f"{format_time(c.start, '.')} --> {format_time(c.end, '.')}\n{c.text}" for c in cues)


_TAGS = re.compile(r"<[^>]+>|\{\\[^}]*\}")


def strip_tags(text: str) -> str:
    return _TAGS.sub("", text)
