"""The wheel: a ring of segments under the pointer. Each segment is a drop target for files being dragged, and a
button when the wheel is opened from the tray or a file manager. Segments run clockwise from 12 o'clock."""

from __future__ import annotations

import math

from PySide6.QtCore import QEvent, QPointF, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import (QColor, QFont, QFontMetricsF, QGuiApplication, QPainter, QPainterPath, QPainterPathStroker,
                           QPixmap)
from PySide6.QtWidgets import QWidget

from ..core.loc import L
from ..core.wheel_catalog import WheelItem, WheelKind, file_count, wheel_title
from . import brand, glyphs

INNER_RADIUS = 64.0
OUTER_RADIUS = 160.0
# Extra tolerance outside the ring that still counts as the segment under the cursor.
HIT_SLOP = 26.0
DIAMETER = int((OUTER_RADIUS + HIT_SLOP) * 2)
_SHADOW = 18


class WheelWidget(QWidget):
    selected = Signal(object)  # WheelItem
    hovered = Signal()
    # The files of a drag, learnt when the drag enters the wheel (the wheel was opened before they were known).
    files_entered = Signal(list)

    def __init__(self) -> None:
        super().__init__()
        self.setFixedSize(DIAMETER, DIAMETER)
        self.setAcceptDrops(True)
        self.setMouseTracking(True)
        self.items: list[WheelItem] = []
        self.kind = WheelKind.CONVERT
        self.count = 0
        self._highlighted: int | None = None
        self._opaque = False
        self.awaiting_files = False
        self._reset_caches()
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, True)

    # MARK: Setup

    def configure(self, kind: WheelKind, items: list[WheelItem], count: int, opaque: bool = False,
                  awaiting_files: bool = False) -> None:
        self.awaiting_files = awaiting_files
        self.kind = kind
        self.items = items
        self.count = count
        self._opaque = opaque
        self._reset_caches()
        self._set_highlight(None)
        self.setAccessibleName(f"{wheel_title(kind)}, {file_count(count)}")
        self.update()

    @property
    def highlighted(self) -> int | None:
        return self._highlighted

    def _reset_caches(self) -> None:
        """Everything that only changes with the items: drawn once, reused on every hover (a Raspberry Pi redraws a
        whole wheel slowly enough for the highlight to lag behind the pointer)."""
        self._paths: dict[int, QPainterPath] = {}
        self._layouts: dict[int, object] = {}
        self._backdrop: QPixmap | None = None

    def _set_highlight(self, index: int | None) -> None:
        if index == self._highlighted:
            return
        previous, self._highlighted = self._highlighted, index
        # Only the two segments that change are redrawn.
        changed = [i for i in (previous, index) if i is not None and i < len(self.items)]
        if changed and len(self.items) > 1:
            for i in changed:
                self.update(self.segment_path(i).boundingRect().toAlignedRect().adjusted(-2, -2, 2, 2))
        else:
            self.update()
        if index is not None:
            self.hovered.emit()

    def highlight_for_test(self, index: int | None) -> None:
        self._set_highlight(index)

    # MARK: Geometry

    @property
    def _center(self) -> QPointF:
        return QPointF(self.width() / 2, self.height() / 2)

    @property
    def _span(self) -> float:
        return 2 * math.pi / max(len(self.items), 1)

    def segment_index_at(self, point: QPointF) -> int | None:
        """Index of the segment under `point` (widget coordinates), if any."""
        if not self.items:
            return None
        dx, dy = point.x() - self._center.x(), point.y() - self._center.y()
        distance = math.hypot(dx, dy)
        if distance < INNER_RADIUS or distance > OUTER_RADIUS + HIT_SLOP:
            return None
        angle = math.atan2(dx, -dy)  # 0 at 12 o'clock, growing clockwise
        if angle < 0:
            angle += 2 * math.pi
        return int((angle + self._span / 2) / self._span) % len(self.items)

    def _point(self, radius: float, angle: float) -> QPointF:
        return QPointF(self._center.x() + radius * math.sin(angle), self._center.y() - radius * math.cos(angle))

    def _circle_path(self, radius: float) -> QPainterPath:
        path = QPainterPath()
        path.addEllipse(self._center, radius, radius)
        return path

    def segment_path(self, index: int) -> QPainterPath:
        path = self._paths.get(index)
        if path is None:
            path = self._paths[index] = self._make_segment_path(index)
        return path

    def _make_segment_path(self, index: int) -> QPainterPath:
        if len(self.items) == 1:
            ring = self._circle_path(OUTER_RADIUS - 4)
            ring.addPath(self._circle_path(INNER_RADIUS + 4))
            ring.setFillRule(Qt.FillRule.OddEvenFill)
            return ring
        # A ring segment with rounded corners, like a mangosteen segment: the shape is shrunk by the corner radius,
        # then grown back by a round-joined stroke of that radius.
        corner, gap = 10.0, 6.0
        outer = OUTER_RADIUS - 4 - corner
        inner = INNER_RADIUS + 4 + corner
        first = index * self._span - self._span / 2
        last = index * self._span + self._span / 2

        def inset(radius: float) -> float:
            return (gap / 2 + corner) / radius

        def qt_angle(clockwise_from_top: float) -> float:
            return 90.0 - math.degrees(clockwise_from_top)

        path = QPainterPath()
        path.moveTo(self._point(outer, first + inset(outer)))
        outer_rect = QRectF(self._center.x() - outer, self._center.y() - outer, 2 * outer, 2 * outer)
        path.arcTo(outer_rect, qt_angle(first + inset(outer)), -math.degrees(last - first - 2 * inset(outer)))
        path.lineTo(self._point(inner, last - inset(inner)))
        inner_rect = QRectF(self._center.x() - inner, self._center.y() - inner, 2 * inner, 2 * inner)
        path.arcTo(inner_rect, qt_angle(last - inset(inner)), math.degrees(last - first - 2 * inset(inner)))
        path.closeSubpath()
        stroker = QPainterPathStroker()
        stroker.setWidth(corner * 2)
        stroker.setCapStyle(Qt.PenCapStyle.RoundCap)
        stroker.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        return path.united(stroker.createStroke(path))

    # MARK: Drawing

    def paintEvent(self, event) -> None:  # noqa: ANN001
        painter = QPainter(self)
        if self._opaque:
            # Without a compositor the window is cut to a circle; what lies outside the wheel itself is filled too,
            # or it would show black.
            painter.fillRect(self.rect(), brand.window_color())
        else:
            painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Source)
            painter.fillRect(event.rect(), Qt.GlobalColor.transparent)
            painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceOver)
        painter.drawPixmap(0, 0, self._backdrop_pixmap())
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        area = QRectF(event.rect())
        for index in range(len(self.items)):
            if self.segment_path(index).boundingRect().intersects(area):
                self._draw_segment(painter, index)
        painter.end()

    def _backdrop_pixmap(self) -> QPixmap:
        """The shadow, the disc and the centre text, which do not change while the pointer moves."""
        ratio = self.devicePixelRatioF()
        if self._backdrop is not None and self._backdrop.devicePixelRatio() == ratio:
            return self._backdrop
        pixmap = QPixmap(int(self.width() * ratio), int(self.height() * ratio))
        pixmap.setDevicePixelRatio(ratio)
        pixmap.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        if not self._opaque:
            self._draw_shadow(painter)
        background = QColor(brand.window_color())
        background.setAlphaF(1.0 if self._opaque else 0.96)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(background)
        painter.drawEllipse(self._center, OUTER_RADIUS, OUTER_RADIUS)
        self._draw_center(painter)
        painter.end()
        self._backdrop = pixmap
        return pixmap

    def _draw_shadow(self, painter: QPainter) -> None:
        for step in range(_SHADOW, 0, -1):
            alpha = 0.30 * (1 - step / _SHADOW) ** 2 / _SHADOW * 2.2
            painter.setBrush(QColor(0, 0, 0, max(0, min(255, int(alpha * 255)))))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawEllipse(QPointF(self._center.x(), self._center.y() + 4), OUTER_RADIUS + step * 0.5,
                                OUTER_RADIUS + step * 0.5)

    def _draw_segment(self, painter: QPainter, index: int) -> None:
        item = self.items[index]
        highlighted = index == self._highlighted and item.available
        path = self.segment_path(index)
        fill = QColor(brand.BRAND) if highlighted else QColor(brand.text_color())
        if not highlighted:
            fill.setAlphaF(0.05)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(fill)
        painter.drawPath(path)

        tint = QColor("white") if highlighted else brand.text_color()
        if not item.available:
            tint = QColor(tint)
            tint.setAlphaF(0.35)
        layout = self._label_layout(index, item.title)
        if layout is None:
            return
        font, text_rect, icon_rect, lines = layout
        glyphs.draw(painter, item.icon, icon_rect, tint, 1.9 if len(self.items) < 10 else 2.0)
        painter.setFont(font)
        painter.setPen(tint)
        painter.drawText(text_rect, int(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop | Qt.TextFlag.TextWordWrap),
                         item.title)

    def _label_layout(self, index: int, title: str):  # noqa: ANN202
        if index not in self._layouts:
            self._layouts[index] = self._fit_label(index, title)
        return self._layouts[index]

    def _fit_label(self, index: int, title: str):  # noqa: ANN202
        """Icon and title are centred together on the segment. The title gets the largest font (11.5 → 8 pt) and the
        widest wrap (≤ 2 lines, no word broken) for which both boxes lie entirely within the segment's ring sector.
        Returns (font, text rect, icon rect, lines)."""
        middle = index * self._span
        base_radius = (INNER_RADIUS + OUTER_RADIUS) / 2
        icon_size = 14.0 if len(self.items) >= 10 else 18.0
        gap = 3.0
        chosen = None
        size = 11.5
        while size >= 8:
            font = QFont(QGuiApplication.font())
            font.setPointSizeF(size)
            font.setWeight(QFont.Weight.DemiBold)
            metrics = QFontMetricsF(font)
            longest = max((math.ceil(metrics.horizontalAdvance(word)) for word in title.split()), default=0)
            for max_width in (84, 76, 68, 60, 52, 44):
                if longest > max_width:
                    continue
                box = metrics.boundingRect(QRectF(0, 0, max_width, 200),
                                           int(Qt.AlignmentFlag.AlignHCenter | Qt.TextFlag.TextWordWrap), title)
                line_height = math.ceil(metrics.height())
                if box.height() > line_height * 2 + 1:
                    continue
                width = min(math.ceil(box.width()), max_width) + 2
                height = math.ceil(box.height())
                for shift in (0, 6, -6, 10, -10, 14):
                    radius = base_radius + shift
                    label_center = self._point(radius, middle)
                    top = label_center.y() - (icon_size + gap + height) / 2
                    icon_rect = QRectF(label_center.x() - icon_size / 2, top, icon_size, icon_size)
                    text_rect = QRectF(label_center.x() - width / 2, icon_rect.bottom() + gap, width, height)
                    if chosen is None or shift == 0:
                        chosen = (QFont(font), text_rect, icon_rect, 0)
                    if self._label_fits(text_rect, index) and self._label_fits(icon_rect, index):
                        return QFont(font), text_rect, icon_rect, 0
            size -= 0.5
        return chosen

    def _label_fits(self, rect: QRectF, index: int) -> bool:
        """Whether `rect` lies inside segment `index`'s ring sector, away from its edges and gaps."""
        middle = index * self._span
        for corner in (rect.topLeft(), rect.topRight(), rect.bottomLeft(), rect.bottomRight()):
            dx, dy = corner.x() - self._center.x(), corner.y() - self._center.y()
            radius = math.hypot(dx, dy)
            if radius < INNER_RADIUS + 6 or radius > OUTER_RADIUS - 6:
                return False
            angle = math.atan2(dx, -dy)
            offset = abs((angle - middle + math.pi) % (2 * math.pi) - math.pi)
            if offset > self._span / 2 - 4 / radius:
                return False
        return True

    def _draw_center(self, painter: QPainter) -> None:
        if self.awaiting_files:
            primary, secondary = wheel_title(self.kind), "…"
        elif not self.items:
            primary, secondary = L("No options"), L("for these files")
        else:
            primary, secondary = wheel_title(self.kind), file_count(self.count)
        font = QFont(QGuiApplication.font())
        font.setPointSizeF(12)
        font.setBold(True)
        painter.setFont(font)
        painter.setPen(brand.text_color())
        painter.drawText(QRectF(self._center.x() - 60, self._center.y() - 22, 120, 22),
                         int(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignBottom), primary)
        small = QFont(QGuiApplication.font())
        small.setPointSizeF(11)
        painter.setFont(small)
        painter.setPen(brand.secondary_text_color())
        painter.drawText(QRectF(self._center.x() - 60, self._center.y() + 2, 120, 22),
                         int(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop), secondary)

    # MARK: Drag destination

    def dragEnterEvent(self, event) -> None:  # noqa: ANN001, N802
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
            if self.awaiting_files:
                self.awaiting_files = False
                paths = [u.toLocalFile() for u in event.mimeData().urls() if u.isLocalFile()]
                self.files_entered.emit(paths)
            self._set_highlight(self.segment_index_at(event.position()))
        else:
            event.ignore()
            if self.awaiting_files:
                self.awaiting_files = False
                self.files_entered.emit([])

    def dragMoveEvent(self, event) -> None:  # noqa: ANN001, N802
        index = self.segment_index_at(event.position())
        self._set_highlight(index)
        if index is None:
            event.ignore()
        else:
            event.setDropAction(Qt.DropAction.CopyAction)
            event.accept()

    def dragLeaveEvent(self, _event) -> None:  # noqa: ANN001, N802
        self._set_highlight(None)

    def dropEvent(self, event) -> None:  # noqa: ANN001, N802
        index = self.segment_index_at(event.position())
        if index is None:
            event.ignore()
            return
        event.setDropAction(Qt.DropAction.CopyAction)
        event.accept()
        self.selected.emit(self.items[index])

    # MARK: Mouse (wheel opened from the tray or a file manager)

    def changeEvent(self, event) -> None:  # noqa: ANN001, N802
        if event.type() in (QEvent.Type.PaletteChange, QEvent.Type.FontChange, QEvent.Type.StyleChange):
            self._reset_caches()
        super().changeEvent(event)

    def mouseMoveEvent(self, event) -> None:  # noqa: ANN001, N802
        self._set_highlight(self.segment_index_at(event.position()))

    def leaveEvent(self, _event) -> None:  # noqa: ANN001, N802
        self._set_highlight(None)

    def mouseReleaseEvent(self, event) -> None:  # noqa: ANN001, N802
        if event.button() != Qt.MouseButton.LeftButton:
            return
        index = self.segment_index_at(event.position())
        if index is not None:
            self.selected.emit(self.items[index])

    def keyPressEvent(self, event) -> None:  # noqa: ANN001, N802
        if event.key() == Qt.Key.Key_Escape:
            self.window().hide()
        else:
            super().keyPressEvent(event)


class WheelController:
    """Shows the wheel centred on the pointer: as a non-activating overlay while a file is being dragged, and as a
    popup (closing when you click elsewhere) when it is opened from the tray or a file manager."""

    def __init__(self, on_item, items_for) -> None:  # noqa: ANN001 - callables
        self._on_item = on_item  # (WheelItem, list[str])
        self._items_for = items_for  # (WheelKind, list[str]) -> list[WheelItem]
        self.widget = WheelWidget()
        self.widget.selected.connect(self._selected)
        self.widget.hovered.connect(self._hover)
        self.widget.files_entered.connect(self._files_entered)
        self._paths: list[str] = []
        self._kind = WheelKind.CONVERT
        self._hide_timer = QTimer()
        self._hide_timer.setSingleShot(True)
        self._hide_timer.timeout.connect(self.hide)
        self.on_hover = lambda: None
        self.on_shown_without_files = lambda: None
        self.drag_mode = False

    @property
    def is_visible(self) -> bool:
        return self.widget.isVisible()

    @property
    def kind(self) -> WheelKind:
        return self._kind

    @property
    def paths(self) -> list[str]:
        return list(self._paths)

    def _hover(self) -> None:
        self.on_hover()

    def _selected(self, item: WheelItem) -> None:
        paths = list(self._paths)
        self.hide()
        # Leave the drop callback before running anything that may show UI.
        QTimer.singleShot(0, lambda: self._on_item(item, paths))

    def _files_entered(self, paths: list[str]) -> None:
        if not paths:
            self.hide()  # the drag carries no files (selected text, say)
            return
        self._paths = paths
        self.switch(self._kind)

    def show(self, kind: WheelKind, paths: list[str] | None, point=None, drag_mode: bool = True) -> None:  # noqa: ANN001
        """`paths` None means a drag is going on whose files are not known yet; the wheel then learns them when
        the drag enters it."""
        from ..platform import x11

        self._hide_timer.stop()
        self._paths = list(paths or [])
        self._kind = kind
        self.drag_mode = drag_mode
        widget = self.widget
        opaque = not x11.has_compositor()
        widget.hide()
        flags = Qt.WindowType.FramelessWindowHint
        if drag_mode:
            flags |= (Qt.WindowType.Tool | Qt.WindowType.WindowStaysOnTopHint | Qt.WindowType.WindowDoesNotAcceptFocus
                      | Qt.WindowType.X11BypassWindowManagerHint)
        else:
            flags |= Qt.WindowType.Popup
        widget.setWindowFlags(flags)
        widget.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, drag_mode)
        widget.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, not opaque)
        awaiting = paths is None
        widget.configure(kind, [] if awaiting else self._items_for(kind, self._paths), len(self._paths), opaque, awaiting)
        if opaque:
            from PySide6.QtGui import QRegion

            # Cut to the wheel itself: the margin around it (where a drop still counts) would otherwise show as a ring.
            edge = int(DIAMETER / 2 - OUTER_RADIUS) - 1
            widget.setMask(QRegion(edge, edge, DIAMETER - 2 * edge, DIAMETER - 2 * edge, QRegion.RegionType.Ellipse))
        else:
            widget.clearMask()

        if point is None:
            point = _cursor() if _cursor_known() else QGuiApplication.primaryScreen().availableGeometry().center()
        size = DIAMETER
        x, y = point.x() - size / 2, point.y() - size / 2
        screen = QGuiApplication.screenAt(point) or QGuiApplication.primaryScreen()
        area = screen.availableGeometry()
        x = min(max(x, area.left()), area.right() - size + 1)
        y = min(max(y, area.top()), area.bottom() - size + 1)
        widget.move(int(x), int(y))
        widget.show()
        widget.raise_()
        if awaiting:
            self.on_shown_without_files()

    def switch(self, kind: WheelKind) -> None:
        """Another wheel for the same files (a different key tapped while this one is open)."""
        if not self.widget.isVisible():
            return
        self._kind = kind
        awaiting = self.widget.awaiting_files and not self._paths
        self.widget.configure(kind, [] if awaiting else self._items_for(kind, self._paths), len(self._paths),
                              self.widget._opaque, awaiting)  # noqa: SLF001

    def drag_ended(self) -> None:
        """The drag finished; give a drop on the wheel time to arrive, then close."""
        if self.drag_mode and self.widget.isVisible():
            self._hide_timer.start(400)

    def hide(self) -> None:
        self._hide_timer.stop()
        self.widget.hide()


def _cursor():  # noqa: ANN202
    from PySide6.QtGui import QCursor

    return QCursor.pos()


def _cursor_known() -> bool:
    """On Wayland the pointer position outside our own windows is not known; the wheel then opens mid-screen."""
    return QGuiApplication.platformName() != "wayland"

