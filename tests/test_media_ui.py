"""The video and audio tool windows: the timeline's mouse handling and each tool run against real files."""

import os
import time

import pytest
from PySide6.QtCore import QEvent, QPointF, Qt
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import QApplication

from make_fixtures import tone, video
from mangosteen.core import capabilities
from mangosteen.core.cancellation import CancellationToken
from mangosteen.core.settings import Settings
from mangosteen.ui import teardown
from mangosteen.ui.tools import registry
from mangosteen.ui.tools.media_widgets import Timeline

pytestmark = pytest.mark.skipif(not capabilities.has_ffmpeg(), reason="needs ffmpeg")


class FakeJobs:
    """Runs the work at once and keeps the results."""

    def __init__(self):
        self.outputs = []

    def run_each(self, title, done, inputs, work, max_concurrent=1):
        for path in inputs:
            self.outputs.append(work(path, CancellationToken(), lambda _f: None))

    def run_once(self, title, done, label, work):
        self.outputs.append(work())


class Context:
    def __init__(self):
        self.jobs = FakeJobs()
        self.settings = Settings()


@pytest.fixture(autouse=True)
def no_player(monkeypatch):
    monkeypatch.setenv("MANGOSTEEN_NO_PLAYER", "1")


@pytest.fixture
def context(qapp):
    context = Context()
    yield context
    teardown.delete_windows(qapp)


def settle(window, timeout=30):
    started = time.monotonic()
    while not window.is_settled:
        QApplication.processEvents()
        time.sleep(0.02)
        assert time.monotonic() - started < timeout, "the window never settled"
    QApplication.processEvents()


def open_tool(tool_id, files, context):
    window = registry.create(tool_id, files, context)
    window.show()
    settle(window)
    return window


def mouse(widget, kind, x, y=30):
    button = Qt.MouseButton.LeftButton
    event = QMouseEvent(kind, QPointF(x, y), widget.mapToGlobal(QPointF(x, y)), button,
                        button if kind != QMouseEvent.Type.MouseButtonRelease else Qt.MouseButton.NoButton,
                        Qt.KeyboardModifier.NoModifier)
    QApplication.sendEvent(widget, event)


def click(widget, x, y=30):
    mouse(widget, QEvent.Type.MouseButtonPress, x, y)
    mouse(widget, QEvent.Type.MouseButtonRelease, x, y)


def drag(widget, x1, y1, x2, y2):
    mouse(widget, QEvent.Type.MouseButtonPress, x1, y1)
    mouse(widget, QEvent.Type.MouseMove, (x1 + x2) / 2, (y1 + y2) / 2)
    mouse(widget, QEvent.Type.MouseMove, x2, y2)
    mouse(widget, QEvent.Type.MouseButtonRelease, x2, y2)


# MARK: Timeline


def test_timeline_select_drag_handles(qapp):
    timeline = Timeline("select")
    timeline.resize(420, 96)
    timeline.set_duration(10.0)
    assert timeline.selection == (0.0, 10.0)
    start_x = timeline._x(0.0)
    drag(timeline, start_x, 40, timeline._x(2.5), 40)
    assert timeline.selection[0] == pytest.approx(2.5, abs=0.1)
    drag(timeline, timeline._x(10.0), 40, timeline._x(7.0), 40)
    assert timeline.selection[1] == pytest.approx(7.0, abs=0.1)
    click(timeline, timeline._x(5.0))
    assert timeline.position == pytest.approx(5.0, abs=0.1)


def test_timeline_markers_add_move_remove(qapp):
    timeline = Timeline("markers")
    timeline.resize(420, 96)
    timeline.set_duration(10.0)
    timeline.add_marker(4.0)
    timeline.add_marker(4.01)  # too close, ignored
    timeline.add_marker(0.0)   # at the edge, ignored
    assert timeline.markers == [4.0]
    drag(timeline, timeline._x(4.0), 40, timeline._x(6.0), 40)
    assert timeline.markers[0] == pytest.approx(6.0, abs=0.1)
    mouse(timeline, QEvent.Type.MouseButtonDblClick, timeline._x(6.0), 40)
    assert timeline.markers == []


def test_timeline_ranges_select_and_edit(qapp):
    timeline = Timeline("ranges")
    timeline.resize(420, 96)
    timeline.set_duration(10.0)
    timeline.add_range(1.0, 2.0)
    timeline.add_range(5.0, 6.0)
    assert timeline.current == 1
    click(timeline, timeline._x(1.5))
    assert timeline.current == 0
    drag(timeline, timeline._x(2.0), 40, timeline._x(3.0), 40)
    assert timeline.ranges[0][1] == pytest.approx(3.0, abs=0.1)
    timeline.remove_current_range()
    assert timeline.ranges == [(5.0, 6.0)] and timeline.current == 0


# MARK: Tools


def test_trim_tool_runs_with_the_typed_times(work, context):
    source = tone(str(work / "a.wav"), seconds=3.0)
    window = open_tool("tool.trimMedia", [source], context)
    window._start.setText("0:00.5")
    window._end.setText("0:02")
    window._typed()
    window.run()
    assert os.path.basename(context.jobs.outputs[0]) == "a (trimmed).wav"


def test_split_tool_makes_equal_parts(work, context):
    source = tone(str(work / "a.wav"), seconds=3.0)
    window = open_tool("tool.splitMedia", [source], context)
    assert not window._action.isEnabled()
    window._parts.setValue(3)
    window._equal()
    assert window._action.isEnabled()
    window.run()
    assert sorted(os.listdir(context.jobs.outputs[0])) == ["a 1.wav", "a 2.wav", "a 3.wav"]


def test_speed_tool_applies_to_every_file(work, context):
    a = tone(str(work / "a.wav"), seconds=1.0)
    b = tone(str(work / "b.wav"), seconds=1.0)
    window = open_tool("tool.speed", [a, b], context)
    window._factor.setValue(2.0)
    window.run()
    assert [os.path.basename(o) for o in context.jobs.outputs] == ["a (speed ×2).wav", "b (speed ×2).wav"]


def test_frames_tool_collects_times(work, context):
    source = video(str(work / "v.mp4"), seconds=2)
    window = open_tool("tool.frames", [source], context)
    window._step.setValue(1.0)
    window._every()
    assert len(window._times) == 2
    window.run()
    assert os.path.isdir(context.jobs.outputs[0])


def test_join_tool_keeps_the_list_order(work, context):
    a = video(str(work / "a.mp4"), seconds=1)
    b = video(str(work / "b.mp4"), seconds=1)
    window = open_tool("tool.join", [a, b], context)
    window._list.setCurrentRow(1)
    window._move(-1)
    window.run()
    assert os.path.basename(context.jobs.outputs[0]) == "Joined.mp4"


def test_compress_tool_estimates_and_runs(work, context):
    source = video(str(work / "v.mp4"), seconds=2)
    window = open_tool("tool.compressMedia", [source], context)
    assert "%" in window._estimate.text()
    window._use_target.setChecked(True)
    window._target.setValue(0.01)
    from mangosteen.imaging.compress import NotSmaller

    try:  # a 27 KB test clip may well not get any smaller; either outcome is the tool doing its job
        window.run()
    except NotSmaller:
        pass


def test_bleep_tool_adds_and_runs(work, context):
    source = tone(str(work / "a.wav"), seconds=3.0)
    window = open_tool("tool.bleep", [source], context)
    assert not window._action.isEnabled()
    window._pane.seek(1.0)
    window._add()
    assert window._action.isEnabled()
    window.run()
    assert "(bleeped)" in context.jobs.outputs[0]


def test_normalize_tool_measures_and_runs(work, context):
    source = tone(str(work / "a.wav"), seconds=3.0)
    window = open_tool("tool.normalize", [source], context)
    assert "LUFS" in window._now.text()
    window._level.setValue(-20.0)
    window.run()
    assert "(volume)" in context.jobs.outputs[0]


def test_channels_tool_runs(work, context):
    source = tone(str(work / "a.wav"), seconds=1.0)
    window = open_tool("tool.channels", [source], context)
    window.run()
    assert "(channels)" in context.jobs.outputs[0]


def test_visualizer_tool_renders_a_preview_and_runs(work, context):
    source = tone(str(work / "a.wav"), seconds=1.0)
    window = open_tool("tool.visualizer", [source], context)
    assert window._preview._pixmap is not None
    window.run()
    assert context.jobs.outputs[0].endswith(".mp4")


def test_crop_video_tool_runs_with_the_chosen_shape(work, context):
    source = video(str(work / "v.mp4"), seconds=1, size="320x240")
    window = open_tool("tool.cropVideo", [source], context)
    window._aspect.setCurrentIndex(1)  # 1:1
    window.run()
    from mangosteen.convert import media

    info = media.probe(context.jobs.outputs[0])
    assert abs(info.width - info.height) <= 2


def test_redact_video_tool_draws_an_area_and_runs(work, context):
    source = video(str(work / "v.mp4"), seconds=2, size="320x240")
    window = open_tool("tool.redactVideo", [source], context)
    assert not window._action.isEnabled()
    canvas = window._canvas
    rect = canvas.image_rect()
    drag(canvas, rect.x() + 20, rect.y() + 20, rect.x() + 120, rect.y() + 90)
    assert len(canvas.regions) == 1 and len(window._pane.timeline.ranges) == 1
    assert window._action.isEnabled()
    window.run()
    assert "(hidden)" in context.jobs.outputs[0]
