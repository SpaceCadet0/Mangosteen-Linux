"""Loudness, channel mixing, bleeping and audio visualisation. For a video only the sound changes; the picture is
copied as it is."""

from __future__ import annotations

import json
import os
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import Enum

from ..convert import media
from ..core import external, output_naming
from ..core.cancellation import CancellationToken
from ..core.file_format import Category, FileFormat
from ..core.loc import L
from ..imaging.compose import RGBA
from . import cut

F = FileFormat
Progress = Callable[[float], None] | None


def hex_color(color: RGBA) -> str:
    return f"0x{int(color.red * 255):02X}{int(color.green * 255):02X}{int(color.blue * 255):02X}"


def number(value: float) -> str:
    return f"{value:.2f}"


def audio_codec_for_video(target: FileFormat) -> list[str]:
    return {F.WEBM: ["-c:a", "libopus", "-b:a", "160k"], F.AVI: ["-c:a", "libmp3lame", "-q:a", "2"],
            F.WMV: ["-c:a", "wmav2", "-b:a", "192k"]}.get(target, ["-c:a", "aac", "-b:a", "192k"])


def _sound_arguments(path: str, audio_filter: str | None, graph: str | None) -> list[str]:
    arguments = ["-i", path]
    if graph:
        return [*arguments, "-filter_complex", graph, "-map", "[a]"]
    arguments += ["-map", "0:a:0"]
    if audio_filter:
        arguments += ["-af", audio_filter]
    return arguments


def process_audio(path: str, suffix: str, audio_filter: str | None = None, graph: str | None = None,
                  progress: Progress = None, cancellation: CancellationToken | None = None) -> str:
    """Re-encodes the sound of `path` through a simple `-af` chain or a `-filter_complex` graph that ends in `[a]`,
    and writes `<name> (suffix).<ext>` next to it."""
    source = cut.require_media(path)
    info = media.probe(path)
    if not info.has_audio:
        raise media.no_audio(path)
    target = cut.output_format(source)
    arguments = _sound_arguments(path, audio_filter, graph)
    if source.category is Category.VIDEO and info.has_video:
        arguments += ["-map", "0:v:0", "-c:v", "copy", *audio_codec_for_video(target)]
    else:
        arguments += [a for a in media.encode_arguments(target, info) if a != "-vn"]
    arguments += ["-map_metadata", "0"]

    def produce(output: str) -> None:
        media.run_ffmpeg(arguments, output, info.duration, progress, cancellation)

    return output_naming.write_atomically(os.path.dirname(os.path.abspath(path)),
                                          f"{output_naming.base_name(path)} ({suffix})", target.extension, produce)


def render_preview(path: str, output: str, audio_filter: str | None = None, graph: str | None = None,
                   start: float = 0.0, length: float | None = None, cancellation: CancellationToken | None = None) -> None:
    """The processed sound only, for listening before saving. A graph is given the whole file, so with a window the
    first `start` seconds are cut after processing."""
    window = ["-ss", cut.seconds_text(start)] if start > 0 else []
    arguments = [*_sound_arguments(path, audio_filter, graph), "-vn", "-c:a", "aac", "-b:a", "160k"]
    if graph:
        arguments = [*arguments, *window, *(["-t", cut.seconds_text(length)] if length else [])]
    else:
        arguments = [*window, *arguments, *(["-t", cut.seconds_text(length)] if length else [])]
    media.run_ffmpeg(arguments, output, None, None, cancellation)


# MARK: Loudness


@dataclass
class LoudnessTarget:
    integrated: float = -14.0  # LUFS
    true_peak: float = -1.0    # dBTP
    range: float = 11.0        # LU


@dataclass
class LoudnessMeasurement:
    integrated: float
    true_peak: float
    range: float
    threshold: float
    offset: float


def loudnorm_filter(target: LoudnessTarget) -> str:
    return f"loudnorm=I={number(target.integrated)}:TP={number(target.true_peak)}:LRA={number(target.range)}"


def measure_loudness(path: str, target: LoudnessTarget | None = None) -> LoudnessMeasurement:
    """First loudnorm pass: measures the file against `target`."""
    target = target or LoudnessTarget()
    text = external.run("ffmpeg", ["-hide_banner", "-nostdin", "-i", path, "-map", "0:a:0", "-vn", "-af",
                                   loudnorm_filter(target) + ":print_format=json", "-f", "null", "-"])
    found = re.search(r"\{[^{}]*\}\s*\Z", text.strip())
    if not found:
        raise media.MediaError(f"Could not measure the loudness of {os.path.basename(path)}.")
    data = json.loads(found.group(0))

    def value(key: str) -> float:
        try:
            result = float(data[key])
        except (KeyError, ValueError, TypeError):
            return -70.0
        return result if result == result and abs(result) != float("inf") else -70.0

    return LoudnessMeasurement(value("input_i"), value("input_tp"), value("input_lra"), value("input_thresh"),
                               value("target_offset"))


def normalize(path: str, target: LoudnessTarget | None = None, progress: Progress = None,
              cancellation: CancellationToken | None = None) -> str:
    """Two-pass EBU R128 normalisation; writes `<name> (volume).<ext>`."""
    target = target or LoudnessTarget()
    info = media.probe(path)
    if not info.has_audio:
        raise media.no_audio(path)
    measured = measure_loudness(path, target)
    if cancellation is not None:
        cancellation.throw_if_cancelled()
    rate = info.sample_rate or 48000
    audio_filter = (loudnorm_filter(target) + f":measured_I={number(measured.integrated)}"
                    f":measured_TP={number(measured.true_peak)}:measured_LRA={number(measured.range)}"
                    f":measured_thresh={number(measured.threshold)}:offset={number(measured.offset)}:linear=true"
                    f",aresample={rate}")  # loudnorm works at 192 kHz internally
    return process_audio(path, L("volume"), audio_filter=audio_filter, progress=progress, cancellation=cancellation)


# MARK: Channels


class Layout(Enum):
    STEREO = "stereo"
    MONO = "mono"


@dataclass
class ChannelSettings:
    layout: Layout = Layout.STEREO
    left: float = 1.0   # 0…2
    right: float = 1.0  # 0…2
    swap: bool = False


def channel_filter(settings: ChannelSettings, source_channels: int) -> str:
    """A `pan` filter; a mono source feeds both sides from its single channel."""
    left_source = "c0" if source_channels < 2 or not settings.swap else "c1"
    right_source = "c0" if source_channels < 2 or settings.swap else "c1"
    if settings.layout is Layout.STEREO:
        return f"pan=stereo|c0={number(settings.left)}*{left_source}|c1={number(settings.right)}*{right_source}"
    if source_channels < 2:  # ffmpeg refuses to reference the same channel twice in one output
        return f"pan=mono|c0={number((settings.left + settings.right) / 2)}*c0"
    return f"pan=mono|c0={number(settings.left / 2)}*{left_source}+{number(settings.right / 2)}*{right_source}"


def convert_channels(path: str, settings: ChannelSettings, progress: Progress = None,
                     cancellation: CancellationToken | None = None) -> str:
    channels = media.probe(path).audio_channels or 2
    return process_audio(path, L("channels"), audio_filter=channel_filter(settings, channels), progress=progress,
                         cancellation=cancellation)


# MARK: Bleep


def bleep_graph(ranges: list[tuple[float, float]], frequency: float, volume: float, duration: float) -> str:
    """The source is muted and a sine tone is mixed in during the ranges."""
    condition = "+".join(f"between(t,{cut.seconds_text(a)},{cut.seconds_text(b)})" for a, b in ranges)
    length = cut.seconds_text(max(duration, 0.1))
    return (f"[0:a:0]aformat=sample_fmts=fltp:sample_rates=48000,volume=0:enable='{condition}'[muted];"
            f"sine=frequency={int(frequency)}:sample_rate=48000:duration={length},"
            f"aformat=sample_fmts=fltp:channel_layouts=mono,volume={number(volume)},volume=0:enable='not({condition})'[tone];"
            "[muted][tone]amix=inputs=2:duration=first:normalize=0[a]")


def bleep(path: str, ranges: list[tuple[float, float]], frequency: float = 1000.0, volume: float = 0.3,
          progress: Progress = None, cancellation: CancellationToken | None = None) -> str:
    """Replaces each range with a tone; writes `<name> (bleeped).<ext>`."""
    if not ranges:
        raise cut.NothingToDo()
    duration = media.probe(path).duration or 0.0
    return process_audio(path, L("bleeped"), graph=bleep_graph(ranges, frequency, volume, duration), progress=progress,
                         cancellation=cancellation)


# MARK: Visualizer


class VisualizerStyle(Enum):
    WAVEFORM = "waveform"
    SPECTRUM = "spectrum"
    STILL = "still"


class Orientation(Enum):
    LANDSCAPE = "landscape"
    PORTRAIT = "portrait"
    SQUARE = "square"

    @property
    def size(self) -> tuple[int, int]:
        return {Orientation.LANDSCAPE: (1920, 1080), Orientation.PORTRAIT: (1080, 1920),
                Orientation.SQUARE: (1080, 1080)}[self]


@dataclass
class VisualizerSettings:
    style: VisualizerStyle = VisualizerStyle.WAVEFORM
    orientation: Orientation = Orientation.LANDSCAPE
    wave_color: RGBA = field(default_factory=lambda: RGBA(1.0, 0.62, 0.2))
    background: RGBA = field(default_factory=lambda: RGBA(0.08, 0.08, 0.1))
    image: str | None = None


def visualizer_arguments(path: str, settings: VisualizerSettings, duration: float, preview: float | None = None) -> list[str]:
    """Inputs and the filter graph; `preview` renders 1.5 s around that moment instead of the whole file."""
    width, height = settings.orientation.size
    length = cut.seconds_text(duration if preview is None else 1.5)
    arguments: list[str] = []
    if preview is not None:
        arguments += ["-ss", cut.seconds_text(max(preview - 0.75, 0)), "-t", length]
    arguments += ["-i", path]
    if settings.image:
        arguments += ["-loop", "1", "-framerate", "30", "-t", length, "-i", settings.image]
        backdrop = (f"[1:v]scale={width}:{height}:force_original_aspect_ratio=increase,crop={width}:{height},"
                    "setsar=1,format=yuv420p[bg]")
    else:
        backdrop = f"color=c={hex_color(settings.background)}:s={width}x{height}:r=30:d={length},format=yuv420p[bg]"
    wave_height = int(height * (0.22 if settings.orientation is Orientation.PORTRAIT else 0.4)) // 2 * 2
    # The picture follows a mono, level-evened copy so quiet recordings still move; the sound is mapped from the input.
    listening = "[0:a:0]aformat=channel_layouts=mono,dynaudnorm=f=150:g=15,"
    colors = hex_color(settings.wave_color)
    overlay = "[bg][w]overlay=(W-w)/2:(H-h)/2:shortest=1,format=yuv420p[v]"
    if settings.style is VisualizerStyle.WAVEFORM:
        graph = (f"{backdrop};{listening}showwaves=s={width}x{wave_height}:mode=cline:scale=sqrt:draw=full:rate=30:"
                 f"colors={colors},format=yuva420p[w];{overlay}")
    elif settings.style is VisualizerStyle.SPECTRUM:
        graph = (f"{backdrop};{listening}showfreqs=s={width}x{wave_height}:mode=bar:ascale=sqrt:fscale=log:win_size=2048:"
                 f"colors={colors},fps=30,format=yuva420p[w];{overlay}")
    else:
        graph = f"{backdrop};[bg]null[v]"
    return [*arguments, "-filter_complex", graph, "-map", "[v]"]


def visualize(path: str, settings: VisualizerSettings, progress: Progress = None,
              cancellation: CancellationToken | None = None) -> str:
    """Writes `<name> (visualization).mp4` with the sound and the chosen picture."""
    info = media.probe(path)
    if not info.has_audio or not info.duration:
        raise media.no_audio(path)
    arguments = [*visualizer_arguments(path, settings, info.duration), "-map", "0:a:0", "-c:v", "libx264", "-preset", "medium",
                 "-crf", "20", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k", "-shortest", "-movflags", "+faststart"]

    def produce(output: str) -> None:
        media.run_ffmpeg(arguments, output, info.duration, progress, cancellation)

    return output_naming.write_atomically(os.path.dirname(os.path.abspath(path)),
                                          f"{output_naming.base_name(path)} ({L('visualization')})", "mp4", produce)


def visualizer_frame(path: str, settings: VisualizerSettings, duration: float, at: float):  # noqa: ANN201
    """One frame of the visualiser at `at` seconds."""
    import io

    from PIL import Image

    data = external.run_data("ffmpeg", ["-hide_banner", "-nostdin", "-loglevel", "error",
                                        *visualizer_arguments(path, settings, duration, at),
                                        "-ss", "0.75", "-frames:v", "1", "-f", "image2pipe", "-c:v", "png", "-"])
    image = Image.open(io.BytesIO(data))
    image.load()
    return image


__all__ = ["process_audio", "normalize", "convert_channels", "bleep", "visualize", "Category"]
