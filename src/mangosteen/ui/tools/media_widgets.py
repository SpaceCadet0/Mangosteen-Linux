"""The pieces the video and audio tools share: a player, a timeline with thumbnails or a waveform, and a pane that
puts them together with a transport bar."""

from __future__ import annotations

import functools
import os
from dataclasses import dataclass

from PySide6.QtCore import QObject, QPointF, QRectF, Qt, QUrl, Signal
from PySide6.QtGui import QColor, QImage, QPainter, QPen, QPixmap, QPolygonF
from PySide6.QtWidgets import QHBoxLayout, QLabel, QToolButton, QVBoxLayout, QWidget

from ...convert import media, qtutil
from ...core import file_format
from ...core.file_format import Category
from ...core.loc import L
from ...mediatools import cut
from .. import brand, glyphs
from ..widgets import LiveTask
from .base import ToolWindow

_MIN_GAP = 0.05


def clock(seconds: float) -> str:
    """"1:02.5" for readouts."""
    seconds = max(seconds, 0.0)
    minutes, rest = divmod(seconds, 60)
    hours, minutes = divmod(int(minutes), 60)
    if hours:
        return f"{hours}:{minutes:02d}:{rest:04.1f}"
    return f"{minutes}:{rest:04.1f}"


# MARK: Player


@functools.lru_cache(maxsize=1)
def has_playback() -> bool:
    """Whether Qt can play media here. Some PySide6 builds (for ARM, on a Raspberry Pi) ship QtMultimedia without a
    backend: a player can be made but plays nothing. Asked once, so Qt's warning about it appears only once."""
    try:
        from PySide6.QtMultimedia import QMediaPlayer
    except ImportError:
        return False
    player = QMediaPlayer()
    available = player.isAvailable()
    player.deleteLater()
    return available


class MediaPlayer(QObject):
    """QMediaPlayer with the sound output and an optional video widget. Without Qt's multimedia backend (or with
    MANGOSTEEN_NO_PLAYER set, which the snapshots use) it does nothing and `available` is False; the windows then
    show still frames instead."""

    position_changed = Signal(float)  # seconds
    playing_changed = Signal(bool)

    def __init__(self, with_video: bool) -> None:
        super().__init__()
        self.available = False
        self.video_widget = None
        self._stop_at: float | None = None
        self._player = None
        if os.environ.get("MANGOSTEEN_NO_PLAYER") or not has_playback():
            return
        from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
        from PySide6.QtMultimediaWidgets import QVideoWidget

        self._player = QMediaPlayer()
        self._output = QAudioOutput()
        self._player.setAudioOutput(self._output)
        if with_video:
            self.video_widget = QVideoWidget()
            self._player.setVideoOutput(self.video_widget)
        self._player.positionChanged.connect(self._moved)
        self._player.playbackStateChanged.connect(lambda state: self.playing_changed.emit(self.is_playing))
        self.available = True

    def load(self, path: str) -> None:
        if self._player is not None:
            self._player.setSource(QUrl.fromLocalFile(path))

    @property
    def is_playing(self) -> bool:
        return self._player is not None and self._player.playbackState() == self._player.PlaybackState.PlayingState

    def play(self, stop_at: float | None = None) -> None:
        if self._player is not None:
            self._stop_at = stop_at
            self._player.play()

    def pause(self) -> None:
        if self._player is not None:
            self._player.pause()

    def toggle(self) -> None:
        self.pause() if self.is_playing else self.play()

    def seek(self, seconds: float) -> None:
        if self._player is not None:
            self._player.setPosition(int(max(seconds, 0) * 1000))

    def position(self) -> float:
        return self._player.position() / 1000.0 if self._player is not None else 0.0

    def set_rate(self, rate: float) -> None:
        if self._player is not None:
            self._player.setPlaybackRate(rate)

    def set_volume(self, volume: float) -> None:
        if self._player is not None:
            self._output.setVolume(min(max(volume, 0.0), 1.0))

    def _moved(self, milliseconds: int) -> None:
        seconds = milliseconds / 1000.0
        if self._stop_at is not None and seconds >= self._stop_at:
            self._stop_at = None
            self.pause()
        self.position_changed.emit(seconds)

    def release(self) -> None:
        """Stops playback and lets go of the file."""
        if self._player is not None:
            self._player.stop()
            self._player.setSource(QUrl())


# MARK: Timeline


class Timeline(QWidget):
    """A strip showing the file (frames or a waveform) with a playhead.

    mode "seek": only the playhead. "select": one range with two handles. "markers": cut points that can be dragged
    and removed by double-clicking. "ranges": several ranges, one of them current and editable."""

    position_changed = Signal(float)
    selection_changed = Signal(float, float)
    markers_changed = Signal()
    ranges_changed = Signal()
    current_changed = Signal(int)

    _PAD = 10.0
    _GRAB = 7.0

    def __init__(self, mode: str = "seek") -> None:
        super().__init__()
        self.mode = mode
        self.duration = 0.0
        self.position = 0.0
        self.selection = (0.0, 0.0)
        self.markers: list[float] = []
        self.ranges: list[tuple[float, float]] = []
        self.current = -1
        self.thumbnails: list[QPixmap] = []
        self.peaks: list[float] = []
        self._drag: tuple | None = None
        self.setMinimumHeight(96)
        self.setMinimumWidth(320)
        self.setMouseTracking(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    # State

    def set_duration(self, duration: float) -> None:
        self.duration = max(duration, 0.0)
        if self.mode == "select":
            self.selection = (0.0, self.duration)
        self.update()

    def set_position(self, seconds: float) -> None:
        self.position = min(max(seconds, 0.0), self.duration)
        self.update()

    def set_thumbnails(self, images: list[QImage]) -> None:
        self.thumbnails = [QPixmap.fromImage(i) for i in images]
        self.update()

    def set_peaks(self, peaks: list[float]) -> None:
        self.peaks = list(peaks)
        self.update()

    def set_selection(self, start: float, end: float, emit: bool = False) -> None:
        self.selection = (min(max(start, 0.0), self.duration), min(max(end, 0.0), self.duration))
        self.update()
        if emit:
            self.selection_changed.emit(*self.selection)

    def add_marker(self, seconds: float) -> None:
        if _MIN_GAP < seconds < self.duration - _MIN_GAP and all(abs(seconds - m) > _MIN_GAP for m in self.markers):
            self.markers = sorted([*self.markers, seconds])
            self.markers_changed.emit()
            self.update()

    def set_markers(self, markers: list[float]) -> None:
        self.markers = sorted(markers)
        self.markers_changed.emit()
        self.update()

    def add_range(self, start: float, end: float) -> None:
        self.ranges.append((min(start, end), max(start, end)))
        self.current = len(self.ranges) - 1
        self.ranges_changed.emit()
        self.current_changed.emit(self.current)
        self.update()

    def remove_current_range(self) -> None:
        if 0 <= self.current < len(self.ranges):
            del self.ranges[self.current]
            self.current = min(self.current, len(self.ranges) - 1)
            self.ranges_changed.emit()
            self.current_changed.emit(self.current)
            self.update()

    def set_current(self, index: int) -> None:
        self.current = index
        self.current_changed.emit(index)
        self.update()

    def set_current_range(self, start: float, end: float) -> None:
        if 0 <= self.current < len(self.ranges):
            self.ranges[self.current] = (min(max(min(start, end), 0.0), self.duration),
                                         min(max(max(start, end), 0.0), self.duration))
            self.ranges_changed.emit()
            self.update()

    # Geometry

    def _strip(self) -> QRectF:
        return QRectF(self._PAD, 10, max(self.width() - 2 * self._PAD, 1), max(self.height() - 20, 1))

    def _x(self, seconds: float) -> float:
        strip = self._strip()
        return strip.x() + (seconds / self.duration if self.duration > 0 else 0.0) * strip.width()

    def _time(self, x: float) -> float:
        strip = self._strip()
        return min(max((x - strip.x()) / strip.width(), 0.0), 1.0) * self.duration

    # Painting

    def paintEvent(self, _event) -> None:  # noqa: ANN001, N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        strip = self._strip()
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(128, 128, 128, 40))
        painter.drawRoundedRect(strip, 8, 8)
        painter.save()
        clip = painter.clipPath()
        from PySide6.QtGui import QPainterPath

        path = QPainterPath()
        path.addRoundedRect(strip, 8, 8)
        painter.setClipPath(path)
        if self.thumbnails:
            cell = strip.width() / len(self.thumbnails)
            for index, pixmap in enumerate(self.thumbnails):
                target = QRectF(strip.x() + index * cell, strip.y(), cell + 0.5, strip.height())
                ratio = max(target.width() / pixmap.width(), target.height() / pixmap.height())
                source_w, source_h = target.width() / ratio, target.height() / ratio
                source = QRectF((pixmap.width() - source_w) / 2, (pixmap.height() - source_h) / 2, source_w, source_h)
                painter.drawPixmap(target, pixmap, source)
        elif self.peaks:
            painter.setBrush(brand.accent())
            middle = strip.center().y()
            count = len(self.peaks)
            bar = strip.width() / count
            for index, level in enumerate(self.peaks):
                height = max(level * (strip.height() - 8), 1.5)
                painter.drawRoundedRect(QRectF(strip.x() + index * bar + bar * 0.15, middle - height / 2, max(bar * 0.7, 1.0),
                                               height), 1, 1)
        if self.mode == "select" and self.duration > 0:
            painter.setBrush(QColor(0, 0, 0, 130))
            painter.drawRect(QRectF(strip.x(), strip.y(), self._x(self.selection[0]) - strip.x(), strip.height()))
            painter.drawRect(QRectF(self._x(self.selection[1]), strip.y(), strip.right() - self._x(self.selection[1]),
                                    strip.height()))
        if self.mode == "ranges":
            for index, (start, end) in enumerate(self.ranges):
                shade = QColor(brand.accent())
                shade.setAlpha(110 if index == self.current else 60)
                painter.setBrush(shade)
                painter.drawRect(QRectF(self._x(start), strip.y(), max(self._x(end) - self._x(start), 1), strip.height()))
        painter.restore()
        del clip

        yellow = QColor(255, 214, 10)
        if self.mode == "select" and self.duration > 0:
            painter.setPen(QPen(yellow, 2))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRect(QRectF(self._x(self.selection[0]), strip.y(), self._x(self.selection[1]) - self._x(self.selection[0]),
                                    strip.height()))
            self._handle(painter, self._x(self.selection[0]), yellow)
            self._handle(painter, self._x(self.selection[1]), yellow)
        if self.mode == "ranges":
            for index, (start, end) in enumerate(self.ranges):
                painter.setPen(QPen(yellow if index == self.current else QColor(255, 255, 255, 170), 1.5))
                painter.setBrush(Qt.BrushStyle.NoBrush)
                painter.drawRect(QRectF(self._x(start), strip.y(), max(self._x(end) - self._x(start), 1), strip.height()))
                if index == self.current:
                    self._handle(painter, self._x(start), yellow)
                    self._handle(painter, self._x(end), yellow)
        if self.mode == "markers":
            painter.setPen(QPen(QColor("white"), 1.5))
            painter.setBrush(QColor("white"))
            for marker in self.markers:
                x = self._x(marker)
                painter.drawLine(QPointF(x, strip.y()), QPointF(x, strip.bottom()))
                painter.drawPolygon(QPolygonF([QPointF(x - 5, strip.y() - 4), QPointF(x + 5, strip.y() - 4),
                                               QPointF(x, strip.y() + 4)]))
        x = self._x(self.position)
        painter.setPen(QPen(QColor(255, 59, 48), 2))
        painter.setBrush(QColor(255, 59, 48))
        painter.drawLine(QPointF(x, strip.y() - 2), QPointF(x, strip.bottom() + 2))
        painter.drawPolygon(QPolygonF([QPointF(x - 5, strip.y() - 8), QPointF(x + 5, strip.y() - 8), QPointF(x, strip.y())]))

    def _handle(self, painter: QPainter, x: float, color: QColor) -> None:
        strip = self._strip()
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(color)
        painter.drawRoundedRect(QRectF(x - 4, strip.y() + strip.height() / 2 - 14, 8, 28), 3, 3)

    # Mouse

    def _hit(self, x: float) -> tuple | None:
        if self.mode == "select":
            for name, seconds in (("start", self.selection[0]), ("end", self.selection[1])):
                if abs(self._x(seconds) - x) <= self._GRAB:
                    return (name,)
        elif self.mode == "markers":
            for index, marker in enumerate(self.markers):
                if abs(self._x(marker) - x) <= self._GRAB:
                    return ("marker", index)
        elif self.mode == "ranges" and 0 <= self.current < len(self.ranges):
            start, end = self.ranges[self.current]
            if abs(self._x(start) - x) <= self._GRAB:
                return ("range_start",)
            if abs(self._x(end) - x) <= self._GRAB:
                return ("range_end",)
        return None

    def mousePressEvent(self, event) -> None:  # noqa: ANN001, N802
        if event.button() != Qt.MouseButton.LeftButton or self.duration <= 0:
            return
        x = event.position().x()
        self._drag = self._hit(x)
        if self._drag is None:
            if self.mode == "ranges":
                seconds = self._time(x)
                for index in range(len(self.ranges) - 1, -1, -1):
                    if self.ranges[index][0] <= seconds <= self.ranges[index][1] and index != self.current:
                        self.set_current(index)
                        break
            self._drag = ("seek",)
            self.set_position(self._time(x))
            self.position_changed.emit(self.position)

    def mouseMoveEvent(self, event) -> None:  # noqa: ANN001, N802
        x = event.position().x()
        if self._drag is None:
            self.setCursor(Qt.CursorShape.SizeHorCursor if self._hit(x) else Qt.CursorShape.PointingHandCursor)
            return
        seconds = self._time(x)
        kind = self._drag[0]
        if kind == "seek":
            self.set_position(seconds)
            self.position_changed.emit(self.position)
        elif kind == "start":
            self.set_selection(min(seconds, self.selection[1] - _MIN_GAP), self.selection[1], emit=True)
        elif kind == "end":
            self.set_selection(self.selection[0], max(seconds, self.selection[0] + _MIN_GAP), emit=True)
        elif kind == "marker":
            index = self._drag[1]
            self.markers[index] = min(max(seconds, _MIN_GAP), self.duration - _MIN_GAP)
            self.markers_changed.emit()
            self.update()
        elif kind == "range_start":
            start, end = self.ranges[self.current]
            self.set_current_range(min(seconds, end - _MIN_GAP), end)
        elif kind == "range_end":
            start, end = self.ranges[self.current]
            self.set_current_range(start, max(seconds, start + _MIN_GAP))

    def mouseReleaseEvent(self, _event) -> None:  # noqa: ANN001, N802
        if self._drag is not None and self._drag[0] == "marker":
            self.markers.sort()
            self.markers_changed.emit()
        self._drag = None
        self.update()

    def mouseDoubleClickEvent(self, event) -> None:  # noqa: ANN001, N802
        hit = self._hit(event.position().x())
        if hit is not None and hit[0] == "marker":
            del self.markers[hit[1]]
            self.markers_changed.emit()
            self.update()


# MARK: Pane


@dataclass
class Loaded:
    info: media.MediaInfo
    thumbnails: list
    peaks: list[float]


class MediaPane(QWidget):
    """The file's picture (or a still frame without a player), the timeline and the transport bar."""

    loaded = Signal(object)  # Loaded
    position_changed = Signal(float)

    def __init__(self, path: str, mode: str = "seek", show_picture: bool = True, thumbnail_height: int = 64) -> None:
        super().__init__()
        kind = file_format.detect(path)
        show_picture = show_picture and kind is not None and kind.category is Category.VIDEO
        self.path = path
        self.info = media.MediaInfo()
        self._thumbnail_height = thumbnail_height
        self.timeline = Timeline(mode)
        self.player = MediaPlayer(with_video=show_picture)
        self.picture: QWidget | None = None
        self._still: QLabel | None = None
        self._still_task = LiveTask(80)
        self._still_task.finished.connect(self._show_still)
        self._settled = False

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        if show_picture:
            if self.player.video_widget is not None:
                self.picture = self.player.video_widget
                self.picture.setMinimumSize(480, 270)
            else:
                self._still = QLabel("…")
                self._still.setAlignment(Qt.AlignmentFlag.AlignCenter)
                self._still.setMinimumSize(480, 270)
                self._still.setStyleSheet("background: rgba(128,128,128,40); border-radius: 10px;")
                self.picture = self._still
            layout.addWidget(self.picture, 1)
        layout.addWidget(self.timeline)

        self._play = QToolButton()
        self._play.setAutoRaise(True)
        self._play.clicked.connect(self._toggle)
        self._time = QLabel("0:00.0 / 0:00.0")
        self._time.setStyleSheet("color: gray;")
        row = QHBoxLayout()
        row.addWidget(self._play)
        row.addWidget(self._time)
        row.addStretch(1)
        self._extras = row
        layout.addLayout(row)
        self._refresh_play(False)

        self.timeline.position_changed.connect(self._scrubbed)
        self.player.position_changed.connect(self._played)
        self.player.playing_changed.connect(self._refresh_play)
        self.player.load(path)
        self._loader = LiveTask(0)
        self._loader.finished.connect(self._loaded)
        self._loader.failed.connect(self._failed)
        self._loader.request(self._load, immediate=True)

    # Loading

    def _load(self, cancelled) -> Loaded:  # noqa: ANN001
        info = media.probe(self.path)
        thumbnails: list = []
        if info.has_video and info.duration:
            aspect = (info.width or 16) / max(info.height or 9, 1)
            count = max(4, min(24, int(640 / max(self._thumbnail_height * aspect, 1))))
            thumbnails = cut.thumbnails(self.path, info.duration, count, self._thumbnail_height, cancelled=cancelled)
        peaks: list[float] = []
        if info.has_audio and info.duration and not thumbnails:
            try:
                peaks = cut.waveform(self.path, info.duration, 480)
            except Exception:  # noqa: BLE001 - a missing waveform is not an error
                peaks = []
        return Loaded(info, thumbnails, peaks)

    def _loaded(self, result: Loaded) -> None:
        self.info = result.info
        self.timeline.set_duration(result.info.duration or 0.0)
        self.timeline.set_thumbnails([qtutil.pil_to_qimage(i) for i in result.thumbnails])
        self.timeline.set_peaks(result.peaks)
        self._settled = True
        self._update_time()
        if self._still is not None:
            self.show_frame_at(0.0)
        self.loaded.emit(result)

    def _failed(self, message: str) -> None:
        self._time.setText(message)
        self._settled = True

    @property
    def is_settled(self) -> bool:
        return self._settled and (self._still is None or self._still.pixmap() is not None and not self._still.pixmap().isNull())

    def add_control(self, widget: QWidget) -> None:
        """Adds a control to the transport row."""
        self._extras.addWidget(widget)

    # Transport

    def _refresh_play(self, playing: bool) -> None:
        self._play.setIcon(glyphs.icon("pause" if playing else "play", 20))
        self._play.setEnabled(self.player.available)
        self._play.setToolTip(L("Play") if not playing else L("Pause"))

    def _toggle(self) -> None:
        if not self.player.is_playing and self.timeline.mode == "select":
            start, end = self.timeline.selection
            if not start <= self.player.position() < end:
                self.player.seek(start)
        self.player.toggle()

    def play_range(self, start: float, end: float) -> None:
        self.player.seek(start)
        self.player.play(stop_at=end)

    def _scrubbed(self, seconds: float) -> None:
        self.player.seek(seconds)
        self._update_time()
        if self._still is not None:
            self.show_frame_at(seconds)
        self.position_changed.emit(seconds)

    def _played(self, seconds: float) -> None:
        self.timeline.set_position(seconds)
        self._update_time()
        self.position_changed.emit(seconds)

    def seek(self, seconds: float) -> None:
        self.timeline.set_position(seconds)
        self._scrubbed(self.timeline.position)

    def _update_time(self) -> None:
        self._time.setText(f"{clock(self.timeline.position)} / {clock(self.timeline.duration)}")

    # Still frames, when there is no player

    def show_frame_at(self, seconds: float) -> None:
        if self._still is None:
            return
        path = self.path
        self._still_task.request(lambda cancelled: cut.frame(path, seconds, 540))

    def _show_still(self, image) -> None:  # noqa: ANN001
        if self._still is None:
            return
        pixmap = QPixmap.fromImage(qtutil.pil_to_qimage(image))
        self._still.setPixmap(pixmap.scaled(self._still.size(), Qt.AspectRatioMode.KeepAspectRatio,
                                            Qt.TransformationMode.SmoothTransformation))

    def shutdown(self) -> None:
        self.player.release()


class MediaToolWindow(ToolWindow):
    """A tool window for video and audio files: it knows which of the files are media and lets go of them (stopping
    playback) when it closes."""

    def __init__(self, title: str, files: list[str], action_title: str, context, category: Category | None = None) -> None:  # noqa: ANN001
        def wanted(path: str) -> bool:
            kind = file_format.detect(path)
            return kind is not None and kind.category.is_media and (category is None or kind.category is category)

        self.media_files = [f for f in files if wanted(f)]
        self._panes: list[MediaPane] = []
        super().__init__(title, files, action_title, context)

    @property
    def first(self) -> str:
        return self.media_files[0]

    def pane(self, *args, **kwargs) -> MediaPane:  # noqa: ANN002, ANN003
        pane = MediaPane(*args, **kwargs)
        self._panes.append(pane)
        return pane

    @property
    def is_settled(self) -> bool:
        return all(p.is_settled for p in self._panes)

    def closeEvent(self, event) -> None:  # noqa: ANN001, N802
        for pane in self._panes:
            pane.shutdown()
        super().closeEvent(event)


def time_field(placeholder: str = "0:00.000"):  # noqa: ANN201
    from PySide6.QtWidgets import QLineEdit

    field = QLineEdit()
    field.setPlaceholderText(placeholder)
    field.setMaximumWidth(120)
    return field


__all__ = ["MediaPlayer", "Timeline", "MediaPane", "MediaToolWindow", "Loaded", "clock", "time_field"]
