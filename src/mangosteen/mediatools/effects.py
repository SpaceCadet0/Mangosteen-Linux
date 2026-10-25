"""Speed, joining, video reframing and media compression, all through ffmpeg."""

from __future__ import annotations

import os
import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum

from ..convert import media
from ..core import output_naming
from ..core.cancellation import CancellationToken
from ..core.file_format import Category, FileFormat, detect
from ..core.loc import L
from ..imaging.compress import NotSmaller
from ..imaging.geometry import UnitRect
from . import cut

F = FileFormat
Progress = Callable[[float], None] | None


# MARK: Speed


def atempo_chain(factor: float) -> list[str]:
    """`atempo` takes 0.5…2 per instance, so larger changes are chained."""
    remaining = factor
    filters: list[str] = []
    while remaining > 2:
        filters.append("atempo=2")
        remaining /= 2
    while remaining < 0.5:
        filters.append("atempo=0.5")
        remaining /= 0.5
    filters.append(f"atempo={remaining:.6g}")
    return filters


def speed_label(factor: float) -> str:
    return "×" + f"{round(factor * 100) / 100:g}"


def change_speed(path: str, factor: float, preserve_pitch: bool = True, progress: Progress = None,
                 cancellation: CancellationToken | None = None) -> str:
    """Writes `<name> (speed ×2).<ext>`. With `preserve_pitch` off the sound is resampled like tape."""
    if factor <= 0:
        raise ValueError("The speed must be positive.")
    source = cut.require_media(path)
    info = media.probe(path)
    target = cut.output_format(source)
    video_filters = [f"setpts=PTS/{factor:.6g}"] if info.has_video else []
    if preserve_pitch:
        audio_filters = atempo_chain(factor)
    else:
        rate = info.sample_rate or 48000
        audio_filters = [f"asetrate={int(rate * factor)}", f"aresample={rate}"]
    arguments = media.encode_arguments(target, info, video_filters, audio_filters)
    duration = info.duration / factor if info.duration else None

    def produce(output: str) -> None:
        media.run(path, output, arguments, duration, progress=progress, cancellation=cancellation)

    return output_naming.write_atomically(os.path.dirname(os.path.abspath(path)),
                                          f"{output_naming.base_name(path)} ({L('speed')} {speed_label(factor)})",
                                          target.extension, produce)


# MARK: Join


def join_graph(infos: list[media.MediaInfo]) -> str:
    """Concatenates the clips; the first sets the frame size and rate, the others are fitted inside it with bars, and
    clips without sound get silence."""
    first = infos[0]
    width, height = (first.width or 2) // 2 * 2, (first.height or 2) // 2 * 2
    fps = f"{first.frame_rate or 30.0:.3f}"
    graph: list[str] = []
    pads = ""
    for index, info in enumerate(infos):
        graph.append(f"[{index}:v:0]scale={width}:{height}:force_original_aspect_ratio=decrease,"
                     f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2,setsar=1,fps={fps},format=yuv420p[v{index}]")
        if info.has_audio:
            graph.append(f"[{index}:a:0]aresample=48000,aformat=sample_fmts=fltp:channel_layouts=stereo[a{index}]")
        else:
            graph.append(f"anullsrc=channel_layout=stereo:sample_rate=48000,atrim=0:{info.duration or 0.0:.3f},"
                         f"aformat=sample_fmts=fltp[a{index}]")
        pads += f"[v{index}][a{index}]"
    graph.append(f"{pads}concat=n={len(infos)}:v=1:a=1[v][a]")
    return ";".join(graph)


def join(paths: list[str], progress: Progress = None, cancellation: CancellationToken | None = None) -> str:
    """Writes `Joined.mp4` next to the first clip."""
    if len(paths) < 2:
        raise cut.NothingToDo()
    infos = [media.probe(p) for p in paths]
    for path, info in zip(paths, infos):
        if not info.has_video:
            raise media.no_video(path)
    arguments = [a for p in paths for a in ("-i", p)]
    arguments += ["-filter_complex", join_graph(infos), "-map", "[v]", "-map", "[a]", "-c:v", "libx264", "-preset", "medium",
                  "-crf", "20", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart"]
    total = sum(i.duration or 0.0 for i in infos)

    def produce(output: str) -> None:
        media.run_ffmpeg(arguments, output, total, progress, cancellation)

    return output_naming.write_atomically(os.path.dirname(os.path.abspath(paths[0])), L("Joined"), "mp4", produce)


# MARK: Crop


def crop_video(path: str, rect: UnitRect, output_size: tuple[int, int] | None = None, progress: Progress = None,
               cancellation: CancellationToken | None = None) -> str:
    """Writes `<name> (cropped).<ext>`; `rect` is normalised against the upright frame."""
    source = cut.require_media(path)
    if source.category is not Category.VIDEO:
        raise media.no_video(path)
    info = media.probe(path)
    width, height = cut.frame_size(path)  # ffmpeg turns frames upright before filtering
    pixels = rect.to_pixels(width, height)
    filters = [f"crop={max(pixels.width // 2 * 2, 2)}:{max(pixels.height // 2 * 2, 2)}:{pixels.x}:{pixels.y}"]
    if output_size and output_size[0] >= 2 and output_size[1] >= 2:
        filters.append(f"scale={output_size[0] // 2 * 2}:{output_size[1] // 2 * 2}")
    target = cut.output_format(source)
    arguments = media.encode_arguments(target, info, filters)

    def produce(output: str) -> None:
        media.run(path, output, arguments, info.duration, progress=progress, cancellation=cancellation)

    return output_naming.write_atomically(os.path.dirname(os.path.abspath(path)),
                                          f"{output_naming.base_name(path)} ({L('cropped')})", target.extension, produce)


# MARK: Compress


class MediaQuality(Enum):
    HIGH = "high"
    BALANCED = "balanced"
    SMALL = "small"

    @property
    def title(self) -> str:
        return {MediaQuality.HIGH: L("High quality"), MediaQuality.BALANCED: L("Balanced"),
                MediaQuality.SMALL: L("Smallest size")}[self]

    @property
    def h264_crf(self) -> int:
        return {MediaQuality.HIGH: 23, MediaQuality.BALANCED: 27, MediaQuality.SMALL: 31}[self]

    @property
    def hevc_crf(self) -> int:
        return {MediaQuality.HIGH: 26, MediaQuality.BALANCED: 30, MediaQuality.SMALL: 34}[self]

    @property
    def audio_kbps(self) -> int:
        return {MediaQuality.HIGH: 160, MediaQuality.BALANCED: 128, MediaQuality.SMALL: 80}[self]


@dataclass
class MediaCompression:
    quality: MediaQuality = MediaQuality.BALANCED
    max_height: int | None = None  # frame height limit
    hevc: bool = False
    use_target_size: bool = False
    target_bytes: int = 25_000_000


LOSSY_AUDIO = frozenset({F.MP3, F.M4A, F.OGG, F.OPUS, F.WMA})


def compressed_format(source: FileFormat) -> FileFormat:
    if source.category is Category.VIDEO:
        return source if source in (F.MP4, F.MOV, F.MKV) else F.MP4
    return source if source in LOSSY_AUDIO else F.M4A


def compression_arguments(source: FileFormat, duration: float | None, settings: MediaCompression) -> list[str]:
    seconds = max(duration or 1.0, 0.1)
    audio_kbps = settings.quality.audio_kbps
    if source.category is Category.AUDIO:
        if settings.use_target_size:
            audio_kbps = int(settings.target_bytes * 8 / seconds / 1000 * 0.95)
        audio_kbps = min(max(audio_kbps, 24), 320)
        codec = {F.MP3: ["-c:a", "libmp3lame"], F.OGG: ["-c:a", "vorbis", "-strict", "-2", "-ac", "2"],
                 F.OPUS: ["-c:a", "libopus"], F.WMA: ["-c:a", "wmav2"]}.get(compressed_format(source), ["-c:a", "aac"])
        return ["-vn", *codec, "-b:a", f"{audio_kbps}k"]
    filters = []
    if settings.max_height:
        filters.append(f"scale=-2:'min({settings.max_height},ih)'")
    filters.append("scale=trunc(iw/2)*2:trunc(ih/2)*2")
    arguments = ["-map", "0:v:0", "-map", "0:a?", "-vf", ",".join(filters), "-pix_fmt", "yuv420p"]
    arguments += (["-c:v", "libx265", "-preset", "medium", "-tag:v", "hvc1"] if settings.hevc
                  else ["-c:v", "libx264", "-preset", "medium"])
    if settings.use_target_size:
        audio_kbps = 96
        video_kbps = max(int(settings.target_bytes * 8 / seconds / 1000 * 0.93) - audio_kbps, 80)
        arguments += ["-b:v", f"{video_kbps}k", "-maxrate", f"{video_kbps * 3 // 2}k", "-bufsize", f"{video_kbps * 2}k"]
    else:
        arguments += ["-crf", str(settings.quality.hevc_crf if settings.hevc else settings.quality.h264_crf)]
    arguments += ["-c:a", "aac", "-b:a", f"{audio_kbps}k"]
    if compressed_format(source) is F.MP4:
        arguments += ["-movflags", "+faststart"]
    return arguments


def estimate_compressed_size(path: str, settings: MediaCompression, cancellation: CancellationToken | None = None) -> int:
    """Predicted output size. Video is measured by encoding a short sample from the middle with the same settings,
    audio follows from the bitrate, and target-size mode returns the target."""
    source = cut.require_media(path)
    info = media.probe(path)
    duration = info.duration or 0.0
    if settings.use_target_size:
        return settings.target_bytes
    if source.category is Category.AUDIO:
        return int(min(max(settings.quality.audio_kbps, 24), 320) * 1000 / 8 * duration)
    length = min(duration, 6.0)
    if length <= 0:
        raise media.MediaError(f"Could not read {os.path.basename(path)}.")
    start = max(0.0, duration / 2 - length / 2)
    with tempfile.TemporaryDirectory(prefix="mangosteen-") as folder:
        sample = os.path.join(folder, "sample." + compressed_format(source).extension)
        media.run_ffmpeg(["-ss", cut.seconds_text(start), "-t", cut.seconds_text(length), "-i", path,
                          *compression_arguments(source, info.duration, settings)], sample, length, None, cancellation)
        return int(os.path.getsize(sample) * duration / length)


def compress(path: str, settings: MediaCompression | None = None, progress: Progress = None,
             cancellation: CancellationToken | None = None) -> str:
    """Writes `<name> (compressed).<ext>`; a result that is not smaller than the original is refused."""
    settings = settings or MediaCompression()
    source = cut.require_media(path)
    info = media.probe(path)
    if source.category is Category.VIDEO and not info.has_video:
        raise media.no_video(path)
    target = compressed_format(source)

    def produce(output: str) -> None:
        media.run(path, output, compression_arguments(source, info.duration, settings), info.duration,
                  progress=progress, cancellation=cancellation)

    result = output_naming.write_atomically(os.path.dirname(os.path.abspath(path)),
                                            f"{output_naming.base_name(path)} ({L('compressed')})", target.extension, produce)
    original, size = os.path.getsize(path), os.path.getsize(result)
    if size >= original:
        os.remove(result)
        raise NotSmaller(original, size)
    return result


__all__ = ["atempo_chain", "change_speed", "join", "crop_video", "compress", "MediaCompression", "MediaQuality",
           "estimate_compressed_size", "detect"]
