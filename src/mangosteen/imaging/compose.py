"""Putting images on canvases: Background (a photo on a colour, gradient, image or blurred copy of itself) and
Collage (several photos on one canvas)."""

from __future__ import annotations

import math
import os
from dataclasses import dataclass, field, replace
from enum import Enum

import cv2
import numpy as np
from PIL import Image

from ..convert import images, qtutil
from ..core import format_catalog, output_naming
from ..core.file_format import FileFormat, detect
from ..core.loc import L
from ..core.settings import ConversionOptions


@dataclass(frozen=True)
class RGBA:
    """An sRGB colour, 0…1 per channel."""

    red: float
    green: float
    blue: float
    alpha: float = 1.0

    def to_qcolor(self):  # noqa: ANN201
        from PySide6.QtGui import QColor

        return QColor.fromRgbF(self.red, self.green, self.blue, self.alpha)

    def to_tuple(self) -> tuple[int, int, int, int]:
        return tuple(int(round(c * 255)) for c in (self.red, self.green, self.blue, self.alpha))  # type: ignore[return-value]

    @staticmethod
    def from_qcolor(color) -> RGBA:  # noqa: ANN001
        return RGBA(color.redF(), color.greenF(), color.blueF(), color.alphaF())


WHITE = RGBA(1, 1, 1)


class CanvasAspect(Enum):
    AUTO = "auto"
    SQUARE = "1:1"
    R4X5 = "4:5"
    R5X4 = "5:4"
    R4X3 = "4:3"
    R3X4 = "3:4"
    R3X2 = "3:2"
    R2X3 = "2:3"
    R16X9 = "16:9"
    R9X16 = "9:16"

    @property
    def title(self) -> str:
        return L("Auto") if self is CanvasAspect.AUTO else self.value

    @property
    def ratio(self) -> float | None:
        if self is CanvasAspect.AUTO:
            return None
        w, h = self.value.split(":")
        return int(w) / int(h)


# MARK: Collage


class CollageLayout(Enum):
    GRID = "grid"
    ROW = "row"
    COLUMN = "column"
    FEATURED = "featured"


class CollageBackground(Enum):
    COLOR = "color"
    GRADIENT = "gradient"


@dataclass(frozen=True)
class CollageSettings:
    layout: CollageLayout = CollageLayout.GRID
    columns: int = 0  # grid columns; 0 picks a near-square grid
    aspect: CanvasAspect = CanvasAspect.AUTO
    width: int = 3000  # output width in pixels
    spacing: float = 0.015  # gap between and around photos, as a fraction of the width
    corner_radius: float = 0.0  # as a fraction of each cell's shorter side
    background: RGBA = WHITE
    format: FileFormat = FileFormat.JPG
    background_style: CollageBackground = CollageBackground.COLOR
    # The same gradient as Background starts with, drawn across the whole canvas.
    gradient_start: RGBA = RGBA(0.98, 0.62, 0.36)
    gradient_end: RGBA = RGBA(0.55, 0.27, 0.68)
    gradient_angle: float = 135.0
    shadow: float = 0.0  # 0…1


Box = tuple[float, float, float, float]  # x, y, width, height


def collage_layout(aspects: list[float], settings: CollageSettings) -> tuple[float, float, list[Box]]:
    """Canvas size and cell rectangles (origin top-left) for photos with the given aspect ratios (width / height).
    Cells are filled edge to edge (cropping when the proportions differ), except Row and Column with automatic
    proportions, which keep every photo whole."""
    count = len(aspects)
    if count == 0:
        return 0, 0, []
    width = float(max(settings.width, 100))
    gap = float(round(settings.spacing * width))
    ratio = settings.aspect.ratio
    fixed_height = float(round(width / ratio)) if ratio else None

    if settings.layout is CollageLayout.ROW:
        if fixed_height is not None:
            cell_width = (width - gap * (count + 1)) / count
            return width, fixed_height, [(gap + i * (cell_width + gap), gap, cell_width, fixed_height - gap * 2)
                                         for i in range(count)]
        row_height = (width - gap * (count + 1)) / sum(aspects)
        x = gap
        cells = []
        for aspect in aspects:
            cells.append((x, gap, aspect * row_height, row_height))
            x += aspect * row_height + gap
        return width, float(round(row_height + gap * 2)), cells

    if settings.layout is CollageLayout.COLUMN:
        column_width = width - gap * 2
        if fixed_height is not None:
            cell_height = (fixed_height - gap * (count + 1)) / count
            return width, fixed_height, [(gap, gap + i * (cell_height + gap), column_width, cell_height)
                                         for i in range(count)]
        y = gap
        cells = []
        for aspect in aspects:
            height = column_width / aspect
            cells.append((gap, y, column_width, height))
            y += height + gap
        return width, float(round(y)), cells

    if settings.layout is CollageLayout.FEATURED and count > 1:
        height = fixed_height if fixed_height is not None else float(round(width * 3 / 4))
        main_width = float(round((width - gap * 3) * 2 / 3))
        side_width = width - gap * 3 - main_width
        others = count - 1
        side_height = (height - gap * (others + 1)) / others
        cells = [(gap, gap, main_width, height - gap * 2)]
        cells += [(gap * 2 + main_width, gap + i * (side_height + gap), side_width, side_height) for i in range(others)]
        return width, height, cells

    columns = min(settings.columns, count) if settings.columns > 0 else int(math.ceil(math.sqrt(count)))
    rows = int(math.ceil(count / columns))
    cell_width = (width - gap * (columns + 1)) / columns
    if fixed_height is not None:
        height = fixed_height
        cell_height = (height - gap * (rows + 1)) / rows
    else:
        cell_height = cell_width / (sum(aspects) / count)
        height = float(round(cell_height * rows + gap * (rows + 1)))
    cells = []
    for index in range(count):
        row = index // columns
        in_row = count - row * columns if row == rows - 1 else columns
        # Centre a shorter last row.
        inset = (columns - in_row) * (cell_width + gap) / 2
        cells.append((inset + gap + index % columns * (cell_width + gap), gap + row * (cell_height + gap),
                      cell_width, cell_height))
    return width, height, cells


def _aspect_fill(image: Image.Image, size: tuple[int, int]) -> Image.Image:
    """Scales `image` to cover `size`, centred and clipped."""
    scale = max(size[0] / image.width, size[1] / image.height)
    resized = image.resize((max(1, round(image.width * scale)), max(1, round(image.height * scale))),
                           Image.Resampling.LANCZOS)
    left, top = (resized.width - size[0]) // 2, (resized.height - size[1]) // 2
    return resized.crop((left, top, left + size[0], top + size[1]))


def _rounded_mask(size: tuple[int, int], radius: float) -> Image.Image:
    """An anti-aliased rounded-rectangle mask, drawn at 4× and scaled down."""
    from PIL import ImageDraw

    factor = 4
    big = Image.new("L", (size[0] * factor, size[1] * factor), 0)
    ImageDraw.Draw(big).rounded_rectangle((0, 0, size[0] * factor - 1, size[1] * factor - 1), radius * factor, fill=255)
    return big.resize(size, Image.Resampling.LANCZOS)


def compose_collage(photos: list[Image.Image], settings: CollageSettings) -> Image.Image:
    aspects = [p.width / max(p.height, 1) for p in photos]
    width, height, cells = collage_layout(aspects, settings)
    if width < 1 or height < 1:
        raise ValueError("The collage has no size.")
    size = (int(width), int(height))
    if settings.background_style is CollageBackground.GRADIENT:
        canvas = _gradient(size, settings.gradient_start, settings.gradient_end, settings.gradient_angle)
    else:
        canvas = Image.new("RGBA", size, settings.background.to_tuple())
    boxes = [((round(x), round(y)), (max(1, round(w)), max(1, round(h)))) for x, y, w, h in cells]
    masks = [_rounded_mask(cell, radius) if (radius := settings.corner_radius * min(cell)) > 0.5 else None
             for _origin, cell in boxes]
    # Every shadow first, then the photos, so no shadow falls on a neighbouring photo.
    if settings.shadow > 0:
        for (origin, cell), mask in zip(boxes, masks):
            _cell_shadow(canvas, origin, cell, mask, settings.shadow)
    for photo, (origin, cell), mask in zip(photos, boxes, masks):
        fitted = _aspect_fill(photo.convert("RGBA"), cell)
        if mask is not None:
            fitted.putalpha(Image.composite(fitted.getchannel("A"), Image.new("L", cell, 0), mask))
        canvas.alpha_composite(fitted, origin)
    return canvas.convert("RGB") if not settings.format.supports_alpha else canvas


def _cell_shadow(canvas: Image.Image, origin: tuple[int, int], cell: tuple[int, int], mask: Image.Image | None,
                 shadow: float) -> None:
    """A soft shadow of one cell's shape: blur shadow × shorter side × 0.08, moved down by 0.35 of the blur, black at
    0.25 + shadow × 0.3."""
    blur = shadow * min(cell) * 0.08
    if blur < 0.5:
        return
    pad = int(blur * 3) + 2
    offset = round(blur * 0.35)
    alpha = Image.new("L", (cell[0] + pad * 2, cell[1] + pad * 2), 0)
    alpha.paste(mask if mask is not None else Image.new("L", cell, 255), (pad, pad))
    blurred = cv2.GaussianBlur(np.asarray(alpha), (0, 0), max(blur / 2, 0.1))
    layer = Image.new("RGBA", alpha.size, (0, 0, 0, 0))
    layer.putalpha(Image.fromarray((blurred.astype(np.float32) * (0.25 + shadow * 0.3)).astype(np.uint8), "L"))
    left, top = origin[0] - pad, origin[1] + offset - pad
    # alpha_composite takes no negative positions: crop what lies outside the canvas.
    crop_left, crop_top = max(0, -left), max(0, -top)
    canvas.alpha_composite(layer.crop((crop_left, crop_top, layer.width, layer.height)),
                           (left + crop_left, top + crop_top))


def collage_files(paths: list[str], settings: CollageSettings, options: ConversionOptions) -> str:
    """Writes `Collage.<ext>` next to the first image."""
    if not paths:
        raise ValueError(L("No suitable files."))
    photos = [images.load(p, settings.width)[0] for p in paths]
    result = compose_collage(photos, settings)
    directory = os.path.dirname(os.path.abspath(paths[0]))

    def produce(output: str) -> None:
        images.write(result, settings.format, output, options)

    return output_naming.write_atomically(directory, L("Collage"), settings.format.extension, produce)


# MARK: Background


class FrameBackground(Enum):
    COLOR = "color"
    GRADIENT = "gradient"
    IMAGE = "image"
    BLUR = "blur"


@dataclass(frozen=True)
class FrameSettings:
    background: FrameBackground = FrameBackground.GRADIENT
    color: RGBA = RGBA(0.96, 0.95, 0.93)
    gradient_start: RGBA = RGBA(0.98, 0.62, 0.36)
    gradient_end: RGBA = RGBA(0.55, 0.27, 0.68)
    gradient_angle: float = 135.0  # degrees, 0 = left to right, 90 = bottom to top
    background_image: str | None = None
    blur: float = 0.5  # 0…1, for the image and blur backgrounds
    aspect: CanvasAspect = CanvasAspect.AUTO
    padding: float = 0.08  # margin around the photo as a fraction of its longer side
    corner_radius: float = 0.03  # as a fraction of the photo's shorter side
    circle: bool = False  # the photo is cut to its centred square and made round
    shadow: float = 0.5  # 0…1


def canvas_size(photo_width: float, photo_height: float, settings: FrameSettings) -> tuple[int, int]:
    margin = settings.padding * max(photo_width, photo_height)
    width, height = photo_width + margin * 2, photo_height + margin * 2
    ratio = settings.aspect.ratio
    if ratio:
        if width / height < ratio:
            width = height * ratio
        else:
            height = width / ratio
    return int(round(width)), int(round(height))


def _gradient(size: tuple[int, int], start: RGBA, end: RGBA, angle: float) -> Image.Image:
    width, height = size
    radians = math.radians(angle)
    cosine, sine = math.cos(radians), math.sin(radians)
    half = (abs(cosine) * width + abs(sine) * height) / 2
    ys, xs = np.mgrid[0:height, 0:width].astype(np.float32)
    # Position along the gradient line (y grows downwards on screen, the angle grows upwards).
    projected = ((xs - width / 2) * cosine - (ys - height / 2) * sine) / (2 * half) + 0.5
    t = np.clip(projected, 0, 1)[..., None]
    a = np.array([start.red, start.green, start.blue, start.alpha], dtype=np.float32)
    b = np.array([end.red, end.green, end.blue, end.alpha], dtype=np.float32)
    return Image.fromarray((np.clip(a + (b - a) * t, 0, 1) * 255).astype(np.uint8), "RGBA")


def _blurred(image: Image.Image, radius: float) -> Image.Image:
    if radius < 0.5:
        return image
    array = np.asarray(image.convert("RGBA"))
    return Image.fromarray(cv2.GaussianBlur(array, (0, 0), radius, borderType=cv2.BORDER_REPLICATE), "RGBA")


def compose_frame(source: Image.Image, settings: FrameSettings, backdrop: Image.Image | None = None) -> Image.Image:
    """Places a photo on a new canvas with a margin, rounded corners and a shadow."""
    photo = source.convert("RGBA")
    if settings.circle and photo.width != photo.height:
        side = min(photo.size)
        left, top = (photo.width - side) // 2, (photo.height - side) // 2
        photo = photo.crop((left, top, left + side, top + side))
    size = canvas_size(photo.width, photo.height, settings)
    longest = max(size)
    if settings.background is FrameBackground.COLOR:
        canvas = Image.new("RGBA", size, settings.color.to_tuple())
    elif settings.background is FrameBackground.GRADIENT:
        canvas = _gradient(size, settings.gradient_start, settings.gradient_end, settings.gradient_angle)
    else:
        base = photo if settings.background is FrameBackground.BLUR else (backdrop.convert("RGBA") if backdrop else photo)
        base = _aspect_fill(base, size)
        canvas = _blurred(base, settings.blur * longest * 0.04) if settings.blur > 0 else base

    left, top = (size[0] - photo.width) // 2, (size[1] - photo.height) // 2
    radius = (0.5 if settings.circle else settings.corner_radius) * min(photo.size)
    mask = _rounded_mask(photo.size, radius) if radius > 0.5 else Image.new("L", photo.size, 255)
    if settings.shadow > 0:
        blur = settings.shadow * longest * 0.035
        pad = int(blur * 3) + 2
        shadow_alpha = Image.new("L", (size[0] + pad * 2, size[1] + pad * 2), 0)
        shadow_alpha.paste(mask, (left + pad, top + pad + int(blur * 0.35)))
        array = cv2.GaussianBlur(np.asarray(shadow_alpha), (0, 0), max(blur / 2, 0.1))
        strength = 0.25 + settings.shadow * 0.3
        layer = Image.new("RGBA", shadow_alpha.size, (0, 0, 0, 0))
        layer.putalpha(Image.fromarray((array.astype(np.float32) * strength).astype(np.uint8), "L"))
        canvas.alpha_composite(layer.crop((pad, pad, pad + size[0], pad + size[1])))
    rounded = photo.copy()
    rounded.putalpha(Image.composite(photo.getchannel("A"), Image.new("L", photo.size, 0), mask))
    canvas.alpha_composite(rounded, (left, top))
    return canvas


def frame_file(path: str, settings: FrameSettings, options: ConversionOptions) -> str:
    """Writes `<name> (background).<ext>` next to the original."""
    source = detect(path)
    if source is None:
        raise ValueError(f"Unknown format of {os.path.basename(path)}.")
    photo, metadata = images.load(path)
    backdrop = images.load(settings.background_image, 4096)[0] if settings.background_image else None
    result = compose_frame(photo, settings, backdrop)
    target = source if source in format_catalog.EDITABLE_IMAGE_FORMATS else FileFormat.PNG

    def produce(output: str) -> None:
        images.write(result, target, output, options, metadata)

    return output_naming.write_atomically(os.path.dirname(os.path.abspath(path)),
                                          f"{output_naming.base_name(path)} ({L('background')})", target.extension, produce)


__all__ = ["RGBA", "WHITE", "CanvasAspect", "CollageBackground", "CollageSettings", "FrameSettings", "replace", "field", "qtutil"]
