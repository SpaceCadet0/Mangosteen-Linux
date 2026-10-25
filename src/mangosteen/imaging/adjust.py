"""Photo adjustments, the same set as on the other Mangosteen apps. Every value at its default leaves the image
unchanged."""

from __future__ import annotations

from dataclasses import dataclass, fields
from enum import Enum

import cv2
import numpy as np
from PIL import Image


class PhotoEffect(Enum):
    NONE = "none"
    MONO = "mono"
    NOIR = "noir"
    TONAL = "tonal"
    CHROME = "chrome"
    FADE = "fade"
    INSTANT = "instant"
    PROCESS = "process"
    TRANSFER = "transfer"


@dataclass(frozen=True)
class PhotoAdjustments:
    exposure: float = 0.0       # EV, -2…2
    brightness: float = 0.0     # -1…1
    contrast: float = 0.0       # -1…1
    highlights: float = 0.0     # -1…1 (negative recovers highlights)
    shadows: float = 0.0        # -1…1 (positive lifts shadows)
    temperature: float = 0.0    # -1 cooler … 1 warmer
    tint: float = 0.0           # -1 green … 1 magenta
    saturation: float = 0.0     # -1…1
    vibrance: float = 0.0       # -1…1
    sharpness: float = 0.0      # 0…1
    clarity: float = 0.0        # 0…1
    noise_reduction: float = 0.0  # 0…1
    dehaze: float = 0.0         # 0…1
    effect: PhotoEffect = PhotoEffect.NONE
    vignette: float = 0.0       # 0…1
    grain: float = 0.0          # 0…1

    @property
    def is_identity(self) -> bool:
        return self == PhotoAdjustments()

    def changed_fields(self) -> list[str]:
        default = PhotoAdjustments()
        return [f.name for f in fields(self) if getattr(self, f.name) != getattr(default, f.name)]


def _luma(r, g, b):  # noqa: ANN001, ANN202
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def box_blur(plane: np.ndarray, radius: int) -> np.ndarray:
    """Three box blurs, which approximate a Gaussian of about that radius."""
    size = radius * 2 + 1
    result = plane
    for _ in range(3):
        result = cv2.blur(result, (size, size), borderType=cv2.BORDER_REPLICATE)
    return result


def apply(source: Image.Image, a: PhotoAdjustments, scale: float = 1.0, cancelled=lambda: False) -> Image.Image:  # noqa: ANN001
    """Applies the adjustments. `scale` is the image size relative to the full photo, so radius-based effects look the
    same in a preview."""
    if a.is_identity:
        return source.copy()
    rgba = source.convert("RGBA")
    data = np.asarray(rgba, dtype=np.float32) / 255.0
    r, g, b, alpha = (data[..., i].copy() for i in range(4))
    height, width = r.shape

    exposure = np.float32(2.0 ** a.exposure)
    r, g, b = r * exposure, g * exposure, b * exposure
    brightness = np.float32(a.brightness * 0.25)
    r, g, b = r + brightness, g + brightness, b + brightness

    # Shadows and highlights move the tones by luminance, keeping the colour.
    if a.shadows != 0 or a.highlights != 0:
        luma = np.clip(_luma(r, g, b), 0, 1)
        shadow_weight = (1 - luma) ** 2
        highlight_weight = luma ** 2
        target = luma + np.float32(a.shadows * 0.45) * shadow_weight * luma * 2 + np.float32(a.highlights * 0.35) * highlight_weight
        safe = luma > 0.0001
        factor = np.where(safe, target / np.where(safe, luma, 1), 1.0)
        r, g, b = r * factor, g * factor, b * factor
        r, g, b = (np.where(safe, ch, target) for ch in (r, g, b))
    if a.contrast != 0:
        c = np.float32(1 + a.contrast * (0.8 if a.contrast > 0 else 0.6))
        r, g, b = ((ch - 0.5) * c + 0.5 for ch in (r, g, b))
    haze = np.float32(a.dehaze * 0.12)
    if haze > 0:
        r, g, b = ((ch - haze) / (1 - haze) for ch in (r, g, b))
    if a.temperature != 0 or a.tint != 0:
        t = np.float32(a.temperature * 0.12)
        tint = np.float32(a.tint * 0.08)
        r, b = r * (1 + t), b * (1 - t)
        g = g * (1 - tint)
        r, b = r * (1 + tint * 0.5), b * (1 + tint * 0.5)
    saturation = np.float32(1 + a.saturation + a.dehaze * 0.25)
    if a.vibrance != 0:
        spread = np.clip(np.maximum(r, np.maximum(g, b)) - np.minimum(r, np.minimum(g, b)), 0, 1)
        saturation = saturation * (1 + np.float32(a.vibrance) * (1 - spread))
    if np.any(saturation != 1):
        luma = _luma(r, g, b)
        r, g, b = (luma + (ch - luma) * saturation for ch in (r, g, b))
    r, g, b = _effect(a.effect, r, g, b)
    if cancelled():
        raise InterruptedError

    if a.noise_reduction > 0:
        radius = max(1, round(2 * scale))
        amount = np.float32(a.noise_reduction * 0.8)
        r, g, b = (ch + (box_blur(ch, radius) - ch) * amount for ch in (r, g, b))
    if a.clarity > 0:
        r, g, b = _unsharp(r, g, b, max(2, round(24 * scale)), a.clarity * 0.7)
    if cancelled():
        raise InterruptedError
    if a.sharpness > 0:
        r, g, b = _unsharp(r, g, b, max(1, round(1.5 * scale)), a.sharpness * 1.6)

    if a.vignette > 0:
        ys = (np.arange(height, dtype=np.float32) + 0.5) / height - 0.5
        xs = (np.arange(width, dtype=np.float32) + 0.5) / width - 0.5
        d = np.sqrt(ys[:, None] ** 2 + xs[None, :] ** 2) / 0.7071
        t = np.clip((d - 0.35) / 0.65, 0, 1)
        factor = 1 - np.float32(a.vignette) * 0.85 * t * t * (3 - 2 * t)
        r, g, b = r * factor, g * factor, b * factor
    if a.grain > 0:
        cell = max(1, round(1.5 * scale))
        noise = (_hash(np.arange(width) // cell, np.arange(height) // cell) - 0.5) * 2 * np.float32(a.grain * 0.12)
        r, g, b = r + noise, g + noise, b + noise

    out = np.stack([r, g, b, alpha], axis=-1)
    result = Image.fromarray(np.clip(np.rint(out * 255), 0, 255).astype(np.uint8), "RGBA")
    return result if source.mode == "RGBA" else result.convert("RGB")


def _hash(xs: np.ndarray, ys: np.ndarray) -> np.ndarray:
    x = xs.astype(np.uint32)[None, :]
    y = ys.astype(np.uint32)[:, None]
    with np.errstate(over="ignore"):
        h = x * np.uint32(374761393) + y * np.uint32(668265263)
        h = (h ^ (h >> np.uint32(13))) * np.uint32(1274126177)
        h = h ^ (h >> np.uint32(16))
    return h.astype(np.float32) / np.float32(4294967295.0)


def _unsharp(r, g, b, radius: int, amount: float):  # noqa: ANN001, ANN202
    amount = np.float32(amount)
    return tuple(ch + (ch - box_blur(ch, radius)) * amount for ch in (r, g, b))


def _effect(effect: PhotoEffect, r, g, b):  # noqa: ANN001, ANN202
    """Approximations of the Core Image photo effects used on the Mac."""
    if effect is PhotoEffect.NONE:
        return r, g, b
    l = _luma(r, g, b)  # noqa: E741
    if effect is PhotoEffect.MONO:
        return l, l, l
    if effect is PhotoEffect.NOIR:
        l = np.clip((l - 0.5) * 1.45 + 0.47, 0, 1)  # noqa: E741
        return l, l, l
    if effect is PhotoEffect.TONAL:
        l = l * 0.9 + 0.05  # noqa: E741
        return l, l, l
    if effect is PhotoEffect.CHROME:
        return tuple((l + (ch - l) * 1.25 - 0.5) * 1.1 + 0.5 for ch in (r, g, b))
    if effect is PhotoEffect.FADE:
        return ((l + (r - l) * 0.7) * 0.85 + 0.1, (l + (g - l) * 0.7) * 0.85 + 0.1, (l + (b - l) * 0.7) * 0.85 + 0.12)
    if effect is PhotoEffect.INSTANT:
        return ((l + (r - l) * 0.85) * 0.9 + 0.09, (l + (g - l) * 0.85) * 0.88 + 0.07, (l + (b - l) * 0.85) * 0.8 + 0.06)
    if effect is PhotoEffect.PROCESS:
        return r * 0.92 + 0.04, g * 1.0 + 0.02 * (1 - l), b * 0.88 + 0.1 * (1 - l)
    if effect is PhotoEffect.TRANSFER:
        return r * 1.05 + 0.04, g * 0.97 + 0.02, b * 0.82 + 0.03
    return r, g, b
