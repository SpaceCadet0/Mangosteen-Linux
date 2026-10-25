"""Video and audio conversion through ffmpeg. Container changes reuse the existing streams when the target
supports their codecs (fast and lossless); otherwise the streams are re-encoded."""

from __future__ import annotations

import functools
import json
import os
import re
from collections.abc import Callable
from dataclasses import dataclass

from ..core import external, loc
from ..core.cancellation import Cancelled, CancellationToken
from ..core.file_format import Category, FileFormat


@dataclass
class MediaInfo:
    """What ffprobe reports about a media file."""

    duration: float | None = None
    video_codec: str | None = None
    audio_codec: str | None = None
    width: int | None = None
    height: int | None = None
    audio_channels: int | None = None
    frame_rate: float | None = None
    sample_rate: int | None = None

    @property
    def has_video(self) -> bool:
        return self.video_codec is not None

    @property
    def has_audio(self) -> bool:
        return self.audio_codec is not None


class MediaError(Exception):
    pass


def no_audio(path: str) -> MediaError:
    return MediaError(loc.fmt("“{0}” has no sound track.", os.path.basename(path)))


def no_video(path: str) -> MediaError:
    return MediaError(loc.fmt("“{0}” has no video.", os.path.basename(path)))


# MARK: Probing


def probe(path: str) -> MediaInfo:
    text = external.run("ffprobe", ["-v", "error", "-print_format", "json", "-show_format", "-show_streams", path])
    try:
        data = json.loads(text)
    except ValueError as error:
        raise MediaError(f"Could not read {os.path.basename(path)}.") from error
    streams = data.get("streams") or []
    # Cover art is reported as a video stream; it is not a picture track.
    video = next((s for s in streams if s.get("codec_type") == "video"
                  and (s.get("disposition") or {}).get("attached_pic") != 1), None)
    audio = next((s for s in streams if s.get("codec_type") == "audio"), None)
    try:
        duration = float((data.get("format") or {}).get("duration"))
    except (TypeError, ValueError):
        duration = None
    # MP3 without a VBR header has its duration guessed from the bitrate, which can be off by tens of seconds;
    # counting the frames is exact and takes milliseconds.
    if video is None and audio is not None and audio.get("codec_name") == "mp3":
        counted = _counted_duration(path)
        if counted:
            duration = counted
    try:
        sample_rate = int(audio["sample_rate"]) if audio and audio.get("sample_rate") else None
    except (TypeError, ValueError):
        sample_rate = None
    return MediaInfo(
        duration=duration,
        video_codec=video.get("codec_name") if video else None,
        audio_codec=audio.get("codec_name") if audio else None,
        width=video.get("width") if video else None,
        height=video.get("height") if video else None,
        audio_channels=audio.get("channels") if audio else None,
        frame_rate=(rate(video.get("avg_frame_rate")) or rate(video.get("r_frame_rate"))) if video else None,
        sample_rate=sample_rate,
    )


def _counted_duration(path: str) -> float | None:
    """The audio length from the packets themselves (stream copy to nowhere, nothing is decoded)."""
    try:
        log = external.run("ffmpeg", ["-hide_banner", "-nostdin", "-v", "error", "-stats", "-i", path, "-map", "0:a:0",
                                      "-c", "copy", "-f", "null", "-"])
    except (external.ToolFailure, external.ToolMissing):
        return None
    matches = re.findall(r"time=(\d+):(\d+):(\d+(?:\.\d+)?)", log.replace("\r", "\n"))
    if not matches:
        return None
    hours, minutes, seconds = matches[-1]
    total = float(hours) * 3600 + float(minutes) * 60 + float(seconds)
    return total if total > 0 else None


def rate(fraction: str | None) -> float | None:
    """"30000/1001" → 29.97; None for "0/0" or garbage."""
    if not fraction:
        return None
    parts = fraction.split("/")
    if len(parts) != 2:
        return None
    try:
        numerator, denominator = float(parts[0]), float(parts[1])
    except ValueError:
        return None
    return numerator / denominator if numerator > 0 and denominator > 0 else None


@functools.lru_cache(maxsize=1)
def _encoders() -> frozenset[str]:
    try:
        text = external.run("ffmpeg", ["-hide_banner", "-encoders"])
    except (external.ToolFailure, external.ToolMissing):
        return frozenset()
    return frozenset(m.group(1) for m in re.finditer(r"^\s[VAS][A-Z.]{5}\s+(\S+)", text, re.MULTILINE))


def has_encoder(name: str) -> bool:
    return name in _encoders()


# MARK: Conversion


def convert(input_path: str, target: FileFormat, output: str, progress: Callable[[float], None] | None = None,
            cancellation: CancellationToken | None = None) -> None:
    """Converts `input_path` to `target`, reporting progress from 0 to 1."""
    info = probe(input_path)
    if target.category is Category.AUDIO and not info.has_audio:
        raise no_audio(input_path)
    if target.category is Category.VIDEO and not info.has_video:
        raise no_video(input_path)

    copy = remux_arguments(target, info)
    if copy is not None:
        try:
            run(input_path, output, copy, info.duration, progress=progress, cancellation=cancellation)
            return
        except Cancelled:
            raise
        except external.ToolFailure:
            # Some streams cannot be copied into this container after all; re-encode instead.
            try:
                os.remove(output)
            except OSError:
                pass
    run(input_path, output, encode_arguments(target, info), info.duration, progress=progress, cancellation=cancellation)


def remux_arguments(target: FileFormat, info: MediaInfo) -> list[str] | None:
    """Stream-copy arguments when the target container accepts the source codecs, otherwise None."""
    video, audio = info.video_codec, info.audio_codec

    def audio_fits(codecs: set[str]) -> bool:
        return audio is None or audio in codecs

    F = FileFormat
    if target in (F.MP4, F.MOV):
        if video not in ("h264", "hevc") or not audio_fits({"aac", "mp3", "alac"}):
            return None
        arguments = ["-map", "0:v:0", "-map", "0:a?", "-c", "copy"]
        if video == "hevc":
            arguments += ["-tag:v", "hvc1"]
        if target is F.MP4:
            arguments += ["-movflags", "+faststart"]
        return arguments
    if target is F.MKV:
        return ["-map", "0:v:0", "-map", "0:a?", "-map", "0:s?", "-c", "copy"] if info.has_video else None
    if target is F.WEBM:
        if video not in ("vp8", "vp9", "av1") or not audio_fits({"opus", "vorbis"}):
            return None
        return ["-map", "0:v:0", "-map", "0:a?", "-c", "copy"]
    audio_only = {
        F.M4A: {"aac", "alac"}, F.OPUS: {"opus"}, F.OGG: {"vorbis", "opus"}, F.FLAC: {"flac"}, F.MP3: {"mp3"},
    }
    if target in audio_only:
        return ["-vn", "-c:a", "copy"] if (audio or "") in audio_only[target] else None
    return None


def encode_arguments(target: FileFormat, info: MediaInfo, video_filters: list[str] | None = None,
                     audio_filters: list[str] | None = None) -> list[str]:
    """Re-encoding arguments for each target. `video_filters` run before the even-size scaling; `audio_filters`
    apply when there is an audio track."""
    audio = ["-af", ",".join(audio_filters)] if info.has_audio and audio_filters else []
    return _codec_arguments(target, info, video_filters or []) + audio


def _codec_arguments(target: FileFormat, info: MediaInfo, video_filters: list[str]) -> list[str]:
    F = FileFormat
    # H.264 and the other 4:2:0 encoders need even dimensions.
    even = ["-vf", ",".join([*video_filters, "scale=trunc(iw/2)*2:trunc(ih/2)*2"])]
    h264 = ["-c:v", "libx264", "-preset", "medium", "-crf", "20", "-pix_fmt", "yuv420p", *even]
    aac = ["-c:a", "aac", "-b:a", "192k"]
    maps = ["-map", "0:v:0", "-map", "0:a?"]
    if target is F.MP4:
        return [*maps, *h264, *aac, "-movflags", "+faststart"]
    if target in (F.MOV, F.MKV):
        return [*maps, *h264, *aac]
    if target is F.WEBM:
        return [*maps, "-c:v", "libvpx-vp9", "-crf", "32", "-b:v", "0", "-row-mt", "1", "-deadline", "good",
                "-cpu-used", "4", "-pix_fmt", "yuv420p", "-c:a", "libopus", "-b:a", "128k", *even]
    if target is F.AVI:
        return [*maps, "-c:v", "mpeg4", "-q:v", "3", "-c:a", "libmp3lame", "-q:a", "3", *even]
    if target is F.WMV:
        return [*maps, "-c:v", "wmv2", "-q:v", "3", "-c:a", "wmav2", "-b:a", "192k", *even]
    if target is F.GIF:
        prefix = "".join(f + "," for f in video_filters)
        return ["-an", "-vf", prefix + "fps=15,scale='min(720,iw)':-2:flags=lanczos,split[a][b];"
                "[a]palettegen=stats_mode=diff[p];[b][p]paletteuse=dither=bayer:bayer_scale=4", "-loop", "0"]
    if target is F.MP3:
        return ["-vn", "-c:a", "libmp3lame", "-q:a", "2"]
    if target is F.M4A:
        return ["-vn", "-c:a", "aac", "-b:a", "256k"]
    if target is F.WAV:
        return ["-vn", "-c:a", "pcm_s16le"]
    if target is F.AIFF:
        return ["-vn", "-c:a", "pcm_s16be"]
    if target is F.FLAC:
        return ["-vn", "-c:a", "flac"]
    if target is F.OGG:
        if has_encoder("libvorbis"):
            return ["-vn", "-c:a", "libvorbis", "-q:a", "5"]
        # The built-in Vorbis encoder is marked experimental and only supports stereo.
        return ["-vn", "-c:a", "vorbis", "-strict", "-2", "-ac", "2", "-b:a", "192k"]
    if target is F.OPUS:
        return ["-vn", "-c:a", "libopus", "-b:a", "160k"]
    if target is F.WMA:
        return ["-vn", "-c:a", "wmav2", "-b:a", "192k"]
    return []


def run(input_path: str, output: str, codec_arguments: list[str], duration: float | None,
        extra_input_arguments: list[str] | None = None, progress: Callable[[float], None] | None = None,
        cancellation: CancellationToken | None = None) -> None:
    """Runs ffmpeg with progress reporting. `codec_arguments` go between the input and the output."""
    run_ffmpeg([*(extra_input_arguments or []), "-i", input_path, *codec_arguments, "-map_metadata", "0"], output,
               duration, progress, cancellation)


def run_ffmpeg(arguments: list[str], output: str, duration: float | None,
               progress: Callable[[float], None] | None = None, cancellation: CancellationToken | None = None) -> None:
    """Runs ffmpeg with `arguments` (inputs, filters, codecs) and progress reporting against `duration`."""
    if cancellation is not None:
        cancellation.throw_if_cancelled()
    full = ["-hide_banner", "-nostdin", "-y", "-loglevel", "error", *arguments, "-progress", "pipe:1", "-nostats", output]

    def on_line(line: str) -> None:
        if progress is None or not duration or duration <= 0 or not line.startswith("out_time_us="):
            return
        try:
            microseconds = float(line[len("out_time_us="):])
        except ValueError:
            return
        progress(min(max(microseconds / 1_000_000 / duration, 0.0), 1.0))

    external.run_streaming("ffmpeg", full, on_line, cancellation)
    if progress:
        progress(1.0)
