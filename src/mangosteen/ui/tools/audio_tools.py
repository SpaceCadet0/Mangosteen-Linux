"""Sound tools: Volume (loudness), Bleep, Channels and the Visualizer. Each can play the processed sound before it is
saved."""

from __future__ import annotations

import os
import tempfile
from collections.abc import Callable

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (QComboBox, QDoubleSpinBox, QFileDialog, QFormLayout, QHBoxLayout, QLabel, QPushButton,
                               QSlider, QVBoxLayout, QWidget)

from ...convert import qtutil
from ...core.loc import L, count, fmt
from ...imaging.compose import RGBA
from ...mediatools import audio, cut
from ..widgets import ColorButton, LiveTask, PreviewPane, Segmented, hint_label
from . import registry
from .media_tools import _note_for_many, _side, _two_columns
from .media_widgets import MediaPane, MediaPlayer, MediaToolWindow, clock, time_field

_PREVIEW_SECONDS = 20.0


class Listen(QWidget):
    """Buttons to hear the original sound or a short rendering of the processed one."""

    def __init__(self, pane: MediaPane, build: Callable[[], dict]) -> None:
        super().__init__()
        self._pane = pane
        self._build = build
        self._player = MediaPlayer(with_video=False)
        self._task = LiveTask(0)
        self._task.finished.connect(self._ready)
        self._task.failed.connect(self._failed)
        self._file: str | None = None
        original = QPushButton(L("Hear the original"))
        original.clicked.connect(self._original)
        self._result = QPushButton(L("Hear the result"))
        self._result.clicked.connect(self._render)
        for button in (original, self._result):
            button.setEnabled(pane.player.available)
        self._status = hint_label("")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        row = QHBoxLayout()
        row.addWidget(original)
        row.addWidget(self._result)
        layout.addLayout(row)
        layout.addWidget(self._status)

    def _original(self) -> None:
        self._player.pause()
        self._pane.player.play()

    def _render(self) -> None:
        self._pane.player.pause()
        self._player.pause()
        path, start = self._pane.path, self._pane.timeline.position
        arguments = self._build()
        self._status.setText(L("Preparing…"))
        self._result.setEnabled(False)
        folder = tempfile.mkdtemp(prefix="mangosteen-listen-")
        target = os.path.join(folder, "preview.m4a")

        def work(cancelled):  # noqa: ANN001, ANN202
            audio.render_preview(path, target, start=start, length=_PREVIEW_SECONDS, **arguments)
            return target

        self._task.request(work, immediate=True)

    def _ready(self, target: str) -> None:
        self._clean()
        self._file = target
        self._result.setEnabled(True)
        self._status.setText("")
        self._player.load(target)
        self._player.play()

    def _failed(self, message: str) -> None:
        self._result.setEnabled(True)
        self._status.setText(message)

    def _clean(self) -> None:
        if self._file:
            try:
                os.remove(self._file)
                os.rmdir(os.path.dirname(self._file))
            except OSError:
                pass
            self._file = None

    def shutdown(self) -> None:
        self._player.release()
        self._clean()


class _ListeningWindow(MediaToolWindow):
    _listeners: list[Listen]

    def listen(self, pane: MediaPane, build: Callable[[], dict]) -> Listen:
        listener = Listen(pane, build)
        if not hasattr(self, "_listeners"):
            self._listeners = []
        self._listeners.append(listener)
        return listener

    def closeEvent(self, event) -> None:  # noqa: ANN001, N802
        for listener in getattr(self, "_listeners", []):
            listener.shutdown()
        super().closeEvent(event)


# MARK: Volume

_LOUDNESS = [(L("Streaming and video, −14 LUFS"), -14.0), (L("Podcast, −16 LUFS"), -16.0),
             (L("Broadcast, −23 LUFS"), -23.0), (L("Loud, −9 LUFS"), -9.0)]


class NormalizeTool(_ListeningWindow):
    def __init__(self, files: list[str], context) -> None:  # noqa: ANN001
        super().__init__(L("Volume"), files, L("Even out the volume"), context)
        self._pane = self.pane(self.first, mode="seek", show_picture=False)
        self._measure = LiveTask(0)
        self._measure.finished.connect(self._measured)
        self._measure.failed.connect(lambda m: self._now.setText(m))
        self._measured_once = False

        side, layout = _side()
        self._preset = QComboBox()
        for title, value in _LOUDNESS:
            self._preset.addItem(title, value)
        self._preset.currentIndexChanged.connect(lambda _i: self._level.setValue(self._preset.currentData()))
        form = QFormLayout()
        form.addRow(L("Target"), self._preset)
        self._level = QDoubleSpinBox()
        self._level.setRange(-40.0, -5.0)
        self._level.setValue(-14.0)
        self._level.setSuffix(" LUFS")
        form.addRow(L("Loudness"), self._level)
        self._peak = QDoubleSpinBox()
        self._peak.setRange(-9.0, 0.0)
        self._peak.setValue(-1.0)
        self._peak.setSuffix(" dBTP")
        form.addRow(L("Highest peak"), self._peak)
        layout.addLayout(form)
        self._now = QLabel("…")
        self._now.setWordWrap(True)
        layout.addWidget(self._now)
        layout.addWidget(self.listen(self._pane, self._preview_arguments))
        layout.addWidget(hint_label(L("The sound is measured and adjusted in two passes, the way streaming services do. "
                                      "Pictures in videos are not touched.")))
        if len(self.media_files) > 1:
            layout.addWidget(hint_label(fmt("The target is applied to all {0} files.", len(self.media_files))))
        layout.addStretch(1)
        _two_columns(self, self._pane, side)
        path = self.first
        self._measure.request(lambda cancelled: audio.measure_loudness(path), immediate=True)

    @property
    def is_settled(self) -> bool:
        return super().is_settled and self._measured_once

    def _measured(self, result: audio.LoudnessMeasurement) -> None:
        self._measured_once = True
        self._now.setText(fmt("Now: {0} LUFS, highest peak {1} dBTP", f"{result.integrated:.1f}", f"{result.true_peak:.1f}"))

    def target(self) -> audio.LoudnessTarget:
        return audio.LoudnessTarget(self._level.value(), self._peak.value())

    def _preview_arguments(self) -> dict:
        return {"audio_filter": audio.loudnorm_filter(self.target())}

    def run(self) -> None:
        target = self.target()
        self.jobs.run_each(L("Evening out the volume"), L("Volume evened out"), self.media_files,
                           lambda p, token, progress: audio.normalize(p, target, progress, token))
        self.close()


# MARK: Bleep

_TONES = [(L("Classic, 1000 Hz"), 1000), (L("Low, 600 Hz"), 600), (L("High, 1500 Hz"), 1500)]


class BleepTool(_ListeningWindow):
    def __init__(self, files: list[str], context) -> None:  # noqa: ANN001
        super().__init__(L("Bleep"), files, L("Bleep"), context)
        self._pane = self.pane(self.first, mode="ranges", thumbnail_height=48)
        timeline = self._pane.timeline
        timeline.ranges_changed.connect(self._ranges_changed)
        timeline.current_changed.connect(lambda _i: self._ranges_changed())

        side, layout = _side()
        add = QPushButton(L("Add a bleep here"))
        add.clicked.connect(self._add)
        layout.addWidget(add)
        form = QFormLayout()
        self._from = time_field()
        self._to = time_field()
        self._from.editingFinished.connect(self._typed)
        self._to.editingFinished.connect(self._typed)
        form.addRow(L("From"), self._from)
        form.addRow(L("To"), self._to)
        layout.addLayout(form)
        remove = QPushButton(L("Remove this bleep"))
        remove.clicked.connect(timeline.remove_current_range)
        layout.addWidget(remove)
        self._summary = QLabel("")
        layout.addWidget(self._summary)
        self._tone = QComboBox()
        for title, value in _TONES:
            self._tone.addItem(title, value)
        tone_form = QFormLayout()
        tone_form.addRow(L("Tone"), self._tone)
        self._volume = QSlider(Qt.Orientation.Horizontal)
        self._volume.setRange(5, 100)
        self._volume.setValue(30)
        tone_form.addRow(L("Tone volume"), self._volume)
        layout.addLayout(tone_form)
        layout.addWidget(self.listen(self._pane, self._preview_arguments))
        layout.addWidget(hint_label(L("Click a bleep on the strip to edit it; drag its edges to change it.")))
        note = _note_for_many(self)
        if note:
            layout.addWidget(note)
        layout.addStretch(1)
        _two_columns(self, self._pane, side)
        self.set_action_enabled(False)

    def _add(self) -> None:
        timeline = self._pane.timeline
        start = timeline.position
        timeline.add_range(start, min(start + 1.0, timeline.duration))

    def _ranges_changed(self) -> None:
        timeline = self._pane.timeline
        if 0 <= timeline.current < len(timeline.ranges):
            start, end = timeline.ranges[timeline.current]
            self._from.setText(cut.timecode(start))
            self._to.setText(cut.timecode(end))
        else:
            self._from.clear()
            self._to.clear()
        self._summary.setText(count(len(timeline.ranges), "bleep"))
        self.set_action_enabled(bool(timeline.ranges))

    def _typed(self) -> None:
        timeline = self._pane.timeline
        start, end = cut.parse_timecode(self._from.text()), cut.parse_timecode(self._to.text())
        if start is not None and end is not None and abs(end - start) >= 0.05:
            timeline.set_current_range(start, end)
        self._ranges_changed()

    def _arguments(self) -> tuple[list[tuple[float, float]], float, float]:
        return list(self._pane.timeline.ranges), self._tone.currentData(), self._volume.value() / 100.0

    def _preview_arguments(self) -> dict:
        ranges, frequency, volume = self._arguments()
        duration = self._pane.timeline.duration
        return {"graph": audio.bleep_graph(ranges, frequency, volume, duration) if ranges else None,
                "audio_filter": None}

    def run(self) -> None:
        ranges, frequency, volume = self._arguments()
        self.jobs.run_each(L("Bleeping"), L("Bleeped"), [self.first],
                           lambda p, token, progress: audio.bleep(p, ranges, frequency, volume, progress, token))
        self.close()


# MARK: Channels


class ChannelsTool(_ListeningWindow):
    def __init__(self, files: list[str], context) -> None:  # noqa: ANN001
        super().__init__(L("Channels"), files, L("Convert"), context)
        self._pane = self.pane(self.first, mode="seek", show_picture=False)
        self._channels = 2

        side, layout = _side()
        self._layout = Segmented([(L("Stereo"), audio.Layout.STEREO), (L("Mono"), audio.Layout.MONO)], audio.Layout.STEREO)
        layout.addWidget(self._layout)
        form = QFormLayout()
        self._left = self._gain()
        self._right = self._gain()
        form.addRow(L("Left"), self._left)
        form.addRow(L("Right"), self._right)
        layout.addLayout(form)
        from PySide6.QtWidgets import QCheckBox

        self._swap = QCheckBox(L("Swap left and right"))
        layout.addWidget(self._swap)
        layout.addWidget(self.listen(self._pane, self._preview_arguments))
        layout.addWidget(hint_label(L("Mono mixes both sides into one channel. The levels are shares of each side.")))
        if len(self.media_files) > 1:
            layout.addWidget(hint_label(fmt("The settings are applied to all {0} files.", len(self.media_files))))
        layout.addStretch(1)
        _two_columns(self, self._pane, side)
        self._pane.loaded.connect(lambda r: setattr(self, "_channels", r.info.audio_channels or 2))

    @staticmethod
    def _gain() -> QSlider:
        slider = QSlider(Qt.Orientation.Horizontal)
        slider.setRange(0, 200)
        slider.setValue(100)
        slider.setToolTip(L("100% keeps the level"))
        return slider

    def settings_value(self) -> audio.ChannelSettings:
        return audio.ChannelSettings(self._layout.value, self._left.value() / 100.0, self._right.value() / 100.0,
                                     self._swap.isChecked())

    def _preview_arguments(self) -> dict:
        return {"audio_filter": audio.channel_filter(self.settings_value(), self._channels)}

    def run(self) -> None:
        value = self.settings_value()
        self.jobs.run_each(L("Converting channels"), L("Channels converted"), self.media_files,
                           lambda p, token, progress: audio.convert_channels(p, value, progress, token))
        self.close()


# MARK: Visualizer


class VisualizerTool(MediaToolWindow):
    def __init__(self, files: list[str], context) -> None:  # noqa: ANN001
        super().__init__(L("Visualizer"), files, L("Make a video"), context)
        self._pane = self.pane(self.first, mode="seek", show_picture=False)
        self._settings = audio.VisualizerSettings()
        self._frame = LiveTask(250)
        self._frame.finished.connect(self._drawn)
        self._frame.failed.connect(lambda m: self._preview.set_message(m))
        self._drawn_once = False
        self._pane.loaded.connect(lambda _r: self._request())
        self._pane.position_changed.connect(lambda _s: self._request())

        left = QWidget()
        column = QVBoxLayout(left)
        column.setContentsMargins(0, 0, 0, 0)
        self._preview = PreviewPane(480, 270)
        column.addWidget(self._preview, 1)
        column.addWidget(self._pane)

        side, layout = _side()
        self._style = Segmented([(L("Wave"), audio.VisualizerStyle.WAVEFORM), (L("Spectrum"), audio.VisualizerStyle.SPECTRUM),
                                 (L("Picture"), audio.VisualizerStyle.STILL)], audio.VisualizerStyle.WAVEFORM)
        self._style.changed.connect(self._changed)
        layout.addWidget(self._style)
        form = QFormLayout()
        self._shape = QComboBox()
        for title, value in ((L("Landscape 16:9"), audio.Orientation.LANDSCAPE),
                             (L("Vertical 9:16"), audio.Orientation.PORTRAIT), (L("Square"), audio.Orientation.SQUARE)):
            self._shape.addItem(title, value)
        self._shape.currentIndexChanged.connect(self._changed)
        form.addRow(L("Shape"), self._shape)
        self._wave = ColorButton(QColor(255, 158, 51))
        self._wave.changed.connect(self._changed)
        form.addRow(L("Colour"), self._wave)
        self._back = ColorButton(QColor(20, 20, 26))
        self._back.changed.connect(self._changed)
        form.addRow(L("Background"), self._back)
        layout.addLayout(form)
        picture = QHBoxLayout()
        self._choose = QPushButton(L("Background picture…"))
        self._choose.clicked.connect(self._pick)
        self._clear = QPushButton(L("Remove"))
        self._clear.clicked.connect(lambda: self._set_image(None))
        self._clear.setEnabled(False)
        picture.addWidget(self._choose, 1)
        picture.addWidget(self._clear)
        layout.addLayout(picture)
        self._image: str | None = None
        layout.addWidget(hint_label(L("The result is an MP4 video with the sound and the picture; the preview shows the "
                                      "moment under the playhead.")))
        if len(self.media_files) > 1:
            layout.addWidget(hint_label(fmt("The settings are applied to all {0} files.", len(self.media_files))))
        layout.addStretch(1)
        _two_columns(self, left, side)

    @property
    def is_settled(self) -> bool:
        return super().is_settled and self._drawn_once

    def value(self) -> audio.VisualizerSettings:
        return audio.VisualizerSettings(self._style.value, self._shape.currentData(), RGBA.from_qcolor(self._wave.color),
                                        RGBA.from_qcolor(self._back.color), self._image)

    def _changed(self, *_args) -> None:  # noqa: ANN002
        self._request()

    def _pick(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, L("Background picture"), os.path.dirname(self.first),
                                              L("Pictures") + " (*.png *.jpg *.jpeg *.webp *.bmp *.tif *.tiff)")
        if path:
            self._set_image(path)

    def _set_image(self, path: str | None) -> None:
        self._image = path
        self._clear.setEnabled(path is not None)
        self._choose.setText(os.path.basename(path) if path else L("Background picture…"))
        self._request()

    def _request(self) -> None:
        duration = self._pane.timeline.duration
        if duration <= 0:
            return
        settings, path, at = self.value(), self.first, self._pane.timeline.position
        self._preview.set_busy(True)
        self._frame.request(lambda cancelled: audio.visualizer_frame(path, settings, duration, at))

    def _drawn(self, image) -> None:  # noqa: ANN001
        self._drawn_once = True
        self._preview.set_busy(False)
        self._preview.set_image(qtutil.pil_to_qimage(image))

    def run(self) -> None:
        settings = self.value()
        self.jobs.run_each(L("Making videos"), L("Videos made"), self.media_files,
                           lambda p, token, progress: audio.visualize(p, settings, progress, token), max_concurrent=1)
        self.close()


@registry.register("tool.normalize")
def create_normalize(files, context):  # noqa: ANN001, ANN201
    return NormalizeTool(files, context)


@registry.register("tool.bleep")
def create_bleep(files, context):  # noqa: ANN001, ANN201
    return BleepTool(files, context)


@registry.register("tool.channels")
def create_channels(files, context):  # noqa: ANN001, ANN201
    return ChannelsTool(files, context)


@registry.register("tool.visualizer")
def create_visualizer(files, context):  # noqa: ANN001, ANN201
    return VisualizerTool(files, context)


__all__ = ["NormalizeTool", "BleepTool", "ChannelsTool", "VisualizerTool", "clock"]
