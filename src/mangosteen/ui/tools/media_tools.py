"""Video and audio tools on a timeline: Trim, Split, Speed, Frames, Compress and Join."""

from __future__ import annotations

import os

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QAbstractItemView, QCheckBox, QComboBox, QDoubleSpinBox, QFormLayout, QHBoxLayout, QLabel,
                               QListWidget, QListWidgetItem, QPushButton, QSpinBox, QVBoxLayout, QWidget)

from ...convert import media
from ...core import capabilities
from ...core.file_format import Category
from ...core.loc import L, count, fmt
from ...imaging.compress import human_size
from ...mediatools import cut, effects
from ..widgets import LiveTask, Segmented, hint_label
from . import registry
from .media_widgets import MediaToolWindow, clock, time_field


def _side(width: int = 300) -> tuple[QWidget, QVBoxLayout]:
    holder = QWidget()
    holder.setFixedWidth(width)
    layout = QVBoxLayout(holder)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(10)
    return holder, layout


def _two_columns(window: MediaToolWindow, left: QWidget, right: QWidget) -> None:
    outer = QHBoxLayout()
    outer.setSpacing(18)
    outer.addWidget(left, 1)
    outer.addWidget(right, alignment=Qt.AlignmentFlag.AlignTop)
    window.set_body(layout=outer)


def _note_for_many(window: MediaToolWindow) -> QLabel | None:
    if len(window.media_files) > 1:
        return hint_label(fmt("{0} files are selected; this tool works on the first one, “{1}”.", len(window.media_files),
                              os.path.basename(window.first)))
    return None


# MARK: Trim


class TrimTool(MediaToolWindow):
    def __init__(self, files: list[str], context) -> None:  # noqa: ANN001
        super().__init__(L("Trim"), files, L("Trim"), context)
        self._pane = self.pane(self.first, mode="select")
        self._pane.timeline.selection_changed.connect(self._selection_changed)
        self._pane.loaded.connect(self._loaded)
        self._pane.timeline.position_changed.connect(lambda _s: None)

        side, layout = _side()
        self._start = time_field()
        self._end = time_field()
        self._start.editingFinished.connect(self._typed)
        self._end.editingFinished.connect(self._typed)
        form = QFormLayout()
        form.addRow(L("From"), self._start)
        form.addRow(L("To"), self._end)
        layout.addLayout(form)
        here = QHBoxLayout()
        set_start = QPushButton(L("Start here"))
        set_start.clicked.connect(lambda: self._set("start"))
        set_end = QPushButton(L("End here"))
        set_end.clicked.connect(lambda: self._set("end"))
        here.addWidget(set_start)
        here.addWidget(set_end)
        layout.addLayout(here)
        self._length = QLabel("")
        layout.addWidget(self._length)
        listen = QPushButton(L("Play the selection"))
        listen.setEnabled(self._pane.player.available)
        listen.clicked.connect(lambda: self._pane.play_range(*self._pane.timeline.selection))
        layout.addWidget(listen)
        self._fast = QCheckBox(L("Fast cut without re-encoding"))
        layout.addWidget(self._fast)
        layout.addWidget(hint_label(L("A fast cut is lossless but can start a little earlier, at the nearest keyframe.")))
        note = _note_for_many(self)
        if note:
            layout.addWidget(note)
        layout.addStretch(1)
        _two_columns(self, self._pane, side)
        self.set_action_enabled(False)

    def _loaded(self, _result) -> None:  # noqa: ANN001
        self._selection_changed(*self._pane.timeline.selection)
        self.set_action_enabled(self._pane.timeline.duration > 0)

    def _selection_changed(self, start: float, end: float) -> None:
        self._start.setText(cut.timecode(start))
        self._end.setText(cut.timecode(end))
        self._length.setText(fmt("Length: {0}", clock(end - start)))

    def _typed(self) -> None:
        timeline = self._pane.timeline
        start, end = cut.parse_timecode(self._start.text()), cut.parse_timecode(self._end.text())
        start = timeline.selection[0] if start is None else start
        end = timeline.selection[1] if end is None else end
        if end - start < 0.05:
            start, end = timeline.selection
        timeline.set_selection(start, end, emit=True)

    def _set(self, which: str) -> None:
        start, end = self._pane.timeline.selection
        here = self._pane.timeline.position
        if which == "start":
            start = min(here, end - 0.05)
        else:
            end = max(here, start + 0.05)
        self._pane.timeline.set_selection(start, end, emit=True)

    def run(self) -> None:
        start, end = self._pane.timeline.selection
        fast = self._fast.isChecked()
        self.jobs.run_each(L("Trimming"), L("Trimmed"), [self.first],
                           lambda p, token, progress: cut.trim(p, start, end, fast, progress, token))
        self.close()


# MARK: Split


class SplitMediaTool(MediaToolWindow):
    def __init__(self, files: list[str], context) -> None:  # noqa: ANN001
        super().__init__(L("Split"), files, L("Split"), context)
        self._pane = self.pane(self.first, mode="markers")
        self._pane.timeline.markers_changed.connect(self._update)
        self._pane.loaded.connect(lambda _r: self._update())

        side, layout = _side()
        add = QPushButton(L("Add a cut here"))
        add.clicked.connect(lambda: self._pane.timeline.add_marker(self._pane.timeline.position))
        layout.addWidget(add)
        equal = QHBoxLayout()
        self._parts = QSpinBox()
        self._parts.setRange(2, 99)
        self._parts.setValue(2)
        apply = QPushButton(L("Cut into equal parts"))
        apply.clicked.connect(self._equal)
        equal.addWidget(self._parts)
        equal.addWidget(apply, 1)
        layout.addLayout(equal)
        clear = QPushButton(L("Remove all cuts"))
        clear.clicked.connect(lambda: self._pane.timeline.set_markers([]))
        layout.addWidget(clear)
        self._summary = QLabel("")
        self._summary.setWordWrap(True)
        layout.addWidget(self._summary)
        self._fast = QCheckBox(L("Fast cut without re-encoding"))
        layout.addWidget(self._fast)
        layout.addWidget(hint_label(L("Click the strip to move the playhead; double-click a cut to remove it.")))
        note = _note_for_many(self)
        if note:
            layout.addWidget(note)
        layout.addStretch(1)
        _two_columns(self, self._pane, side)
        self.set_action_enabled(False)

    def _equal(self) -> None:
        timeline = self._pane.timeline
        timeline.set_markers(cut.equal_split_points(timeline.duration, self._parts.value()))

    def _update(self) -> None:
        timeline = self._pane.timeline
        bounds = cut.split_bounds(timeline.markers, timeline.duration)
        parts = len(bounds) - 1
        self._summary.setText(count(parts, "part") + (": " + " · ".join(f"{clock(a)}–{clock(b)}" for a, b in
                                                                     zip(bounds, bounds[1:])) if parts <= 6 else ""))
        self.set_action_enabled(parts >= 2)

    def run(self) -> None:
        points = list(self._pane.timeline.markers)
        fast = self._fast.isChecked()
        self.jobs.run_each(L("Splitting"), L("Split into parts"), [self.first],
                           lambda p, token, progress: cut.split(p, points, fast, progress, token))
        self.close()


# MARK: Speed

_SPEEDS = [0.25, 0.5, 0.75, 1.25, 1.5, 2.0, 3.0, 4.0]


class SpeedTool(MediaToolWindow):
    def __init__(self, files: list[str], context) -> None:  # noqa: ANN001
        super().__init__(L("Speed"), files, L("Change speed"), context)
        self._pane = self.pane(self.first, mode="seek")
        self._pane.loaded.connect(lambda _r: self._update())

        side, layout = _side()
        grid = QHBoxLayout()
        grid.setSpacing(4)
        for speed in _SPEEDS[:4]:
            grid.addWidget(self._preset(speed))
        layout.addLayout(grid)
        grid = QHBoxLayout()
        grid.setSpacing(4)
        for speed in _SPEEDS[4:]:
            grid.addWidget(self._preset(speed))
        layout.addLayout(grid)
        self._factor = QDoubleSpinBox()
        self._factor.setRange(0.1, 8.0)
        self._factor.setSingleStep(0.05)
        self._factor.setDecimals(2)
        self._factor.setValue(2.0)
        self._factor.setPrefix("× ")
        self._factor.valueChanged.connect(self._update)
        form = QFormLayout()
        form.addRow(L("Speed"), self._factor)
        layout.addLayout(form)
        self._pitch = QCheckBox(L("Keep the pitch"))
        self._pitch.setChecked(True)
        layout.addWidget(self._pitch)
        layout.addWidget(hint_label(L("Without it, sound speeds up and goes higher, like a tape.")))
        self._result = QLabel("")
        layout.addWidget(self._result)
        if len(self.media_files) > 1:
            layout.addWidget(hint_label(fmt("The speed is applied to all {0} files.", len(self.media_files))))
        layout.addStretch(1)
        _two_columns(self, self._pane, side)
        self._update()

    def _preset(self, speed: float) -> QPushButton:
        button = QPushButton(effects.speed_label(speed))
        button.setMinimumWidth(40)
        button.clicked.connect(lambda: self._factor.setValue(speed))
        return button

    def _update(self) -> None:
        factor = self._factor.value()
        duration = self._pane.timeline.duration
        self._result.setText(fmt("New length: {0}", clock(duration / factor)) if duration else "")
        self._pane.player.set_rate(factor)

    def run(self) -> None:
        factor, pitch = self._factor.value(), self._pitch.isChecked()
        self.jobs.run_each(L("Changing speed"), L("Speed changed"), self.media_files,
                           lambda p, token, progress: effects.change_speed(p, factor, pitch, progress, token),
                           max_concurrent=2)
        self.close()


# MARK: Frames


class FramesTool(MediaToolWindow):
    def __init__(self, files: list[str], context) -> None:  # noqa: ANN001
        super().__init__(L("Frames"), files, L("Save frames"), context, Category.VIDEO)
        self._pane = self.pane(self.first, mode="seek")
        self._times: list[float] = []

        side, layout = _side()
        capture = QPushButton(L("Take the frame here"))
        capture.clicked.connect(lambda: self._add(self._pane.timeline.position))
        layout.addWidget(capture)
        every = QHBoxLayout()
        self._step = QDoubleSpinBox()
        self._step.setRange(0.1, 3600)
        self._step.setValue(5.0)
        self._step.setSuffix(" " + L("s"))
        add_all = QPushButton(L("Take one every"))
        add_all.clicked.connect(self._every)
        every.addWidget(add_all, 1)
        every.addWidget(self._step)
        layout.addLayout(every)
        self._list = QListWidget()
        self._list.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self._list.itemActivated.connect(lambda item: self._pane.seek(item.data(Qt.ItemDataRole.UserRole)))
        layout.addWidget(self._list, 1)
        buttons = QHBoxLayout()
        remove = QPushButton(L("Remove"))
        remove.clicked.connect(self._remove)
        clear = QPushButton(L("Clear"))
        clear.clicked.connect(self._clear)
        buttons.addWidget(remove)
        buttons.addWidget(clear)
        layout.addLayout(buttons)
        note = _note_for_many(self)
        if note:
            layout.addWidget(note)
        _two_columns(self, self._pane, side)
        self.set_action_enabled(False)

    def _add(self, seconds: float) -> None:
        if all(abs(seconds - t) > 0.01 for t in self._times):
            self._times.append(seconds)
            self._times.sort()
            self._refresh()

    def _every(self) -> None:
        step, duration = self._step.value(), self._pane.timeline.duration
        moment = 0.0
        while moment < duration - 0.05:
            self._add(moment)
            moment += step

    def _remove(self) -> None:
        for item in self._list.selectedItems():
            self._times.remove(item.data(Qt.ItemDataRole.UserRole))
        self._refresh()

    def _clear(self) -> None:
        self._times.clear()
        self._refresh()

    def _refresh(self) -> None:
        self._list.clear()
        for seconds in self._times:
            item = QListWidgetItem(cut.timecode(seconds))
            item.setData(Qt.ItemDataRole.UserRole, seconds)
            self._list.addItem(item)
        self.set_action_enabled(bool(self._times))
        self.set_status(count(len(self._times), "frame"))

    def run(self) -> None:
        times = list(self._times)
        self.jobs.run_once(L("Saving frames"), L("Frames saved"), count(len(times), "frame"),
                           lambda: cut.save_frames(self.first, times))
        self.close()


# MARK: Compress

_HEIGHTS = [(L("Original size"), None), ("2160p", 2160), ("1440p", 1440), ("1080p", 1080), ("720p", 720), ("480p", 480),
            ("360p", 360)]


class CompressMediaTool(MediaToolWindow):
    def __init__(self, files: list[str], context) -> None:  # noqa: ANN001
        super().__init__(L("Compress"), files, L("Compress"), context)
        self._pane = self.pane(self.first, mode="seek", thumbnail_height=48)
        self._estimated_once = False
        self._estimator = LiveTask(400)
        self._estimator.finished.connect(self._estimated)
        self._estimator.failed.connect(lambda m: self._estimate.setText(m))
        self._pane.loaded.connect(lambda _r: self._changed())
        has_video = any(file_kind(f) is Category.VIDEO for f in self.media_files)

        side, layout = _side()
        self._quality = Segmented([(q.title, q) for q in effects.MediaQuality], effects.MediaQuality.BALANCED)
        self._quality.changed.connect(self._changed)
        layout.addWidget(self._quality)
        form = QFormLayout()
        self._height = QComboBox()
        for title, value in _HEIGHTS:
            self._height.addItem(title, value)
        self._height.currentIndexChanged.connect(self._changed)
        if has_video:
            form.addRow(L("Frame height"), self._height)
        layout.addLayout(form)
        self._hevc = QCheckBox(L("Use H.265 (smaller files)"))
        self._hevc.setVisible(has_video and media.has_encoder("libx265"))
        self._hevc.toggled.connect(self._changed)
        layout.addWidget(self._hevc)
        target = QHBoxLayout()
        self._use_target = QCheckBox(L("Aim for a size"))
        self._use_target.toggled.connect(self._changed)
        self._target = QDoubleSpinBox()
        self._target.setRange(0.1, 100_000)
        self._target.setValue(25.0)
        self._target.setSuffix(" " + L("MB"))
        self._target.valueChanged.connect(self._changed)
        target.addWidget(self._use_target)
        target.addWidget(self._target)
        layout.addLayout(target)
        self._estimate = QLabel("")
        self._estimate.setWordWrap(True)
        layout.addWidget(self._estimate)
        layout.addWidget(hint_label(L("A result that is not smaller than the original is not kept.")))
        if len(self.media_files) > 1:
            layout.addWidget(hint_label(fmt("The settings are applied to all {0} files.", len(self.media_files))))
        layout.addStretch(1)
        _two_columns(self, self._pane, side)

    def compression(self) -> effects.MediaCompression:
        return effects.MediaCompression(self._quality.value, self._height.currentData(), self._hevc.isChecked(),
                                        self._use_target.isChecked(), int(self._target.value() * 1_000_000))

    def _changed(self, *_args) -> None:  # noqa: ANN002
        self._target.setEnabled(self._use_target.isChecked())
        settings, path = self.compression(), self.first
        self._estimate.setText("…")
        self._estimator.request(lambda cancelled: effects.estimate_compressed_size(path, settings))

    @property
    def is_settled(self) -> bool:
        return super().is_settled and self._estimated_once

    def _estimated(self, size: int) -> None:
        self._estimated_once = True
        original = os.path.getsize(self.first)
        share = size / original * 100 if original else 0
        self._estimate.setText(fmt("About {0} instead of {1} ({2}%)", human_size(size), human_size(original), round(share)))

    def run(self) -> None:
        settings = self.compression()
        self.jobs.run_each(L("Compressing"), L("Compressed"), self.media_files,
                           lambda p, token, progress: effects.compress(p, settings, progress, token), max_concurrent=1)
        self.close()


def file_kind(path: str) -> Category | None:
    from ...core import file_format

    kind = file_format.detect(path)
    return kind.category if kind else None


# MARK: Join


class JoinTool(MediaToolWindow):
    def __init__(self, files: list[str], context) -> None:  # noqa: ANN001
        super().__init__(L("Join"), files, L("Join"), context, Category.VIDEO)
        self._list = QListWidget()
        self._list.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self._list.setMinimumSize(520, 260)
        self._info: dict[str, media.MediaInfo] = {}
        self._loader = LiveTask(0)
        self._loader.finished.connect(self._loaded)
        self._loader.failed.connect(lambda m: self.set_status(m))
        paths = list(self.media_files)
        self._loader.request(lambda cancelled: {p: media.probe(p) for p in paths}, immediate=True)
        self._settled = False

        layout = QVBoxLayout()
        layout.addWidget(hint_label(L("Drag the clips into the order you want. The first one sets the picture size; the "
                                      "others are fitted inside it.")))
        layout.addWidget(self._list, 1)
        row = QHBoxLayout()
        up = QPushButton(L("Move up"))
        up.clicked.connect(lambda: self._move(-1))
        down = QPushButton(L("Move down"))
        down.clicked.connect(lambda: self._move(1))
        row.addWidget(up)
        row.addWidget(down)
        row.addStretch(1)
        self._total = QLabel("")
        row.addWidget(self._total)
        layout.addLayout(row)
        self.set_body(layout=layout)
        self.set_action_enabled(False)

    @property
    def is_settled(self) -> bool:
        return self._settled

    def _loaded(self, infos: dict) -> None:
        self._info = infos
        for path in self.media_files:
            info = infos[path]
            size = f"{info.width}×{info.height}" if info.width else ""
            item = QListWidgetItem(f"{os.path.basename(path)}    {clock(info.duration or 0)}    {size}")
            item.setData(Qt.ItemDataRole.UserRole, path)
            self._list.addItem(item)
        total = sum(infos[p].duration or 0 for p in self.media_files)
        self._total.setText(fmt("Total: {0}", clock(total)))
        self.set_action_enabled(len(self.media_files) >= 2)
        self._settled = True

    def _move(self, step: int) -> None:
        row = self._list.currentRow()
        target = row + step
        if row < 0 or not 0 <= target < self._list.count():
            return
        item = self._list.takeItem(row)
        self._list.insertItem(target, item)
        self._list.setCurrentRow(target)

    def run(self) -> None:
        order = [self._list.item(i).data(Qt.ItemDataRole.UserRole) for i in range(self._list.count())]
        self.jobs.run_once(L("Joining videos"), L("Videos joined"), count(len(order), "file"),
                           lambda: effects.join(order))
        self.close()


@registry.register("tool.trimMedia")
def create_trim(files, context):  # noqa: ANN001, ANN201
    return TrimTool(files, context)


@registry.register("tool.splitMedia")
def create_split(files, context):  # noqa: ANN001, ANN201
    return SplitMediaTool(files, context)


@registry.register("tool.speed")
def create_speed(files, context):  # noqa: ANN001, ANN201
    return SpeedTool(files, context)


@registry.register("tool.frames")
def create_frames(files, context):  # noqa: ANN001, ANN201
    return FramesTool(files, context)


@registry.register("tool.compressMedia")
def create_compress(files, context):  # noqa: ANN001, ANN201
    return CompressMediaTool(files, context)


@registry.register("tool.join")
def create_join(files, context):  # noqa: ANN001, ANN201
    return JoinTool(files, context)


__all__ = ["TrimTool", "SplitMediaTool", "SpeedTool", "FramesTool", "CompressMediaTool", "JoinTool", "capabilities"]
