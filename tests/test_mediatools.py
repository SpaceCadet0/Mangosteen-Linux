"""The video and audio tools against real ffmpeg output."""

import os

import pytest

from make_fixtures import tone, video
from mangosteen.convert import media
from mangosteen.core import capabilities
from mangosteen.imaging.compose import RGBA
from mangosteen.imaging.geometry import UnitRect
from mangosteen.imaging.redact import RedactionStyle
from mangosteen.mediatools import audio, cut, effects, redact_video

pytestmark = pytest.mark.skipif(not capabilities.has_ffmpeg(), reason="needs ffmpeg")


def names(folder):
    return sorted(os.listdir(folder))


def test_timecodes():
    assert cut.timecode(83.45) == "00:01:23.450"
    assert cut.timecode(-3) == "00:00:00.000"
    assert cut.parse_timecode("1:02:03.5") == pytest.approx(3723.5)
    assert cut.parse_timecode("2:03") == 123
    assert cut.parse_timecode("75,5") == 75.5
    assert cut.parse_timecode("abc") is None
    assert cut.parse_timecode("1:2:3:4") is None
    assert cut.parse_timecode("-4") is None


def test_split_points_and_bounds():
    assert cut.equal_split_points(10, 4) == [2.5, 5.0, 7.5]
    assert cut.equal_split_points(10, 1) == []
    assert cut.split_bounds([5, 5, 0.01, 9.99, 3], 10) == [0, 3, 5, 10]


def test_peaks_cover_every_sample():
    assert cut.peaks([0.1, -0.9, 0.2, 0.3], 2) == pytest.approx([0.9, 0.3])
    assert cut.peaks([], 4) == []
    assert len(cut.peaks([0.5] * 3, 10)) == 3


def test_atempo_chain_and_label():
    assert effects.atempo_chain(1.5) == ["atempo=1.5"]
    assert effects.atempo_chain(4) == ["atempo=2", "atempo=2"]
    assert effects.atempo_chain(0.25) == ["atempo=0.5", "atempo=0.5"]
    assert effects.speed_label(2) == "×2"
    assert effects.speed_label(1.255) == "×1.25" or effects.speed_label(1.255) == "×1.26"


def test_trim_audio_keeps_format_and_length(work):
    source = tone(str(work / "a.wav"), seconds=3.0)
    result = cut.trim(source, 0.5, 2.0)
    assert os.path.basename(result) == "a (trimmed).wav"
    assert media.probe(result).duration == pytest.approx(1.5, abs=0.15)
    assert os.path.exists(source)


def test_trim_video_reencodes_to_an_exact_cut(work):
    source = video(str(work / "v.mp4"), seconds=3)
    result = cut.trim(source, 1.0, 2.0, fast=False)
    info = media.probe(result)
    assert info.has_video and info.has_audio
    assert info.duration == pytest.approx(1.0, abs=0.25)


def test_split_writes_numbered_parts(work):
    source = tone(str(work / "a.wav"), seconds=3.0)
    folder = cut.split(source, [1.0, 2.0])
    assert names(folder) == ["a 1.wav", "a 2.wav", "a 3.wav"]
    total = sum(media.probe(os.path.join(folder, n)).duration for n in names(folder))
    assert total == pytest.approx(3.0, abs=0.3)


def test_frames(work):
    source = video(str(work / "v.mp4"), seconds=2)
    one = cut.save_frames(source, [0.5])
    assert one.endswith(".png") and "00-00-00.500" in one
    several = cut.save_frames(source, [0.2, 1.0, 1.6])
    assert os.path.isdir(several) and len(names(several)) == 3
    assert cut.frame_size(source) == (160, 120)
    assert len(cut.thumbnails(source, 2.0, 4, 40)) == 4


def test_waveform_levels(work):
    source = tone(str(work / "a.wav"), seconds=1.0)
    levels = cut.waveform(source, 1.0, 20)
    assert len(levels) == 20 and max(levels) > 0.2


def test_speed_changes_the_duration(work):
    source = tone(str(work / "a.wav"), seconds=2.0)
    fast = effects.change_speed(source, 2.0)
    assert "speed ×2" in os.path.basename(fast)
    assert media.probe(fast).duration == pytest.approx(1.0, abs=0.2)
    tape = effects.change_speed(source, 0.5, preserve_pitch=False)
    assert media.probe(tape).duration == pytest.approx(4.0, abs=0.3)


def test_join_makes_one_mp4(work):
    a = video(str(work / "a.mp4"), seconds=1)
    b = video(str(work / "b.mp4"), seconds=1, size="320x240", audio=False)
    result = effects.join([a, b])
    assert os.path.basename(result) == "Joined.mp4"
    info = media.probe(result)
    assert (info.width, info.height) == (160, 120)
    assert info.has_audio
    assert info.duration == pytest.approx(2.0, abs=0.3)
    with pytest.raises(cut.NothingToDo):
        effects.join([a])


def test_crop_video(work):
    source = video(str(work / "v.mp4"), seconds=1, size="320x240")
    result = effects.crop_video(source, UnitRect(0.25, 0.25, 0.5, 0.5))
    info = media.probe(result)
    assert (info.width, info.height) == (160, 120)
    scaled = effects.crop_video(source, UnitRect(0, 0, 0.5, 0.5), (100, 60))
    assert (media.probe(scaled).width, media.probe(scaled).height) == (100, 60)


def test_compress_audio_is_smaller_or_refused(work):
    source = tone(str(work / "a.wav"), seconds=2.0)
    result = effects.compress(source)
    assert os.path.getsize(result) < os.path.getsize(source)
    assert result.endswith(".m4a")


def test_compress_target_size_estimate(work):
    source = tone(str(work / "a.wav"), seconds=2.0)
    settings = effects.MediaCompression(use_target_size=True, target_bytes=40_000)
    assert effects.estimate_compressed_size(source, settings) == 40_000
    assert effects.estimate_compressed_size(source, effects.MediaCompression()) > 0


def test_normalize_hits_the_target_loudness(work):
    source = tone(str(work / "a.wav"), seconds=4.0)
    result = audio.normalize(source, audio.LoudnessTarget(integrated=-20.0))
    assert "(volume)" in result
    measured = audio.measure_loudness(result, audio.LoudnessTarget(integrated=-20.0))
    assert measured.integrated == pytest.approx(-20.0, abs=2.0)


def test_channel_filters():
    settings = audio.ChannelSettings(left=1.0, right=0.5, swap=True)
    assert audio.channel_filter(settings, 2) == "pan=stereo|c0=1.00*c1|c1=0.50*c0"
    assert audio.channel_filter(settings, 1) == "pan=stereo|c0=1.00*c0|c1=0.50*c0"
    mono = audio.ChannelSettings(layout=audio.Layout.MONO)
    assert audio.channel_filter(mono, 2) == "pan=mono|c0=0.50*c0+0.50*c1"
    assert audio.channel_filter(mono, 1) == "pan=mono|c0=1.00*c0"


def test_convert_channels_to_stereo(work):
    source = tone(str(work / "a.wav"), seconds=1.0)
    result = audio.convert_channels(source, audio.ChannelSettings())
    assert media.probe(result).audio_channels == 2


def test_bleep_replaces_the_range(work):
    source = tone(str(work / "a.wav"), seconds=2.0)
    result = audio.bleep(source, [(0.5, 1.0)], frequency=1000, volume=0.3)
    assert "(bleeped)" in result
    assert media.probe(result).duration == pytest.approx(2.0, abs=0.2)
    with pytest.raises(cut.NothingToDo):
        audio.bleep(source, [])


def test_audio_tools_refuse_files_without_sound(work):
    silent = video(str(work / "s.mp4"), seconds=1, audio=False)
    with pytest.raises(media.MediaError):
        audio.normalize(silent)


def test_audio_tools_on_video_copy_the_picture(work):
    source = video(str(work / "v.mp4"), seconds=1)
    result = audio.convert_channels(source, audio.ChannelSettings(layout=audio.Layout.MONO))
    info = media.probe(result)
    assert info.has_video and info.audio_channels == 1


def test_visualizer_makes_a_video(work):
    source = tone(str(work / "a.wav"), seconds=1.0)
    settings = audio.VisualizerSettings(orientation=audio.Orientation.SQUARE)
    result = audio.visualize(source, settings)
    info = media.probe(result)
    assert result.endswith(".mp4") and (info.width, info.height) == (1080, 1080) and info.has_audio
    frame = audio.visualizer_frame(source, settings, 1.0, 0.5)
    assert frame.size == (1080, 1080)


def test_redact_video_covers_the_region_in_time(work):
    source = video(str(work / "v.mp4"), seconds=2, size="320x240")
    regions = [redact_video.Region(UnitRect(0, 0, 0.5, 0.5), 0.0, 1.0)]
    solid = RGBA(0, 0, 0)
    covered = redact_video.preview_frame(source, regions, RedactionStyle.SOLID, solid, (320, 240), 0.5).convert("RGB")
    assert covered.getpixel((50, 50)) == pytest.approx((16, 16, 16), abs=8) or sum(covered.getpixel((50, 50))) < 60
    clear = redact_video.preview_frame(source, regions, RedactionStyle.SOLID, solid, (320, 240), 1.5).convert("RGB")
    assert clear.getpixel((50, 50)) != covered.getpixel((50, 50))
    result = redact_video.redact(source, regions, RedactionStyle.PIXELATE, solid)
    assert "(hidden)" in result and media.probe(result).has_audio
    with pytest.raises(cut.NothingToDo):
        redact_video.redact(source, [], RedactionStyle.SOLID, solid)
