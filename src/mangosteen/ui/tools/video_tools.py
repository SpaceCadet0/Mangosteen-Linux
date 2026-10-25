"""Picture tools for video: Reframe (crop) and Hide (cover areas for a stretch of time)."""

from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QImage, QPainter, QPen
from PySide6.QtWidgets import QComboBox, QFormLayout, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from ...convert import qtutil
from ...core.file_format import Category
from ...core.loc import L, count, fmt
from ...imaging.compose import RGBA
from ...imaging.geometry import UnitRect, centered_rect
from ...imaging.redact import RedactionStyle
from ...mediatools import cut, effects, redact_video
from ..widgets import ColorButton, LiveTask, Segmented, hint_label
from . import registry
from .crop_canvas import CropCanvas
from .media_tools import _note_for_many, _side
from .media_widgets import MediaToolWindow, clock, time_field

_FRAME_HEIGHT = 720

_ASPECTS = [(L("Free"), None), (L("1:1"), 1.0), (L("4:3"), 4 / 3), (L("3:2"), 3 / 2), (L("16:9"), 16 / 9),
            (L("9:16"), 9 / 16), (L("3:4"), 3 / 4), (L("4:5"), 4 / 5)]


# MARK: Reframe


class CropVideoTool(MediaToolWindow):
    def __init__(self, files: list[str], context) -> None:  # noqa: ANN001
        super().__init__(L("Reframe"), files, L("Reframe"), context, Category.VIDEO)
        self._canvas = CropCanvas()
        self._canvas.setMinimumSize(560, 340)
        self._canvas.rect_changed.connect(lambda _r: self._update_size())
        self._pane = self.pane(self.first, mode="seek", show_picture=False, thumbnail_height=40)
        self._frame = LiveTask(120)
        self._frame.finished.connect(self._frame_ready)
        self._frame.failed.connect(lambda m: self._canvas.set_image(None, m))
        self._pane.position_changed.connect(self._request_frame)
        self._pane.loaded.connect(lambda _r: self._request_frame(0.0))
        self._frame_size = (1, 1)
        self._drawn = False

        side, layout = _side(260)
        form = QFormLayout()
        self._aspect = QComboBox()
        for title, ratio in _ASPECTS:
            self._aspect.addItem(title, ratio)
        self._aspect.currentIndexChanged.connect(self._aspect_changed)
        form.addRow(L("Shape"), self._aspect)
        layout.addLayout(form)
        self._size = QLabel("")
        layout.addWidget(self._size)
        layout.addWidget(hint_label(L("Drag the frame or its corners. Move the playhead to see another moment.")))
        if len(self.media_files) > 1:
            layout.addWidget(hint_label(fmt("The same frame is cut from all {0} videos.", len(self.media_files))))
        layout.addStretch(1)

        left = QVBoxLayout()
        left.addWidget(self._canvas, 1)
        left.addWidget(self._pane)
        outer = QHBoxLayout()
        outer.setSpacing(18)
        outer.addLayout(left, 1)
        outer.addWidget(side, alignment=Qt.AlignmentFlag.AlignTop)
        self.set_body(layout=outer)
        self.set_action_enabled(False)

    @property
    def is_settled(self) -> bool:
        return super().is_settled and self._drawn

    def _request_frame(self, seconds: float) -> None:
        path = self.first
        self._frame.request(lambda cancelled: cut.frame(path, seconds, _FRAME_HEIGHT))

    def _frame_ready(self, image) -> None:  # noqa: ANN001
        self._canvas.set_image(qtutil.pil_to_qimage(image))
        if not self._drawn:
            real = self._pane.info
            self._frame_size = (real.width or image.width, real.height or image.height)
            self._drawn = True
            self.set_action_enabled(True)
            self._aspect_changed()
        self._update_size()

    def _aspect_changed(self) -> None:
        ratio = self._aspect.currentData()
        width, height = self._frame_size
        self._canvas.set_aspect(ratio * height / width if ratio else None)
        if ratio:
            self._canvas.set_rect(centered_rect(ratio, width, height))
        self._update_size()

    def _update_size(self) -> None:
        width, height = self._frame_size
        pixels = self._canvas.unit_rect.to_pixels(width, height)
        self._size.setText(fmt("Result: {0} × {1}", pixels.width // 2 * 2, pixels.height // 2 * 2))

    def run(self) -> None:
        rect = self._canvas.unit_rect
        self.jobs.run_each(L("Reframing"), L("Reframed"), self.media_files,
                           lambda p, token, progress: effects.crop_video(p, rect, None, progress, token), max_concurrent=1)
        self.close()


# MARK: Hide


class _RegionCanvas(QWidget):
    """The video frame with the hidden areas on it; click an area to select it, drag on an empty spot to add one."""

    added = Signal(object)  # UnitRect
    selected = Signal(int)

    def __init__(self) -> None:
        super().__init__()
        self.setMinimumSize(560, 340)
        self.image: QImage | None = None
        self.regions: list[UnitRect] = []
        self.current = -1
        self._start: QPointF | None = None
        self._drag: QRectF | None = None
        self._message = "…"
        self.setCursor(Qt.CursorShape.CrossCursor)

    def set_image(self, image: QImage | None, message: str = "…") -> None:
        self.image, self._message = image, message
        self.update()

    def image_rect(self) -> QRectF:
        if self.image is None:
            return QRectF()
        area = QRectF(self.rect()).adjusted(10, 10, -10, -10)
        size = self.image.size().scaled(area.size().toSize(), Qt.AspectRatioMode.KeepAspectRatio)
        rect = QRectF(0, 0, size.width(), size.height())
        rect.moveCenter(area.center())
        return rect

    def _unit(self, point: QPointF) -> tuple[float, float]:
        rect = self.image_rect()
        return (min(max((point.x() - rect.x()) / rect.width(), 0.0), 1.0),
                min(max((point.y() - rect.y()) / rect.height(), 0.0), 1.0))

    def mousePressEvent(self, event) -> None:  # noqa: ANN001, N802
        if self.image is None or event.button() != Qt.MouseButton.LeftButton:
            return
        x, y = self._unit(event.position())
        for index in range(len(self.regions) - 1, -1, -1):
            r = self.regions[index]
            if r.x <= x <= r.right and r.y <= y <= r.bottom:
                self.selected.emit(index)
                return
        self._start = event.position()
        self._drag = QRectF(self._start, self._start)

    def mouseMoveEvent(self, event) -> None:  # noqa: ANN001, N802
        if self._start is not None:
            self._drag = QRectF(self._start, event.position()).normalized()
            self.update()

    def mouseReleaseEvent(self, _event) -> None:  # noqa: ANN001, N802
        if self._start is None or self._drag is None:
            return
        rect = self.image_rect()
        area = self._drag.intersected(rect)
        self._start = self._drag = None
        if area.width() > 6 and area.height() > 6:
            self.added.emit(UnitRect((area.x() - rect.x()) / rect.width(), (area.y() - rect.y()) / rect.height(),
                                     area.width() / rect.width(), area.height() / rect.height()))
        self.update()

    def paintEvent(self, _event) -> None:  # noqa: ANN001, N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(128, 128, 128, 36))
        painter.drawRoundedRect(self.rect(), 10, 10)
        if self.image is None:
            painter.setPen(QColor(128, 128, 128))
            painter.drawText(self.rect(), int(Qt.AlignmentFlag.AlignCenter), self._message)
            return
        rect = self.image_rect()
        painter.drawImage(rect, self.image)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        for index, r in enumerate(self.regions):
            painter.setPen(QPen(QColor(255, 214, 10) if index == self.current else QColor(255, 255, 255, 190),
                                2.5 if index == self.current else 1.5))
            painter.drawRect(QRectF(rect.x() + r.x * rect.width(), rect.y() + r.y * rect.height(), r.width * rect.width(),
                                    r.height * rect.height()))
        if self._drag is not None:
            painter.setPen(QPen(QColor("white"), 1.5, Qt.PenStyle.DashLine))
            painter.drawRect(self._drag)


class RedactVideoTool(MediaToolWindow):
    def __init__(self, files: list[str], context) -> None:  # noqa: ANN001
        super().__init__(L("Hide"), files, L("Hide"), context, Category.VIDEO)
        self._canvas = _RegionCanvas()
        self._canvas.added.connect(self._add_region)
        self._canvas.selected.connect(self._select)
        self._pane = self.pane(self.first, mode="ranges", show_picture=False, thumbnail_height=40)
        timeline = self._pane.timeline
        timeline.ranges_changed.connect(self._ranges_changed)
        timeline.current_changed.connect(self._current_changed)
        self._frame = LiveTask(150)
        self._frame.finished.connect(self._frame_ready)
        self._frame.failed.connect(lambda m: self._canvas.set_image(None, m))
        self._pane.position_changed.connect(lambda _s: self._request_frame())
        self._pane.loaded.connect(self._loaded)
        self._frame_size = (1, 1)
        self._drawn = False
        self._style = RedactionStyle.BLUR
        self._color = RGBA(0, 0, 0)

        side, layout = _side(280)
        self._style_control = Segmented([(L("Fill"), RedactionStyle.SOLID), (L("Blur"), RedactionStyle.BLUR),
                                         (L("Pixels"), RedactionStyle.PIXELATE)], RedactionStyle.BLUR)
        self._style_control.changed.connect(self._style_changed)
        layout.addWidget(self._style_control)
        form = QFormLayout()
        self._fill = ColorButton(QColor("black"))
        self._fill.changed.connect(lambda c: (setattr(self, "_color", RGBA.from_qcolor(c)), self._request_frame()))
        self._fill_label = QLabel(L("Colour"))
        form.addRow(self._fill_label, self._fill)
        self._fill.setVisible(False)
        self._fill_label.setVisible(False)
        self._from = time_field()
        self._to = time_field()
        self._from.editingFinished.connect(self._typed)
        self._to.editingFinished.connect(self._typed)
        form.addRow(L("From"), self._from)
        form.addRow(L("To"), self._to)
        layout.addLayout(form)
        remove = QPushButton(L("Remove this area"))
        remove.clicked.connect(self._remove)
        layout.addWidget(remove)
        self._summary = QLabel("")
        layout.addWidget(self._summary)
        layout.addWidget(hint_label(L("Drag on the picture to hide an area. Each area is hidden for the time shown on the "
                                      "strip; click an area to change when. The picture shows the result.")))
        note = _note_for_many(self)
        if note:
            layout.addWidget(note)
        layout.addStretch(1)

        left = QVBoxLayout()
        left.addWidget(self._canvas, 1)
        left.addWidget(self._pane)
        outer = QHBoxLayout()
        outer.setSpacing(18)
        outer.addLayout(left, 1)
        outer.addWidget(side, alignment=Qt.AlignmentFlag.AlignTop)
        self.set_body(layout=outer)
        self.set_action_enabled(False)

    @property
    def is_settled(self) -> bool:
        return super().is_settled and self._drawn

    def _loaded(self, result) -> None:  # noqa: ANN001
        self._frame_size = (result.info.width or 1, result.info.height or 1)
        self._request_frame()

    # Regions and their time ranges are kept in step: region i belongs to range i.

    def _add_region(self, rect: UnitRect) -> None:
        timeline = self._pane.timeline
        self._canvas.regions.append(rect)
        start = timeline.position
        timeline.add_range(start, min(start + 3.0, timeline.duration) if start + 0.2 < timeline.duration else timeline.duration)

    def _select(self, index: int) -> None:
        self._pane.timeline.set_current(index)

    def _remove(self) -> None:
        index = self._pane.timeline.current
        if 0 <= index < len(self._canvas.regions):
            del self._canvas.regions[index]
            self._pane.timeline.remove_current_range()

    def _ranges_changed(self) -> None:
        self._refresh_fields()
        self._request_frame()

    def _current_changed(self, index: int) -> None:
        self._canvas.current = index
        self._canvas.update()
        self._refresh_fields()

    def _refresh_fields(self) -> None:
        timeline = self._pane.timeline
        if 0 <= timeline.current < len(timeline.ranges):
            start, end = timeline.ranges[timeline.current]
            self._from.setText(cut.timecode(start))
            self._to.setText(cut.timecode(end))
        else:
            self._from.clear()
            self._to.clear()
        self._summary.setText(count(len(timeline.ranges), "area"))
        self.set_action_enabled(bool(timeline.ranges) and len(timeline.ranges) == len(self._canvas.regions))

    def _typed(self) -> None:
        start, end = cut.parse_timecode(self._from.text()), cut.parse_timecode(self._to.text())
        if start is not None and end is not None and abs(end - start) >= 0.05:
            self._pane.timeline.set_current_range(start, end)
        self._refresh_fields()

    def _style_changed(self, style: RedactionStyle) -> None:
        self._style = style
        solid = style is RedactionStyle.SOLID
        self._fill.setVisible(solid)
        self._fill_label.setVisible(solid)
        self._request_frame()

    def _regions(self) -> list[redact_video.Region]:
        timeline = self._pane.timeline
        return [redact_video.Region(rect, *timeline.ranges[i]) for i, rect in enumerate(self._canvas.regions)
                if i < len(timeline.ranges)]

    def _request_frame(self) -> None:
        path, at = self.first, self._pane.timeline.position
        regions, style, color, size = self._regions(), self._style, self._color, self._frame_size
        if regions and size[0] > 1:
            self._frame.request(lambda cancelled: redact_video.preview_frame(path, regions, style, color, size, at))
        else:
            self._frame.request(lambda cancelled: cut.frame(path, at, _FRAME_HEIGHT))

    def _frame_ready(self, image) -> None:  # noqa: ANN001
        self._canvas.set_image(qtutil.pil_to_qimage(image))
        self._drawn = True

    def run(self) -> None:
        regions, style, color = self._regions(), self._style, self._color
        self.jobs.run_each(L("Hiding"), L("Hidden"), [self.first],
                           lambda p, token, progress: redact_video.redact(p, regions, style, color, progress, token))
        self.close()


@registry.register("tool.cropVideo")
def create_crop_video(files, context):  # noqa: ANN001, ANN201
    return CropVideoTool(files, context)


@registry.register("tool.redactVideo")
def create_redact_video(files, context):  # noqa: ANN001, ANN201
    return RedactVideoTool(files, context)


__all__ = ["CropVideoTool", "RedactVideoTool", "clock"]
