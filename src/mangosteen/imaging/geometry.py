"""Crop presets, the geometry of the crop frame (all in normalised coordinates), resize rules and transforms."""

from __future__ import annotations

import math
from dataclasses import dataclass, replace
from enum import IntFlag

from PIL import Image


@dataclass(frozen=True)
class PixelRect:
    x: int
    y: int
    width: int
    height: int

    @property
    def right(self) -> int:
        return self.x + self.width

    @property
    def bottom(self) -> int:
        return self.y + self.height

    def as_box(self) -> tuple[int, int, int, int]:
        return (self.x, self.y, self.right, self.bottom)


@dataclass(frozen=True)
class UnitRect:
    """A rectangle in normalised coordinates: 0…1, origin at the top-left of the upright image."""

    x: float
    y: float
    width: float
    height: float

    @property
    def right(self) -> float:
        return self.x + self.width

    @property
    def bottom(self) -> float:
        return self.y + self.height

    def to_pixels(self, image_width: int, image_height: int) -> PixelRect:
        """The rectangle in whole pixels, clamped to the image and never empty."""
        left = min(max(round_half_up(self.x * image_width), 0), image_width - 1)
        top = min(max(round_half_up(self.y * image_height), 0), image_height - 1)
        right = min(max(round_half_up(self.right * image_width), left + 1), image_width)
        bottom = min(max(round_half_up(self.bottom * image_height), top + 1), image_height)
        return PixelRect(left, top, right - left, bottom - top)

    def inflate(self, fraction: float) -> UnitRect:
        """Grows the rectangle by a fraction of its size on every side, staying inside the image."""
        dx, dy = self.width * fraction, self.height * fraction
        x, y = max(0.0, self.x - dx), max(0.0, self.y - dy)
        return UnitRect(x, y, min(1.0, self.right + dx) - x, min(1.0, self.bottom + dy) - y)


FULL = UnitRect(0, 0, 1, 1)


def round_half_up(value: float) -> int:
    """Rounds .5 away from zero for positive numbers, like the other Mangosteen apps (Python's round() is bankers')."""
    return int(math.floor(value + 0.5)) if value >= 0 else -int(math.floor(-value + 0.5))


# (title, ratio, is_original): Free, the image's own proportions, and the usual ratios (width / height).
ASPECTS: list[tuple[str, float | None, bool]] = [
    ("Free", None, False), ("Original", None, True),
    ("1:1", 1.0, False), ("4:5", 4 / 5, False), ("5:4", 5 / 4, False), ("4:3", 4 / 3, False), ("3:4", 3 / 4, False),
    ("3:2", 3 / 2, False), ("2:3", 2 / 3, False), ("16:9", 16 / 9, False), ("9:16", 9 / 16, False),
]

MINIMUM_SIZE = 0.02


def centered_rect(aspect: float, image_width: int, image_height: int) -> UnitRect:
    """The largest rectangle of `aspect` (pixel width / height) centred in the image."""
    image_aspect = image_width / image_height
    if aspect > image_aspect:
        height = image_aspect / aspect
        return UnitRect(0, (1 - height) / 2, 1, height)
    width = aspect / image_aspect
    return UnitRect((1 - width) / 2, 0, width, 1)


class Edges(IntFlag):
    NONE = 0
    LEFT = 1
    TOP = 2
    RIGHT = 4
    BOTTOM = 8
    TOP_LEFT = TOP | LEFT
    TOP_RIGHT = TOP | RIGHT
    BOTTOM_LEFT = BOTTOM | LEFT
    BOTTOM_RIGHT = BOTTOM | RIGHT


def move(rect: UnitRect, dx: float, dy: float) -> UnitRect:
    """Moves the whole frame by (dx, dy), keeping it inside the image."""
    return replace(rect, x=min(max(rect.x + dx, 0.0), 1 - rect.width), y=min(max(rect.y + dy, 0.0), 1 - rect.height))


def resize(rect: UnitRect, edges: Edges, dx: float, dy: float, unit_aspect: float | None) -> UnitRect | None:
    """Drags the given edges by (dx, dy). With `unit_aspect` (normalised width / height) the frame keeps its
    proportions. Returns None when the result would leave the image or become too small."""
    left, top, right, bottom = rect.x, rect.y, rect.right, rect.bottom
    if edges & Edges.LEFT:
        left += dx
    if edges & Edges.RIGHT:
        right += dx
    if edges & Edges.TOP:
        top += dy
    if edges & Edges.BOTTOM:
        bottom += dy

    if unit_aspect:
        horizontal = bool(edges & (Edges.LEFT | Edges.RIGHT))
        vertical = bool(edges & (Edges.TOP | Edges.BOTTOM))
        width, height = right - left, bottom - top
        if horizontal and (not vertical or abs(dx) >= abs(dy)):
            height = width / unit_aspect
        else:
            width = height * unit_aspect
        # Grow from the opposite edge (or from the centre when only one axis is dragged).
        if edges & Edges.LEFT:
            left = right - width
        elif edges & Edges.RIGHT:
            right = left + width
        else:
            center = (rect.x + rect.right) / 2
            left, right = center - width / 2, center + width / 2
        if edges & Edges.TOP:
            top = bottom - height
        elif edges & Edges.BOTTOM:
            bottom = top + height
        else:
            middle = (rect.y + rect.bottom) / 2
            top, bottom = middle - height / 2, middle + height / 2

    tolerance = 0.0001
    if (left < -tolerance or top < -tolerance or right > 1 + tolerance or bottom > 1 + tolerance
            or right - left < MINIMUM_SIZE or bottom - top < MINIMUM_SIZE):
        return None
    left, top = max(0.0, left), max(0.0, top)
    return UnitRect(left, top, min(1.0, right) - left, min(1.0, bottom) - top)


def crop(image: Image.Image, rect: PixelRect) -> Image.Image:
    return image.crop(rect.as_box())


def even_cuts(parts: int) -> list[float]:
    """Cut positions (0…1) that divide a side into `parts` equal pieces."""
    return [i / parts for i in range(1, max(parts, 1))]


def tile_edges(cuts, length: int) -> list[int]:  # noqa: ANN001
    """Pixel edges of the parts along a side of `length` pixels, cut at `cuts` (fractions of the side) rounded to the
    nearest pixel; empty parts are dropped. Starts at 0, ends at the length."""
    edges = [0]
    for edge in [round_half_up(c * length) for c in sorted(c for c in cuts if 0 < c < 1)] + [length]:
        if edge > edges[-1]:
            edges.append(edge)
    return edges


def tiles(column_cuts, row_cuts, width: int, height: int) -> list[PixelRect]:  # noqa: ANN001
    """The parts of a grid, row by row from the top-left."""
    xs, ys = tile_edges(column_cuts, width), tile_edges(row_cuts, height)
    return [PixelRect(xs[c], ys[r], xs[c + 1] - xs[c], ys[r + 1] - ys[r])
            for r in range(len(ys) - 1) for c in range(len(xs) - 1)]


def clamp_cut(cuts: list[float], index: int, position: float, gap: float = 0.02) -> float:
    """Moves cut `index` to `position`, kept at least `gap` away from its neighbours and from the edges."""
    low = (cuts[index - 1] if index > 0 else 0.0) + gap
    high = (cuts[index + 1] if index < len(cuts) - 1 else 1.0) - gap
    return cuts[index] if low > high else min(max(position, low), high)


# MARK: Resize

MAX_SIDE = 20000
PERCENTS = [25, 50, 75]
LONG_SIDES = [3840, 2560, 1920, 1280, 1080, 800]


@dataclass(frozen=True)
class ResizeRule:
    """One rule for every file of a resize: a share of the size, a long side (smaller images are not enlarged), a
    width or a height with the other side to scale, or an exact size. Each side ends up between 1 and `MAX_SIDE`."""

    kind: str  # "percent", "long_side", "width", "height", "exact"
    value: float = 100
    height: int = 0

    def apply(self, width: int, height: int) -> tuple[int, int]:
        w, h = float(width), float(height)
        if self.kind == "percent":
            w, h = width * self.value / 100.0, height * self.value / 100.0
        elif self.kind == "long_side":
            scale = min(1.0, self.value / max(width, height))
            w, h = width * scale, height * scale
        elif self.kind == "width":
            w, h = self.value, height * self.value / width
        elif self.kind == "height":
            w, h = width * self.value / height, self.value
        elif self.kind == "exact":
            w, h = self.value, self.height
        # Beyond the limit both sides shrink together, so the proportions hold (an exact size is taken as it is).
        if self.kind != "exact" and max(w, h) > MAX_SIDE:
            fit = MAX_SIDE / max(w, h)
            w, h = w * fit, h * fit

        def side(value: float) -> int:
            return min(max(round_half_up(value), 1), MAX_SIDE)

        return side(w), side(h)


def result_name(base_name: str, width: int, height: int) -> str:
    """"photo (1920×1440)": the name of a resized result, next to the original."""
    return f"{base_name} ({width}×{height})"


# MARK: Transform


@dataclass(frozen=True)
class ImageTransform:
    """Rotation by quarter turns and mirroring, as shown on screen: the image is turned first, then mirrored."""

    quarter_turns: int = 0
    flip_horizontal: bool = False
    flip_vertical: bool = False

    @property
    def is_identity(self) -> bool:
        return self.quarter_turns == 0 and not self.flip_horizontal and not self.flip_vertical

    def size(self, width: int, height: int) -> tuple[int, int]:
        """The size after the turn: a quarter turn swaps width and height."""
        return (height, width) if self.quarter_turns % 2 == 1 else (width, height)

    def rotate(self, clockwise: bool) -> ImageTransform:
        """Turns what is on screen by 90°. A mirror made before the turn now runs along the other axis."""
        return ImageTransform((self.quarter_turns + (1 if clockwise else 3)) % 4, self.flip_vertical, self.flip_horizontal)

    def flip(self, horizontal: bool) -> ImageTransform:
        if horizontal:
            return replace(self, flip_horizontal=not self.flip_horizontal)
        return replace(self, flip_vertical=not self.flip_vertical)

    def apply(self, image: Image.Image) -> Image.Image:
        if self.is_identity:
            return image
        result = image
        turn = {1: Image.Transpose.ROTATE_270, 2: Image.Transpose.ROTATE_180, 3: Image.Transpose.ROTATE_90}.get(
            self.quarter_turns)
        if turn is not None:
            result = result.transpose(turn)
        if self.flip_horizontal:
            result = result.transpose(Image.Transpose.FLIP_LEFT_RIGHT)
        if self.flip_vertical:
            result = result.transpose(Image.Transpose.FLIP_TOP_BOTTOM)
        return result
