"""Hides areas of a video, each for its own time range, with a solid colour, blur or large pixels."""

from __future__ import annotations

import io
import os
from collections.abc import Callable
from dataclasses import dataclass

from PIL import Image

from ..convert import media
from ..core import external, output_naming
from ..core.cancellation import CancellationToken
from ..core.file_format import Category, FileFormat
from ..core.loc import L
from ..imaging.compose import RGBA
from ..imaging.geometry import UnitRect
from ..imaging.redact import RedactionStyle
from . import cut
from .audio import hex_color

F = FileFormat


@dataclass(frozen=True)
class Region:
    rect: UnitRect  # normalised against the upright frame
    start: float
    end: float


def filter_graph(regions: list[Region], style: RedactionStyle, color: RGBA, frame_size: tuple[int, int]) -> str:
    """The filter graph; the result is labelled `[v]`."""
    chains: list[str] = []
    current = "[0:v]"
    for index, region in enumerate(regions):
        pixels = region.rect.to_pixels(*frame_size)
        x, y = pixels.x // 2 * 2, pixels.y // 2 * 2
        width, height = max(pixels.width // 2 * 2, 2), max(pixels.height // 2 * 2, 2)
        enable = f"between(t,{cut.seconds_text(region.start)},{cut.seconds_text(region.end)})"
        output = f"[v{index}]"
        if style is RedactionStyle.SOLID:
            chains.append(f"{current}drawbox=x={x}:y={y}:w={width}:h={height}:color={hex_color(color)}@1:t=fill:"
                          f"enable='{enable}'{output}")
        else:
            # Pixelating first destroys the detail, so even the blur cannot be undone.
            block = max(max(width, height) // 10, 4)
            effect = (f"crop={width}:{height}:{x}:{y},scale={max(width // block, 2)}:{max(height // block, 2)},"
                      f"scale={width}:{height}:flags=neighbor")
            if style is RedactionStyle.BLUR:
                effect += f",gblur=sigma={block * 0.9:.1f}"
            chains.append(f"{current}split[main{index}][part{index}]")
            chains.append(f"[part{index}]{effect}[hidden{index}]")
            chains.append(f"[main{index}][hidden{index}]overlay={x}:{y}:enable='{enable}'{output}")
        current = output
    chains.append(f"{current}format=yuv420p[v]")
    return ";".join(chains)


def video_codec_arguments(target: FileFormat) -> list[str]:
    return {F.WEBM: ["-c:v", "libvpx-vp9", "-crf", "30", "-b:v", "0", "-row-mt", "1", "-deadline", "good", "-cpu-used", "4"],
            F.AVI: ["-c:v", "mpeg4", "-q:v", "2"], F.WMV: ["-c:v", "wmv2", "-q:v", "2"]}.get(
        target, ["-c:v", "libx264", "-preset", "medium", "-crf", "18"])


def redact(path: str, regions: list[Region], style: RedactionStyle, color: RGBA,
           progress: Callable[[float], None] | None = None, cancellation: CancellationToken | None = None) -> str:
    """Writes `<name> (hidden).<ext>`; the sound is copied unchanged."""
    source = cut.require_media(path)
    if source.category is not Category.VIDEO:
        raise media.no_video(path)
    if not regions:
        raise cut.NothingToDo()
    info = media.probe(path)
    target = cut.output_format(source)
    graph = filter_graph(regions, style, color, cut.frame_size(path))
    arguments = ["-i", path, "-filter_complex", graph, "-map", "[v]", "-map", "0:a?", *video_codec_arguments(target),
                 "-c:a", "copy"]
    if target is F.MP4:
        arguments += ["-movflags", "+faststart"]

    def produce(output: str) -> None:
        media.run_ffmpeg(arguments, output, info.duration, progress, cancellation)

    return output_naming.write_atomically(os.path.dirname(os.path.abspath(path)),
                                          f"{output_naming.base_name(path)} ({L('hidden')})", target.extension, produce)


def preview_frame(path: str, regions: list[Region], style: RedactionStyle, color: RGBA, frame_size: tuple[int, int],
                  at: float) -> Image.Image:
    """The processed frame at `at` seconds, to check the result before saving."""
    graph = filter_graph(regions, style, color, frame_size)
    # -copyts keeps the original timestamps so the time ranges in the graph still match.
    data = external.run_data("ffmpeg", ["-hide_banner", "-nostdin", "-loglevel", "error", "-ss", cut.seconds_text(at),
                                        "-copyts", "-i", path, "-filter_complex", graph, "-map", "[v]", "-frames:v", "1",
                                        "-f", "image2pipe", "-c:v", "png", "-"])
    image = Image.open(io.BytesIO(data))
    image.load()
    return image
