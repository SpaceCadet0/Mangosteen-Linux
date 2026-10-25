"""Timeline operations: timecodes, trim, split, frame export, plus thumbnails and waveforms for the windows."""

from __future__ import annotations

import io
import os
from collections.abc import Callable

from PIL import Image

from ..convert import media
from ..core import external, output_naming
from ..core.cancellation import CancellationToken
from ..core.file_format import FileFormat, detect
from ..core.loc import L

F = FileFormat
LOSSLESS_AUDIO = frozenset({F.WAV, F.AIFF, F.FLAC})


class NothingToDo(Exception):
    def __init__(self) -> None:
        super().__init__(L("Nothing to do."))


def seconds_text(value: float) -> str:
    return f"{max(value, 0):.3f}"


def timecode(seconds: float) -> str:
    """83.45 → "00:01:23.450"."""
    ms = int(round(max(seconds, 0) * 1000))
    return f"{ms // 3_600_000:02d}:{ms // 60_000 % 60:02d}:{ms // 1000 % 60:02d}.{ms % 1000:03d}"


def parse_timecode(text: str) -> float | None:
    """"1:02:03.5", "2:03", "75" or "75,5" as seconds; None when it is not a time."""
    fields = text.strip().replace(",", ".").split(":")
    if not 1 <= len(fields) <= 3:
        return None
    total = 0.0
    for field in fields:
        try:
            value = float(field)
        except ValueError:
            return None
        if value < 0 or value != value or value == float("inf"):
            return None
        total = total * 60 + value
    return total


def output_format(source: FileFormat) -> FileFormat:
    """Tools keep the source format, except M4V (written as MP4) and AAC (written as M4A)."""
    return {F.M4V: F.MP4, F.AAC: F.M4A}.get(source, source)


def require_media(path: str) -> FileFormat:
    source = detect(path)
    if source is None or not source.category.is_media:
        raise ValueError(f"Unknown format of {os.path.basename(path)}.")
    return source


def cut_arguments(target: FileFormat, info: media.MediaInfo, fast: bool) -> list[str]:
    """Codec arguments for a cut. `fast` copies the streams (cuts land on keyframes); otherwise the cut is
    re-encoded and frame-accurate. Lossless audio is always exact, so it is copied."""
    if fast or target in LOSSLESS_AUDIO:
        return ["-map", "0:v?", "-map", "0:a?", "-c", "copy", "-avoid_negative_ts", "make_zero"]
    return media.encode_arguments(target, info)


def _cut(path: str, info: media.MediaInfo, target: FileFormat, start: float, end: float, fast: bool, output: str,
         progress: Callable[[float], None] | None, cancellation: CancellationToken | None) -> None:
    length = max(end - start, 0.01)
    media.run(path, output, ["-t", seconds_text(length), *cut_arguments(target, info, fast)], length,
              extra_input_arguments=["-ss", seconds_text(start)], progress=progress, cancellation=cancellation)


def trim(path: str, start: float, end: float, fast: bool = False, progress: Callable[[float], None] | None = None,
         cancellation: CancellationToken | None = None) -> str:
    """Writes `<name> (trimmed).<ext>` with the part between `start` and `end` seconds."""
    source = require_media(path)
    info = media.probe(path)
    target = output_format(source)

    def produce(output: str) -> None:
        _cut(path, info, target, start, end, fast, output, progress, cancellation)

    return output_naming.write_atomically(os.path.dirname(os.path.abspath(path)),
                                          f"{output_naming.base_name(path)} ({L('trimmed')})", target.extension, produce)


def equal_split_points(duration: float, parts: int) -> list[float]:
    if parts <= 1 or duration <= 0:
        return []
    return [duration * i / parts for i in range(1, parts)]


def split_bounds(points: list[float], duration: float) -> list[float]:
    """0, the cuts that are not too close to the ends (sorted, without repeats), the duration."""
    return [0.0, *sorted({p for p in points if 0.05 < p < duration - 0.05}), duration]


def split(path: str, points: list[float], fast: bool = False, progress: Callable[[float], None] | None = None,
          cancellation: CancellationToken | None = None) -> str:
    """Cuts at `points` (seconds) into `<name> 1.<ext>`, `<name> 2.<ext>`… inside `<name> (parts)`."""
    source = require_media(path)
    info = media.probe(path)
    if not info.duration:
        raise media.MediaError(f"Could not read {os.path.basename(path)}.")
    target = output_format(source)
    bounds = split_bounds(points, info.duration)
    parts = len(bounds) - 1
    base = output_naming.base_name(path)

    def produce(folder: str) -> None:
        os.makedirs(folder)
        for index in range(parts):
            name = f"{base} {output_naming.part_number(index, parts)}.{target.extension}"

            def part_progress(value: float, index: int = index) -> None:
                if progress:
                    progress((index + value) / parts)

            _cut(path, info, target, bounds[index], bounds[index + 1], fast, os.path.join(folder, name), part_progress,
                 cancellation)

    return output_naming.write_atomically(os.path.dirname(os.path.abspath(path)), f"{base} ({L('parts')})", "", produce)


# MARK: Frames


def frame_data(path: str, at: float, max_height: int | None = None) -> bytes:
    """PNG bytes of the frame at `at` seconds."""
    scale = ["-vf", f"scale=-2:'min({max_height},ih)'"] if max_height else []
    return external.run_data("ffmpeg", ["-hide_banner", "-nostdin", "-loglevel", "error", "-ss", seconds_text(at), "-i", path,
                                        "-frames:v", "1", "-an", *scale, "-f", "image2pipe", "-c:v", "png", "-"])


def frame(path: str, at: float, max_height: int | None = None) -> Image.Image:
    data = frame_data(path, at, max_height)
    try:
        image = Image.open(io.BytesIO(data))
        image.load()
    except Exception as error:  # noqa: BLE001 - an empty or broken pipe
        raise media.MediaError(f"Could not read a frame of {os.path.basename(path)}.") from error
    return image


def frame_size(path: str) -> tuple[int, int]:
    """The upright frame size ffmpeg filters see (rotation applied)."""
    return frame(path, 0).size


def _frame_name(base: str, at: float) -> str:
    return f"{base} {L('frame')} {timecode(at).replace(':', '-')}"


def save_frames(path: str, times: list[float]) -> str:
    """One frame as `<name> frame 00-01-23.450.png`; several go into `<name> (frames)`."""
    ordered = sorted(times)
    if not ordered:
        raise NothingToDo()
    base = output_naming.base_name(path)
    directory = os.path.dirname(os.path.abspath(path))
    if len(ordered) == 1:
        def produce_one(output: str) -> None:
            with open(output, "wb") as stream:
                stream.write(frame_data(path, ordered[0]))

        return output_naming.write_atomically(directory, _frame_name(base, ordered[0]), "png", produce_one)

    def produce(folder: str) -> None:
        os.makedirs(folder)
        for at in ordered:
            target = output_naming.unique_path(folder, _frame_name(base, at), "png")
            with open(target, "wb") as stream:
                stream.write(frame_data(path, at))

    return output_naming.write_atomically(directory, f"{base} ({L('frames')})", "", produce)


def thumbnails(path: str, duration: float, count: int, height: int, start: float = 0.0,
               cancelled: Callable[[], bool] | None = None) -> list[Image.Image]:
    """`count` small frames evenly spread over `duration` seconds from `start`; stops early when cancelled."""
    if duration <= 0 or count <= 0:
        return []
    result: list[Image.Image] = []
    for index in range(count):
        if cancelled is not None and cancelled():
            break
        try:
            result.append(frame(path, start + duration * (index + 0.5) / count, height))
        except (media.MediaError, external.ToolFailure):
            continue
    return result


# MARK: Waveform


def peaks(samples, buckets: int) -> list[float]:  # noqa: ANN001
    """The largest absolute sample of each of `buckets` slices that together cover every sample."""
    import numpy as np

    total = len(samples)
    if total == 0 or buckets <= 0:
        return []
    count = min(buckets, total)
    magnitude = np.minimum(np.abs(np.asarray(samples, dtype=np.float32)), 1.0)
    edges = [i * total // count for i in range(count + 1)]
    return [float(magnitude[edges[i]:max(edges[i + 1], edges[i] + 1)].max()) for i in range(count)]


def waveform(path: str, duration: float, buckets: int, audio_filter: str | None = None,
             start: float | None = None) -> list[float]:
    """Peak level (0…1) of `buckets` equal slices of the first audio track mixed to mono. `audio_filter` runs before
    the mono mix (for example `pan=mono|c0=c1` for the right channel). With `start` only `duration` seconds from
    there are read."""
    import numpy as np

    rate = 500 if duration > 600 else 4000
    window = ["-ss", seconds_text(start), "-t", seconds_text(duration)] if start is not None else []
    data = external.run_data("ffmpeg", ["-hide_banner", "-nostdin", "-loglevel", "error", *window, "-i", path,
                                        "-map", "0:a:0", *(["-af", audio_filter] if audio_filter else []),
                                        "-ac", "1", "-ar", str(rate), "-f", "f32le", "-"])
    return peaks(np.frombuffer(data, dtype="<f4"), buckets)
