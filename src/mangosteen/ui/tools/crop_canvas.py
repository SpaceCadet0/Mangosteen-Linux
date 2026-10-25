"""The crop canvas: the picture with a frame to drag, handles on its edges, and cut lines that divide the result into
parts."""

from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QImage, QPainter, QPen
from PySide6.QtWidgets import QWidget

from ...imaging import geometry as g
from ...imaging.geometry import Edges, UnitRect
from .. import brand

_HANDLE = 6.0
_GRAB = 11.0
_CUT_GRAB = 6.0


class CropCanvas(QWidget):
    rect_changed = Signal(object)  # UnitRect
    cuts_changed = Signal()

    def __init__(self) -> None:
        super().__init__()
        self.setMinimumSize(620, 420)
        self.setMouseTracking(True)
        self._image: QImage | None = None
        self._rect = g.FULL
        self._aspect: float | None = None  # normalised width / height
        self.column_cuts: list[float] = []
        self.row_cuts: list[float] = []
        self._message = ""
        self._drag: tuple | None = None

    # MARK: State

    def set_image(self, image: QImage | None, message: str = "") -> None:
        self._image = image
        self._message = message
        self.update()

    def set_rect(self, rect: UnitRect) -> None:
        self._rect = rect
        self.update()

    @property
    def unit_rect(self) -> UnitRect:
        """The crop frame, normalised to the image."""
        return self._rect

    def set_aspect(self, aspect: float | None) -> None:
        self._aspect = aspect

    def set_cuts(self, columns: list[float], rows: list[float]) -> None:
        self.column_cuts, self.row_cuts = list(columns), list(rows)
        self.update()

    # MARK: Geometry

    def _image_rect(self) -> QRectF:
        if self._image is None or self._image.isNull():
            return QRectF()
        area = QRectF(self.rect()).adjusted(16, 16, -16, -16)
        size = self._image.size().scaled(area.size().toSize(), Qt.AspectRatioMode.KeepAspectRatio)
        target = QRectF(0, 0, size.width(), size.height())
        target.moveCenter(area.center())
        return target

    def _frame_rect(self) -> QRectF:
        image = self._image_rect()
        r = self._rect
        return QRectF(image.x() + r.x * image.width(), image.y() + r.y * image.height(), r.width * image.width(),
                      r.height * image.height())

    def _handles(self) -> list[tuple[Edges, QPointF]]:
        f = self._frame_rect()
        cx, cy = f.center().x(), f.center().y()
        return [(Edges.TOP_LEFT, f.topLeft()), (Edges.TOP, QPointF(cx, f.top())), (Edges.TOP_RIGHT, f.topRight()),
                (Edges.RIGHT, QPointF(f.right(), cy)), (Edges.BOTTOM_RIGHT, f.bottomRight()),
                (Edges.BOTTOM, QPointF(cx, f.bottom())), (Edges.BOTTOM_LEFT, f.bottomLeft()),
                (Edges.LEFT, QPointF(f.left(), cy))]

    # MARK: Drawing

    def paintEvent(self, _event) -> None:  # noqa: ANN001, N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(128, 128, 128, 36))
        painter.drawRoundedRect(self.rect(), 10, 10)
        if self._image is None or self._image.isNull():
            painter.setPen(brand.secondary_text_color())
            painter.drawText(self.rect().adjusted(20, 20, -20, -20), int(Qt.AlignmentFlag.AlignCenter | Qt.TextFlag.TextWordWrap),
                             self._message)
            return
        image_rect = self._image_rect()
        painter.drawImage(image_rect, self._image)
        frame = self._frame_rect()
        # Dim everything outside the frame.
        dim = QColor(0, 0, 0, 120)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(dim)
        for part in (QRectF(image_rect.left(), image_rect.top(), image_rect.width(), frame.top() - image_rect.top()),
                     QRectF(image_rect.left(), frame.bottom(), image_rect.width(), image_rect.bottom() - frame.bottom()),
                     QRectF(image_rect.left(), frame.top(), frame.left() - image_rect.left(), frame.height()),
                     QRectF(frame.right(), frame.top(), image_rect.right() - frame.right(), frame.height())):
            painter.drawRect(part)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        # Rule-of-thirds guides.
        painter.setPen(QPen(QColor(255, 255, 255, 70), 1))
        for i in (1, 2):
            painter.drawLine(QPointF(frame.left() + frame.width() * i / 3, frame.top()),
                             QPointF(frame.left() + frame.width() * i / 3, frame.bottom()))
            painter.drawLine(QPointF(frame.left(), frame.top() + frame.height() * i / 3),
                             QPointF(frame.right(), frame.top() + frame.height() * i / 3))
        painter.setPen(QPen(QColor("white"), 1.5))
        painter.drawRect(frame)
        # Cut lines.
        painter.setPen(QPen(QColor(255, 214, 10), 2, Qt.PenStyle.DashLine))
        for cut in self.column_cuts:
            x = frame.left() + cut * frame.width()
            painter.drawLine(QPointF(x, frame.top()), QPointF(x, frame.bottom()))
        for cut in self.row_cuts:
            y = frame.top() + cut * frame.height()
            painter.drawLine(QPointF(frame.left(), y), QPointF(frame.right(), y))
        # Handles.
        painter.setPen(QPen(QColor(0, 0, 0, 120), 1))
        painter.setBrush(QColor("white"))
        for _edges, point in self._handles():
            painter.drawRoundedRect(QRectF(point.x() - _HANDLE, point.y() - _HANDLE, _HANDLE * 2, _HANDLE * 2), 3, 3)

    # MARK: Mouse

    def _hit(self, point: QPointF) -> tuple | None:
        frame = self._frame_rect()
        for index, cut in enumerate(self.column_cuts):
            x = frame.left() + cut * frame.width()
            if abs(point.x() - x) <= _CUT_GRAB and frame.top() - _CUT_GRAB <= point.y() <= frame.bottom() + _CUT_GRAB:
                return ("column", index)
        for index, cut in enumerate(self.row_cuts):
            y = frame.top() + cut * frame.height()
            if abs(point.y() - y) <= _CUT_GRAB and frame.left() - _CUT_GRAB <= point.x() <= frame.right() + _CUT_GRAB:
                return ("row", index)
        for edges, handle in self._handles():
            if abs(point.x() - handle.x()) <= _GRAB and abs(point.y() - handle.y()) <= _GRAB:
                return ("edges", edges)
        if frame.contains(point):
            return ("move", None)
        return None

    def mouseMoveEvent(self, event) -> None:  # noqa: ANN001, N802
        point = event.position()
        if self._drag is None:
            hit = self._hit(point)
            cursor = Qt.CursorShape.ArrowCursor
            if hit is not None:
                kind, value = hit
                if kind == "move":
                    cursor = Qt.CursorShape.SizeAllCursor
                elif kind == "column":
                    cursor = Qt.CursorShape.SplitHCursor
                elif kind == "row":
                    cursor = Qt.CursorShape.SplitVCursor
                elif value in (Edges.TOP_LEFT, Edges.BOTTOM_RIGHT):
                    cursor = Qt.CursorShape.SizeFDiagCursor
                elif value in (Edges.TOP_RIGHT, Edges.BOTTOM_LEFT):
                    cursor = Qt.CursorShape.SizeBDiagCursor
                elif value in (Edges.LEFT, Edges.RIGHT):
                    cursor = Qt.CursorShape.SizeHorCursor
                else:
                    cursor = Qt.CursorShape.SizeVerCursor
            self.setCursor(cursor)
            return
        kind, value, start_point, start_rect, start_cuts = self._drag
        image = self._image_rect()
        if image.width() <= 0 or image.height() <= 0:
            return
        dx = (point.x() - start_point.x()) / image.width()
        dy = (point.y() - start_point.y()) / image.height()
        if kind == "move":
            self._rect = g.move(start_rect, dx, dy)
            self.rect_changed.emit(self._rect)
        elif kind == "edges":
            resized = g.resize(start_rect, value, dx, dy, self._aspect)
            if resized is not None:
                self._rect = resized
                self.rect_changed.emit(self._rect)
        else:
            frame = self._frame_rect()
            if kind == "column":
                cuts = list(start_cuts)
                position = (point.x() - frame.left()) / max(frame.width(), 1)
                cuts[value[0]] = g.clamp_cut(cuts, value[0], position)
                self.column_cuts = cuts
            else:
                cuts = list(start_cuts)
                position = (point.y() - frame.top()) / max(frame.height(), 1)
                cuts[value[0]] = g.clamp_cut(cuts, value[0], position)
                self.row_cuts = cuts
            self.cuts_changed.emit()
        self.update()

    def mousePressEvent(self, event) -> None:  # noqa: ANN001, N802
        if event.button() != Qt.MouseButton.LeftButton:
            return
        hit = self._hit(event.position())
        if hit is None:
            return
        kind, value = hit
        if kind == "column":
            self._drag = (kind, (value,), event.position(), self._rect, list(self.column_cuts))
        elif kind == "row":
            self._drag = (kind, (value,), event.position(), self._rect, list(self.row_cuts))
        else:
            self._drag = (kind, value, event.position(), self._rect, None)

    def mouseReleaseEvent(self, _event) -> None:  # noqa: ANN001, N802
        self._drag = None
