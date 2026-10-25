"""Annotate: arrows, shapes, text, numbered steps, pencil, highlighter, magnifier and pasted pictures, drawn on a
picture with a live preview."""

from __future__ import annotations

import copy
import os

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QGuiApplication, QImage, QKeySequence, QPainter, QPen, QShortcut
from PySide6.QtWidgets import (QFileDialog, QHBoxLayout, QInputDialog, QLabel, QPushButton, QSlider, QToolButton,
                               QVBoxLayout, QWidget)

from ...convert import images, qtutil
from ...core import file_format
from ...core.file_format import Category
from ...core.loc import L
from ...imaging import annotations as ann
from ...imaging.annotations import Annotation
from ...imaging.compose import RGBA
from .. import brand, glyphs
from ..widgets import ColorButton, LiveTask, hint_label
from . import registry
from .base import ToolWindow

_PREVIEW_SIDE = 1800
_HANDLE = 6.0


class AnnotateCanvas(QWidget):
    def __init__(self, tool: AnnotateTool) -> None:
        super().__init__()
        self.tool = tool
        self.setMinimumSize(640, 440)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.image: QImage | None = None
        self.full_size = (1, 1)
        self.annotations: list[Annotation] = []
        self.pictures: dict[str, QImage] = {}
        self.selected: int | None = None
        self._drawing: Annotation | None = None
        self._drag: tuple | None = None
        self._message = ""

    # MARK: Geometry

    def image_rect(self) -> QRectF:
        if self.image is None:
            return QRectF()
        area = QRectF(self.rect()).adjusted(12, 12, -12, -12)
        size = self.image.size().scaled(area.size().toSize(), Qt.AspectRatioMode.KeepAspectRatio)
        rect = QRectF(0, 0, size.width(), size.height())
        rect.moveCenter(area.center())
        return rect

    def display_scale(self) -> float:
        rect = self.image_rect()
        return rect.width() / max(self.full_size[0], 1)

    def to_image(self, point: QPointF) -> tuple[float, float]:
        rect = self.image_rect()
        scale = self.display_scale() or 1.0
        return ((point.x() - rect.x()) / scale, (point.y() - rect.y()) / scale)

    def selected_annotation(self) -> Annotation | None:
        return next((a for a in self.annotations if a.id == self.selected), None)

    # MARK: Drawing

    def paintEvent(self, _event) -> None:  # noqa: ANN001, N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(128, 128, 128, 36))
        painter.drawRoundedRect(self.rect(), 10, 10)
        if self.image is None:
            painter.setPen(brand.secondary_text_color())
            painter.drawText(self.rect(), int(Qt.AlignmentFlag.AlignCenter), self._message)
            return
        rect = self.image_rect()
        painter.drawImage(rect, self.image)
        painter.save()
        painter.setClipRect(rect)
        painter.translate(rect.topLeft())
        scale = self.display_scale()
        painter.scale(scale, scale)
        preview_scale = self.image.width() / max(self.full_size[0], 1)
        items = list(self.annotations) + ([self._drawing] if self._drawing is not None else [])
        for annotation in items:
            painter.save()
            ann.draw_annotation(painter, annotation, self.image, preview_scale, self.pictures)
            painter.restore()
        painter.restore()
        selected = self.selected_annotation()
        if selected is not None:
            self._draw_selection(painter, selected, rect, scale)

    def _draw_selection(self, painter: QPainter, a: Annotation, rect: QRectF, scale: float) -> None:
        x, y, w, h = ann.bounds(a)
        box = QRectF(rect.x() + x * scale, rect.y() + y * scale, w * scale, h * scale).adjusted(-4, -4, 4, 4)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(QPen(QColor(10, 132, 255), 1.2, Qt.PenStyle.DashLine))
        painter.drawRect(box)
        painter.setPen(QPen(QColor("white"), 1.5))
        painter.setBrush(QColor(10, 132, 255))
        for _handle, point in ann.handles(a):
            painter.drawEllipse(QPointF(rect.x() + point[0] * scale, rect.y() + point[1] * scale), _HANDLE, _HANDLE)

    # MARK: Mouse

    def _handle_at(self, point: QPointF) -> object | None:
        selected = self.selected_annotation()
        if selected is None:
            return None
        rect, scale = self.image_rect(), self.display_scale()
        for handle, position in ann.handles(selected):
            target = QPointF(rect.x() + position[0] * scale, rect.y() + position[1] * scale)
            if abs(point.x() - target.x()) <= _HANDLE + 4 and abs(point.y() - target.y()) <= _HANDLE + 4:
                return handle
        return None

    def mousePressEvent(self, event) -> None:  # noqa: ANN001, N802
        if self.image is None or event.button() != Qt.MouseButton.LeftButton:
            return
        self.setFocus()
        point = event.position()
        x, y = self.to_image(point)
        tool = self.tool.current_tool
        if tool == "select" or self._handle_at(point) is not None:
            handle = self._handle_at(point)
            if handle is not None:
                self.tool.push_undo()
                self._drag = ("handle", handle, copy.deepcopy(self.selected_annotation()))
                return
            hit = ann.hit_test(self.annotations, (x, y), 6 / max(self.display_scale(), 0.01))
            self.selected = hit
            if hit is not None:
                self.tool.push_undo()
                self._drag = ("move", (x, y), copy.deepcopy(self.selected_annotation()))
                self.tool.selection_changed(self.selected_annotation())
            else:
                self.tool.selection_changed(None)
            self.update()
            return
        color, width, font = RGBA.from_qcolor(self.tool.color), self.tool.line_width, self.tool.font_size
        if tool == "text":
            self._place_text((x, y))
            return
        if tool == "number":
            self.tool.push_undo()
            number = max((a.number for a in self.annotations if a.kind == "number"), default=0) + 1
            self.annotations.append(Annotation("number", color, width, font, start=(x, y), number=number))
            self.selected = self.annotations[-1].id
            self.update()
            return
        if tool == "image":
            self._place_picture((x, y))
            return
        start = (x, y)
        if tool == "arrow":
            self._drawing = Annotation("arrow", color, width, font, start=start, end=start)
        elif tool in ("rectangle", "ellipse"):
            self._drawing = Annotation(tool, color, width, font, rect=(x, y, 0, 0))
        elif tool in ("pen", "highlight"):
            self._drawing = Annotation(tool, color, width, font, points=[start])
        elif tool == "magnifier":
            self._drawing = Annotation("magnifier", color, width, font, start=start, radius=8)
        self._drag = ("draw", start, None)

    def mouseMoveEvent(self, event) -> None:  # noqa: ANN001, N802
        if self.image is None:
            return
        x, y = self.to_image(event.position())
        if self._drag is None:
            handle = self._handle_at(event.position())
            self.setCursor(Qt.CursorShape.CrossCursor if handle is not None or self.tool.current_tool != "select"
                           else Qt.CursorShape.ArrowCursor)
            return
        kind = self._drag[0]
        if kind == "move":
            _, (sx, sy), original = self._drag
            moved = ann.translated(original, x - sx, y - sy)
            self._replace(moved)
        elif kind == "handle":
            _, handle, original = self._drag
            aspect = None
            if original.kind == "image" and original.image_path in self.pictures:
                picture = self.pictures[original.image_path]
                aspect = picture.width() / max(picture.height(), 1)
            self._replace(ann.moving(original, handle, (x, y), aspect))
        elif kind == "draw" and self._drawing is not None:
            a = self._drawing
            sx, sy = self._drag[1]
            if a.kind == "arrow":
                a.end = (x, y)
            elif a.kind in ("rectangle", "ellipse"):
                a.rect = (sx, sy, x - sx, y - sy)
            elif a.kind in ("pen", "highlight"):
                a.points.append((x, y))
            elif a.kind == "magnifier":
                a.radius = max(8.0, ((x - sx) ** 2 + (y - sy) ** 2) ** 0.5)
        self.update()

    def mouseReleaseEvent(self, _event) -> None:  # noqa: ANN001, N802
        if self._drag is not None and self._drag[0] == "draw" and self._drawing is not None:
            a = self._drawing
            bx, by, bw, bh = ann.bounds(a)
            if a.kind in ("pen", "highlight") or max(bw, bh) > 3 or a.kind == "magnifier":
                self.tool.push_undo()
                self.annotations.append(a)
                self.selected = a.id
            self._drawing = None
            self.tool.selection_changed(self.selected_annotation())
        self._drag = None
        self.update()

    def mouseDoubleClickEvent(self, event) -> None:  # noqa: ANN001, N802
        x, y = self.to_image(event.position())
        hit = ann.hit_test(self.annotations, (x, y), 6 / max(self.display_scale(), 0.01))
        target = next((a for a in self.annotations if a.id == hit), None)
        if target is not None and target.kind == "text":
            text, ok = QInputDialog.getText(self, L("Text"), L("Text"), text=target.text)
            if ok and text:
                self.tool.push_undo()
                target.text = text
                self.update()

    def keyPressEvent(self, event) -> None:  # noqa: ANN001, N802
        if event.key() in (Qt.Key.Key_Delete, Qt.Key.Key_Backspace):
            self.tool.delete_selected()
        else:
            super().keyPressEvent(event)

    # MARK: Helpers

    def _replace(self, updated: Annotation) -> None:
        for index, a in enumerate(self.annotations):
            if a.id == updated.id:
                self.annotations[index] = updated
                return

    def _place_text(self, position: tuple[float, float]) -> None:
        text, ok = QInputDialog.getText(self, L("Text"), L("Text"))
        if ok and text:
            self.tool.push_undo()
            self.annotations.append(Annotation("text", RGBA.from_qcolor(self.tool.color), self.tool.line_width, self.tool.font_size,
                                               start=position, text=text))
            self.selected = self.annotations[-1].id
            self.tool.selection_changed(self.selected_annotation())
            self.update()

    def _place_picture(self, position: tuple[float, float]) -> None:
        key = self.tool.pending_picture
        if key is None:
            path, _ = QFileDialog.getOpenFileName(self, L("Picture"))
            if not path:
                return
            self.tool.load_picture(path)
            key = path
        picture = self.pictures.get(key)
        if picture is None:
            return
        width = self.full_size[0] * 0.3
        height = width * picture.height() / max(picture.width(), 1)
        self.tool.push_undo()
        self.annotations.append(Annotation("image", rect=(position[0], position[1], width, height), image_path=key))
        self.selected = self.annotations[-1].id
        self.tool.selection_changed(self.selected_annotation())
        self.update()


class AnnotateTool(ToolWindow):
    def __init__(self, files: list[str], context) -> None:  # noqa: ANN001
        self.images = [f for f in files if (d := file_format.detect(f)) is not None and d.category is Category.IMAGE]
        super().__init__(L("Annotate"), files, L("Save"), context)
        self.current_tool = "arrow"
        self.color = QColor(255, 59, 48)
        self.line_width = 6.0
        self.font_size = 40.0
        self.pending_picture: str | None = None
        self._undo: list[list[Annotation]] = []
        self._settled = False
        self._picture_arrays: dict[str, object] = {}

        self.canvas = AnnotateCanvas(self)
        layout = QVBoxLayout()
        layout.setSpacing(10)
        layout.addLayout(self._toolbar())
        layout.addWidget(self.canvas, 1)
        hint = L("Ctrl+V pastes a picture. Delete removes the selected mark, Ctrl+Z undoes.")
        layout.addWidget(hint_label(hint))
        if len(self.images) > 1:
            layout.addWidget(hint_label(L("Only the first image is annotated.")))
        self.set_body(layout=layout)
        self.resize(900, 700)
        QShortcut(QKeySequence("Ctrl+Z"), self, self.undo)
        QShortcut(QKeySequence("Ctrl+V"), self, self.paste)
        QShortcut(QKeySequence("Delete"), self, self.delete_selected)

        self._loader = LiveTask(0)
        self._loader.finished.connect(self._loaded)
        self._loader.failed.connect(lambda m: self.canvas.__setattr__("_message", m))
        if self.images:
            first = self.images[0]
            self._loader.request(lambda c: self._load(first), immediate=True)
            self.set_action_enabled(True)
        else:
            self.set_action_enabled(False)

    @staticmethod
    def _load(path: str):  # noqa: ANN205
        from .crop_tool import _upright_size

        image, _ = images.load(path, _PREVIEW_SIDE)
        return image, _upright_size(path)

    def _loaded(self, result) -> None:  # noqa: ANN001
        image, size = result
        self.canvas.image = qtutil.pil_to_qimage(image)
        self.canvas.full_size = size
        self.canvas.update()
        self._settled = True

    @property
    def is_settled(self) -> bool:
        return self._settled or not self.images

    # MARK: Toolbar

    def _toolbar(self) -> QHBoxLayout:
        row = QHBoxLayout()
        self._tool_buttons: dict[str, QToolButton] = {}
        for tool in ann.TOOLS:
            button = QToolButton()
            button.setCheckable(True)
            button.setAutoExclusive(True)
            button.setIcon(glyphs.icon(ann.tool_glyph(tool), 20))
            button.setToolTip(ann.tool_title(tool))
            button.setChecked(tool == self.current_tool)
            button.clicked.connect(lambda _c=False, t=tool: self._choose_tool(t))
            self._tool_buttons[tool] = button
            row.addWidget(button)
        row.addSpacing(12)
        self._color_button = ColorButton(self.color)
        self._color_button.changed.connect(self._color_changed)
        row.addWidget(self._color_button)
        self._width_slider = self._slider(1, 24, self.line_width, self._width_changed, L("Line"))
        self._font_slider = self._slider(12, 160, self.font_size, self._font_changed, L("Text size"))
        for label, slider in ((L("Line"), self._width_slider), (L("Text size"), self._font_slider)):
            row.addWidget(QLabel(label))
            row.addWidget(slider)
        row.addStretch(1)
        undo = QPushButton(L("Undo"))
        undo.clicked.connect(self.undo)
        delete = QPushButton(L("Delete"))
        delete.clicked.connect(self.delete_selected)
        row.addWidget(undo)
        row.addWidget(delete)
        return row

    def _slider(self, low: int, high: int, value: float, handler, tip: str) -> QSlider:  # noqa: ANN001
        slider = QSlider(Qt.Orientation.Horizontal)
        slider.setRange(low, high)
        slider.setValue(int(value))
        slider.setFixedWidth(90)
        slider.setToolTip(tip)
        slider.valueChanged.connect(handler)
        return slider

    def _choose_tool(self, tool: str) -> None:
        self.current_tool = tool
        if tool != "select":
            self.canvas.selected = None
            self.canvas.update()

    def _color_changed(self, color: QColor) -> None:
        self.color = color
        selected = self.canvas.selected_annotation()
        if selected is not None:
            self.push_undo()
            selected.color = RGBA.from_qcolor(color)
            self.canvas.update()

    def _width_changed(self, value: int) -> None:
        self.line_width = float(value)
        selected = self.canvas.selected_annotation()
        if selected is not None:
            selected.line_width = float(value)
            self.canvas.update()

    def _font_changed(self, value: int) -> None:
        self.font_size = float(value)
        selected = self.canvas.selected_annotation()
        if selected is not None:
            selected.font_size = float(value)
            self.canvas.update()

    def selection_changed(self, annotation: Annotation | None) -> None:
        if annotation is None:
            return
        for slider, value in ((self._width_slider, annotation.line_width), (self._font_slider, annotation.font_size)):
            blocked = slider.blockSignals(True)
            slider.setValue(int(value))
            slider.blockSignals(blocked)
        self._color_button.set_color(annotation.color.to_qcolor())
        self.color = annotation.color.to_qcolor()

    # MARK: Editing

    def push_undo(self) -> None:
        self._undo.append(copy.deepcopy(self.canvas.annotations))
        del self._undo[:-60]

    def undo(self) -> None:
        if self._undo:
            self.canvas.annotations = self._undo.pop()
            self.canvas.selected = None
            self.canvas.update()

    def delete_selected(self) -> None:
        if self.canvas.selected is None:
            return
        self.push_undo()
        self.canvas.annotations = [a for a in self.canvas.annotations if a.id != self.canvas.selected]
        self.canvas.selected = None
        self.canvas.update()

    def load_picture(self, path: str) -> None:
        image = QImage(path)
        if image.isNull():
            pil, _ = images.load(path)
            image = qtutil.pil_to_qimage(pil)
        self.canvas.pictures[path] = image
        self.pending_picture = path

    def paste(self) -> None:
        image = QGuiApplication.clipboard().image()
        if image.isNull():
            return
        key = f"clipboard:{len(self.canvas.pictures) + 1}"
        self.canvas.pictures[key] = image
        self.pending_picture = key
        self._tool_buttons["image"].setChecked(True)
        self._choose_tool("image")
        rect = self.canvas.image_rect()
        self.canvas._place_picture((self.canvas.full_size[0] * 0.1, self.canvas.full_size[1] * 0.1))  # noqa: SLF001
        self.pending_picture = None
        self.canvas.update()
        _ = rect

    # MARK: Work

    def run(self) -> None:
        if not self.images:
            return
        if not self.canvas.annotations:
            self.context.notify(L("Annotate"), L("Nothing was changed."))
            return
        first = self.images[0]
        annotations = copy.deepcopy(self.canvas.annotations)
        pictures = {}
        for key, qimage in self.canvas.pictures.items():
            from .editor_tool import qtutil_to_pil  # a QImage as PIL

            pictures[key] = qtutil_to_pil(qimage)
        options = self.settings.conversion_options
        self.jobs.run_each(L("Annotating"), L("Annotated"), [first],
                           lambda path, _t, _p: ann.annotate_file(path, annotations, pictures, options))
        self.close()


@registry.register("tool.annotate")
def create(files: list[str], context) -> AnnotateTool:  # noqa: ANN001
    return AnnotateTool(files, context)


__all__ = ["AnnotateTool", "os"]
