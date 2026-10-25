"""Crops, turns, resizes and cuts images, writing the result next to the original."""

from __future__ import annotations

import os

from PIL import Image

from ..convert import images
from ..core import format_catalog, output_naming
from ..core.file_format import FileFormat, detect
from ..core.loc import L
from ..core.settings import ConversionOptions
from . import geometry
from .geometry import ImageTransform, ResizeRule, UnitRect


def _target(source: FileFormat) -> FileFormat:
    """Read-only formats (SVG, PSD…) are saved as PNG."""
    return source if source in format_catalog.EDITABLE_IMAGE_FORMATS else FileFormat.PNG


def resized(image: Image.Image, width: int, height: int) -> Image.Image:
    if (width, height) == image.size:
        return image
    return image.resize((width, height), Image.Resampling.LANCZOS)


def crop_file(path: str, rect: UnitRect, output_size: tuple[int, int] | None, transform: ImageTransform | None,
              column_cuts: list[float], row_cuts: list[float], options: ConversionOptions) -> str:
    """Turns and mirrors the image, crops `rect` (normalised, in the turned image), scales it to `output_size` when
    given, and writes `<name> (cropped).<ext>` next to the original, keeping its format and metadata. With cut lines
    the result is cut into parts saved in a `<name> (parts)` folder."""
    transform = transform or ImageTransform()
    source = detect(path)
    if source is None:
        raise ValueError(f"Unknown format of {os.path.basename(path)}.")
    original, metadata = images.load(path)
    image = transform.apply(original)
    area = rect.to_pixels(image.width, image.height)
    cropped = image.crop(area.as_box())
    if output_size and output_size[0] >= 1 and output_size[1] >= 1:
        cropped = resized(cropped, int(output_size[0]), int(output_size[1]))
    target = _target(source)
    base = output_naming.base_name(path)
    carried = metadata if options.preserve_metadata else None
    directory = os.path.dirname(os.path.abspath(path))

    if column_cuts or row_cuts:
        parts = [cropped.crop(t.as_box()) for t in geometry.tiles(column_cuts, row_cuts, cropped.width, cropped.height)]

        def produce_parts(folder: str) -> None:
            os.makedirs(folder)
            for index, part in enumerate(parts):
                name = f"{base} {output_naming.part_number(index, len(parts))}.{target.extension}"
                images.write(part, target, os.path.join(folder, name), options, carried)

        return output_naming.write_atomically(directory, f"{base} ({L('parts')})", "", produce_parts)

    is_crop = output_size is not None or (area.width, area.height) != image.size
    suffix = L("cropped") if is_crop or transform.is_identity else L("changed")

    def produce(output: str) -> None:
        images.write(cropped, target, output, options, carried)

    return output_naming.write_atomically(directory, f"{base} ({suffix})", target.extension, produce)


def resize_file(path: str, rule: ResizeRule, transform: ImageTransform | None, options: ConversionOptions) -> str:
    """Turns and mirrors the image, scales it by `rule` and writes `<name> (W×H).<ext>` next to the original, keeping
    its format and metadata."""
    transform = transform or ImageTransform()
    source = detect(path)
    if source is None:
        raise ValueError(f"Unknown format of {os.path.basename(path)}.")
    original, metadata = images.load(path)
    image = transform.apply(original)
    width, height = rule.apply(image.width, image.height)
    result = resized(image, width, height)
    target = _target(source)

    def produce(output: str) -> None:
        images.write(result, target, output, options, metadata if options.preserve_metadata else None)

    return output_naming.write_atomically(os.path.dirname(os.path.abspath(path)),
                                          geometry.result_name(output_naming.base_name(path), width, height),
                                          target.extension, produce)


def edit_file(path: str, adjustments, options: ConversionOptions) -> str:  # noqa: ANN001
    """Writes `<name> (edited).<ext>` next to the original with the photo adjustments applied."""
    from . import adjust

    source = detect(path)
    if source is None:
        raise ValueError(f"Unknown format of {os.path.basename(path)}.")
    image, metadata = images.load(path)
    result = adjust.apply(image, adjustments)
    target = _target(source)

    def produce(output: str) -> None:
        images.write(result, target, output, options, metadata if options.preserve_metadata else None)

    return output_naming.write_atomically(os.path.dirname(os.path.abspath(path)),
                                          f"{output_naming.base_name(path)} ({L('edited')})", target.extension, produce)
