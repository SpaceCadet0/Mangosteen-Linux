"""Hide: covers faces, text or areas you draw on a picture with a fill, a blur or large pixels. Nothing can be
recovered from the result, and it carries no metadata."""

from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QImage, QPainter, QPen
from PySide6.QtWidgets import (QCheckBox, QFormLayout, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget)

from ...convert import images, qtutil
from ...core import capabilities, file_format
from ...core.file_format import Category
from ...core.loc import L, fmt
from ...imaging import redact
from ...imaging.compose import RGBA
from ...imaging.geometry import UnitRect
from ...imaging.redact import RedactionStyle
from ..widgets import ColorButton, LiveTask, Segmented, hint_label
from . import registry
from .base import ToolWindow

_PREVIEW_SIDE = 1400


class _Canvas(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self.setMinimumSize(560, 420)
        self.setMouseTracking(True)
        self.image: QImage | None = None
        self.regions: list[UnitRect] = []
        self.changed = lambda: None
        self._start: QPointF | None = None
        self._current: QRectF | None = None
        self._message = "…"

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
        for index in range(len(self.regions) - 1, -1, -1):  # clicking an area removes it
            r = self.regions[index]
            if r.x <= x <= r.right and r.y <= y <= r.bottom:
                del self.regions[index]
                self.changed()
                self.update()
                return
        self._start = event.position()
        self._current = QRectF(self._start, self._start)

    def mouseMoveEvent(self, event) -> None:  # noqa: ANN001, N802
        if self._start is not None:
            self._current = QRectF(self._start, event.position()).normalized()
            self.update()

    def mouseReleaseEvent(self, _event) -> None:  # noqa: ANN001, N802
        if self._start is None or self._current is None:
            return
        rect = self.image_rect()
        current = self._current.intersected(rect)
        self._start = self._current = None
        if current.width() > 6 and current.height() > 6:
            self.regions.append(UnitRect((current.x() - rect.x()) / rect.width(), (current.y() - rect.y()) / rect.height(),
                                         current.width() / rect.width(), current.height() / rect.height()))
            self.changed()
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
        painter.setPen(QPen(QColor(255, 214, 10), 2))
        for r in self.regions:
            painter.drawRect(QRectF(rect.x() + r.x * rect.width(), rect.y() + r.y * rect.height(), r.width * rect.width(),
                                    r.height * rect.height()))
        if self._current is not None:
            painter.setPen(QPen(QColor("white"), 1.5, Qt.PenStyle.DashLine))
            painter.drawRect(self._current)


class HideTool(ToolWindow):
    def __init__(self, files: list[str], context) -> None:  # noqa: ANN001
        self.images = [f for f in files if (d := file_format.detect(f)) is not None and d.category is Category.IMAGE]
        super().__init__(L("Hide faces and text"), files, L("Hide"), context)
        self._style = RedactionStyle.BLUR
        self._color = RGBA(0, 0, 0)
        self._base = None
        self._settled = False
        self._canvas = _Canvas()
        self._canvas.changed = self._render
        self._live = LiveTask(120)
        self._live.finished.connect(self._rendered)
        self._finder = LiveTask(0)
        self._finder.finished.connect(self._found)
        self._finder.failed.connect(self._find_failed)
        self._loader = LiveTask(0)
        self._loader.finished.connect(self._loaded)

        side = QWidget()
        side.setFixedWidth(280)
        form = QFormLayout(side)
        form.setContentsMargins(0, 0, 0, 0)
        self._style_control = Segmented([(L("Fill"), RedactionStyle.SOLID), (L("Blur"), RedactionStyle.BLUR),
                                         (L("Pixels"), RedactionStyle.PIXELATE)], RedactionStyle.BLUR)
        self._style_control.changed.connect(self._style_changed)
        form.addRow(self._style_control)
        self._fill = ColorButton(QColor("black"))
        self._fill.changed.connect(lambda c: (setattr(self, "_color", RGBA.from_qcolor(c)), self._render()))
        self._fill_label = QLabel(L("Colour"))
        form.addRow(self._fill_label, self._fill)
        self._fill.setVisible(False)
        self._fill_label.setVisible(False)
        self._faces = QPushButton(L("Find faces"))
        self._faces.clicked.connect(lambda: self._find("faces"))
        self._text = QPushButton(L("Find text"))
        self._text.clicked.connect(lambda: self._find("text"))
        self._text.setEnabled(capabilities.has_tesseract())
        if not capabilities.has_tesseract():
            self._text.setToolTip(L("Needs Tesseract: install the tesseract-ocr package."))
        form.addRow(self._faces)
        form.addRow(self._text)
        self._status = hint_label(L("Drag on the picture to add an area; click an area to remove it."))
        form.addRow(self._status)
        self._auto_faces = QCheckBox(L("Faces"))
        self._auto_text = QCheckBox(L("Text"))
        self._auto_text.setEnabled(capabilities.has_tesseract())
        if len(self.images) > 1:
            form.addRow(hint_label(L("The areas above belong to the first image; on the others Mangosteen finds what is "
                                     "ticked here.")))
            form.addRow(self._auto_faces)
            form.addRow(self._auto_text)

        outer = QHBoxLayout()
        outer.setSpacing(16)
        outer.addWidget(self._canvas, 1)
        outer.addWidget(side, alignment=Qt.AlignmentFlag.AlignTop)
        self.set_body(layout=outer)
        self.resize(900, 560)
        if self.images:
            first = self.images[0]
            self._loader.request(lambda c: images.load(first, _PREVIEW_SIDE)[0], immediate=True)
        else:
            self.set_action_enabled(False)

    def _style_changed(self, style: RedactionStyle) -> None:
        self._style = style
        solid = style is RedactionStyle.SOLID
        self._fill.setVisible(solid)
        self._fill_label.setVisible(solid)
        self._render()

    def _loaded(self, image) -> None:  # noqa: ANN001
        self._base = image
        self._canvas.image = qtutil.pil_to_qimage(image)
        self._canvas.update()
        self._settled = True

    def _find(self, what: str) -> None:
        if self._base is None:
            return
        base = self._base
        self._pending = what
        self._status.setText(L("Looking for faces…") if what == "faces" else L("Looking for text…"))
        self._finder.request(lambda c: redact.detect_faces(base) if what == "faces" else redact.detect_text(base),
                             immediate=True)

    def _found(self, regions) -> None:  # noqa: ANN001
        self._canvas.regions.extend(regions)
        if self._pending == "faces":
            self._status.setText(fmt("Faces found: {0}", len(regions)) if regions else L("No faces found."))
        else:
            self._status.setText(fmt("Lines of text found: {0}", len(regions)) if regions else fmt("No text was found in “{0}”.", ""))
        self._canvas.update()
        self._render()

    def _find_failed(self, message: str) -> None:
        self._status.setText(message)

    def _render(self) -> None:
        if self._base is None:
            return
        base, regions, style, color = self._base, list(self._canvas.regions), self._style, self._color
        if not regions:
            self._canvas.image = qtutil.pil_to_qimage(base)
            self._canvas.update()
            return
        self._live.request(lambda c: redact.apply(base, regions, style, color))

    def _rendered(self, image) -> None:  # noqa: ANN001
        self._canvas.image = qtutil.pil_to_qimage(image)
        self._canvas.update()

    @property
    def is_settled(self) -> bool:
        return self._settled or not self.images

    def run(self) -> None:
        if not self.images:
            return
        first = self.images[0]
        regions, style, color = list(self._canvas.regions), self._style, self._color
        faces, text = self._auto_faces.isChecked(), self._auto_text.isChecked()
        options = self.settings.conversion_options

        def work(path: str, _token, _progress) -> str:  # noqa: ANN001
            areas = list(regions) if path == first else []
            if path != first and (faces or text):
                image, _ = images.load(path)
                if faces:
                    areas += redact.detect_faces(image)
                if text:
                    areas += redact.detect_text(image)
            if not areas:
                raise ValueError(L("Nothing was changed."))
            return redact.redact_file(path, areas, style, color, options)

        self.jobs.run_each(L("Hiding"), L("Hidden"), self.images, work)
        self.close()


@registry.register("tool.redact")
def create(files: list[str], context) -> HideTool:  # noqa: ANN001
    return HideTool(files, context)


__all__ = ["HideTool"]
