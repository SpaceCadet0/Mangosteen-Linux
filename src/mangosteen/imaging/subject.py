"""Removing the background: the subject mask from the IS-Net model (ONNX Runtime) when it is installed, otherwise
OpenCV's GrabCut, which needs nothing but gives rougher edges."""

from __future__ import annotations

import hashlib
import os
import urllib.request

import cv2
import numpy as np
from PIL import Image

from ..convert import images
from ..core import capabilities, format_catalog, log, output_naming, paths
from ..core.file_format import FileFormat, detect
from ..core.loc import L, fmt
from ..core.settings import ConversionOptions
from .geometry import PixelRect

SIDE = 1024
_MEAN = np.array([0.485, 0.456, 0.406], dtype=np.float32)

# The model: IS-Net "general use" from DIS (Apache-2.0), as published in ONNX form by rembg.
MODEL_URL = "https://github.com/danielgatis/rembg/releases/download/v0.0.0/isnet-general-use.onnx"
MODEL_SHA256 = "60920e99c45464f2ba57bee2ad08c919a52bbf852739e96947fbb4358c0d964a"
MODEL_NAME = "isnet-general-use.onnx"


class NoSubject(Exception):
    def __init__(self, name: str | None = None) -> None:
        super().__init__(fmt("No subject was found in “{0}” to separate from the background.", name)
                         if name else L("No subject was found to separate from the background."))


def model_path() -> str | None:
    """The model file when it is installed (next to the app, or in the user's data folder)."""
    candidates = [paths.data_dir() / "models" / MODEL_NAME]
    appdir = os.environ.get("APPDIR")
    if appdir:
        candidates.insert(0, __import__("pathlib").Path(appdir) / "usr" / "share" / "mangosteen" / "models" / MODEL_NAME)
    override = os.environ.get("MANGOSTEEN_MODELS")
    if override:
        candidates.insert(0, __import__("pathlib").Path(override) / MODEL_NAME)
    for candidate in candidates:
        if candidate.is_file():
            return str(candidate)
    return None


def has_model() -> bool:
    return capabilities.has_onnxruntime() and model_path() is not None


def download_model(progress=lambda _fraction: None) -> str:  # noqa: ANN001
    """Fetches the model once into the user's data folder and checks its checksum. Nothing else is ever downloaded."""
    folder = paths.data_dir() / "models"
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / MODEL_NAME
    temporary = folder / (MODEL_NAME + ".part")
    digest = hashlib.sha256()
    with urllib.request.urlopen(MODEL_URL, timeout=30) as response, open(temporary, "wb") as stream:  # noqa: S310
        total = int(response.headers.get("Content-Length") or 0)
        done = 0
        while chunk := response.read(1 << 20):
            stream.write(chunk)
            digest.update(chunk)
            done += len(chunk)
            if total:
                progress(done / total)
    if digest.hexdigest() != MODEL_SHA256:
        temporary.unlink(missing_ok=True)
        raise ValueError("The downloaded model does not match its checksum.")
    os.replace(temporary, target)
    return str(target)


_session = None


def _model_mask(image: Image.Image) -> np.ndarray:
    global _session
    import onnxruntime as ort

    if _session is None:
        options = ort.SessionOptions()
        options.log_severity_level = 3
        _session = ort.InferenceSession(model_path(), options, providers=["CPUExecutionProvider"])
    small = np.asarray(image.convert("RGB").resize((SIDE, SIDE), Image.Resampling.BILINEAR), dtype=np.float32) / 255.0
    tensor = (small - _MEAN).transpose(2, 0, 1)[None].astype(np.float32)
    output = _session.run(None, {_session.get_inputs()[0].name: tensor})[0]
    mask = normalize(np.asarray(output, dtype=np.float32).reshape(SIDE, SIDE))
    return cv2.resize(mask, image.size, interpolation=cv2.INTER_LINEAR)


def normalize(output: np.ndarray) -> np.ndarray:
    """The model output (0…1) as 0…255, stretched so its lowest value becomes 0 and its highest 255. A photo without
    a subject stays below one half everywhere; it is not stretched, or noise would become a subject."""
    low, high = float(output.min()), float(output.max())
    if high < 0.5:
        low, high = 0.0, 1.0
    span = max(high - low, 1e-6)
    return np.clip(np.rint((output - low) / span * 255), 0, 255).astype(np.uint8)


def _grabcut_mask(image: Image.Image) -> np.ndarray:
    """A rougher mask without the model: GrabCut seeded with the middle of the picture as the subject."""
    scale = min(1.0, 800 / max(image.size))
    small = image.convert("RGB").resize((max(1, round(image.width * scale)), max(1, round(image.height * scale))))
    array = cv2.cvtColor(np.asarray(small), cv2.COLOR_RGB2BGR)
    mask = np.full(array.shape[:2], cv2.GC_PR_BGD, dtype=np.uint8)
    h, w = mask.shape
    mask[int(h * 0.08):int(h * 0.92), int(w * 0.08):int(w * 0.92)] = cv2.GC_PR_FGD
    mask[int(h * 0.25):int(h * 0.75), int(w * 0.25):int(w * 0.75)] = cv2.GC_FGD
    mask[:3, :], mask[-3:, :], mask[:, :3], mask[:, -3:] = (cv2.GC_BGD,) * 4
    cv2.grabCut(array, mask, None, np.zeros((1, 65), np.float64), np.zeros((1, 65), np.float64), 4, cv2.GC_INIT_WITH_MASK)
    result = np.where((mask == cv2.GC_FGD) | (mask == cv2.GC_PR_FGD), 255, 0).astype(np.uint8)
    result = cv2.GaussianBlur(cv2.morphologyEx(result, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8)), (0, 0), 1.2)
    return cv2.resize(result, image.size, interpolation=cv2.INTER_LINEAR)


def subject_mask(image: Image.Image) -> np.ndarray:
    """One opacity byte per pixel (255 = subject), the size of the image."""
    if has_model():
        try:
            return _model_mask(image)
        except Exception as error:  # noqa: BLE001 - fall back to the built-in method
            log.error("background model", error)
    return _grabcut_mask(image)


def coverage(mask: np.ndarray) -> float:
    return float((mask >= 128).mean()) if mask.size else 0.0


def has_subject(mask: np.ndarray) -> bool:
    """True when something was found to keep: at least a few pixels of solid subject."""
    return coverage(mask) >= 0.002


def bounds(mask: np.ndarray) -> PixelRect | None:
    """The smallest rectangle around the subject (pixels at least half opaque), or None when there is none."""
    ys, xs = np.nonzero(mask >= 128)
    if xs.size == 0:
        return None
    return PixelRect(int(xs.min()), int(ys.min()), int(xs.max() - xs.min() + 1), int(ys.max() - ys.min() + 1))


def cut(image: Image.Image, mask: np.ndarray) -> Image.Image:
    """The image with the mask as its opacity."""
    rgba = np.asarray(image.convert("RGBA")).copy()
    rgba[..., 3] = (rgba[..., 3].astype(np.uint16) * mask.astype(np.uint16) // 255).astype(np.uint8)
    return Image.fromarray(rgba, "RGBA")


def on_color(cutout: Image.Image, color: tuple[int, int, int, int]) -> Image.Image:
    """The cut-out over a solid colour, fully opaque."""
    background = Image.new("RGBA", cutout.size, (*color[:3], 255))
    return Image.alpha_composite(background, cutout)


def remove_file(path: str, fill: tuple[int, int, int, int] | None, crop_to_subject: bool,
                options: ConversionOptions) -> str:
    """Writes `<name> (no background).png` next to the original; with a fill colour the original's format is kept
    when it can be written."""
    image, metadata = images.load(path)
    mask = subject_mask(image)
    if not has_subject(mask):
        raise NoSubject(os.path.basename(path))
    subject = cut(image, mask)
    if crop_to_subject:
        box = bounds(mask)
        if box is not None:
            subject = subject.crop(box.as_box())
    result = on_color(subject, fill) if fill is not None else subject
    source = detect(path)
    target = source if fill is not None and source in format_catalog.EDITABLE_IMAGE_FORMATS else FileFormat.PNG

    def produce(output: str) -> None:
        images.write(result, target, output, options, metadata if options.preserve_metadata else None)

    return output_naming.write_atomically(os.path.dirname(os.path.abspath(path)),
                                          f"{output_naming.base_name(path)} ({L('no background')})", target.extension,
                                          produce)
