"""Reading and editing image metadata on a copy of the file. JPEG is edited by replacing its metadata segments, so the
pixels are never re-encoded; PNG and TIFF are re-saved losslessly. Other formats are not edited."""

from __future__ import annotations

import io
import os
import re
import struct
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum

from PIL import Image
from PIL.ExifTags import GPSTAGS, TAGS

from ..core import output_naming
from ..core.file_format import FileFormat, detect
from ..core.loc import L, fmt

SUPPORTED = {FileFormat.JPG, FileFormat.TIFF, FileFormat.PNG}

_EXIF_IFD = 0x8769
_GPS_IFD = 0x8825
_DATE_FORMAT = "%Y:%m:%d %H:%M:%S"


class MetadataField(Enum):
    DESCRIPTION = 0x010E
    AUTHOR = 0x013B
    COPYRIGHT = 0x8298
    MAKE = 0x010F
    MODEL = 0x0110

    @property
    def title(self) -> str:
        return {MetadataField.DESCRIPTION: L("Description"), MetadataField.AUTHOR: L("Author"),
                MetadataField.COPYRIGHT: L("Copyright"), MetadataField.MAKE: L("Camera maker"),
                MetadataField.MODEL: L("Camera model")}[self]


@dataclass
class MetadataChanges:
    """What to change. Only fields present are touched; an empty string removes a field."""

    remove_all: bool = False
    remove_location: bool = False
    text: dict[MetadataField, str] = field(default_factory=dict)
    date_taken: datetime | None = None

    @property
    def is_empty(self) -> bool:
        return not self.remove_all and not self.remove_location and not self.text and self.date_taken is None


@dataclass
class MetadataInfo:
    entries: list[tuple[str, str, str]]  # group, key, value
    text: dict[MetadataField, str]
    date_taken: datetime | None
    location: tuple[float, float] | None


def _describe(value: object) -> str:
    if isinstance(value, bytes):
        return fmt("{0} bytes", len(value))
    if isinstance(value, (tuple, list)):
        return ", ".join(_describe(v) for v in list(value)[:12])
    if isinstance(value, dict):
        return fmt("{0} fields", len(value))
    return str(value).strip("\x00")


def _degrees(values, ref: str | None) -> float | None:  # noqa: ANN001
    try:
        d, m, s = (float(v) for v in values)
    except (TypeError, ValueError):
        return None
    result = d + m / 60 + s / 3600
    return -result if ref in ("S", "W") else result


def read(path: str) -> MetadataInfo:
    """Every metadata value, the common fields, the date taken and the location of a file."""
    with Image.open(path) as image:
        exif = image.getexif()
        entries: list[tuple[str, str, str]] = []
        for tag, value in exif.items():
            if tag in (_EXIF_IFD, _GPS_IFD, 0x927C):
                continue
            entries.append(("EXIF", TAGS.get(tag, str(tag)), _describe(value)))
        sub = exif.get_ifd(_EXIF_IFD) if hasattr(exif, "get_ifd") else {}
        for tag, value in sub.items():
            if tag != 0x927C:
                entries.append(("EXIF", TAGS.get(tag, str(tag)), _describe(value)))
        gps = exif.get_ifd(_GPS_IFD) if hasattr(exif, "get_ifd") else {}
        for tag, value in gps.items():
            entries.append(("GPS", GPSTAGS.get(tag, str(tag)), _describe(value)))
        for key, value in image.info.items():
            if key in ("exif", "icc_profile"):
                entries.append((L("Main"), key, fmt("{0} bytes", len(value))))
            elif key == "xmp" or key == "XML:com.adobe.xmp":
                entries.append(("XMP", key, fmt("{0} bytes", len(value) if hasattr(value, "__len__") else 0)))
            elif key not in ("dpi", "jfif", "jfif_version", "jfif_unit", "jfif_density", "progressive", "progression",
                             "adobe", "adobe_transform", "compression", "transparency", "gamma", "photoshop"):
                entries.append((L("Main"), str(key), _describe(value)))
        if "dpi" in image.info:
            entries.append((L("Main"), "dpi", _describe(image.info["dpi"])))
        entries.append((L("Main"), "Size", f"{image.width} × {image.height}"))
        text = {f: str(exif.get(f.value, "")).strip("\x00") for f in MetadataField}
        raw_date = sub.get(0x9003) or exif.get(0x0132)
        taken = None
        if raw_date:
            try:
                taken = datetime.strptime(str(raw_date).strip("\x00"), _DATE_FORMAT)
            except ValueError:
                taken = None
        location = None
        lat = _degrees(gps.get(2), gps.get(1)) if gps else None
        lon = _degrees(gps.get(4), gps.get(3)) if gps else None
        if lat is not None and lon is not None:
            location = (lat, lon)
        entries.sort(key=lambda e: (e[0], e[1]))
        return MetadataInfo(entries, text, taken, location)


# MARK: Writing


def apply(path: str, changes: MetadataChanges) -> str:
    """Writes `<name> (metadata).<ext>` next to the original with the changes applied."""
    fmt_ = detect(path)
    if fmt_ is None or fmt_.category.value != "image":
        raise ValueError(L("This file has no editable metadata."))
    if fmt_ not in SUPPORTED:
        raise ValueError(fmt("Metadata in {0} files cannot be edited.", fmt_.display_name))
    full = os.path.abspath(path)

    def produce(output: str) -> None:
        if fmt_ is FileFormat.JPG:
            with open(full, "rb") as stream:
                data = stream.read()
            with open(output, "wb") as out:
                out.write(_edit_jpeg(data, changes))
        else:
            _resave(full, output, fmt_, changes)

    return output_naming.write_atomically(os.path.dirname(full), f"{output_naming.base_name(full)} ({L('metadata')})",
                                          fmt_.extension, produce)


def _changed_exif(exif: Image.Exif, changes: MetadataChanges, orientation: int | None = None) -> Image.Exif:
    if changes.remove_all:
        fresh = Image.Exif()
        if orientation and orientation != 1:
            fresh[0x0112] = orientation
        return fresh
    for field_, value in changes.text.items():
        if value:
            exif[field_.value] = value
        elif field_.value in exif:
            del exif[field_.value]
    if changes.date_taken is not None:
        raw = changes.date_taken.strftime(_DATE_FORMAT)
        sub = exif.get_ifd(_EXIF_IFD)
        sub[0x9003] = raw
        sub[0x9004] = raw
        exif[0x0132] = raw
    if changes.remove_location:
        if _GPS_IFD in exif:
            del exif[_GPS_IFD]
    return exif


def _strip_xmp_location(xmp: bytes) -> bytes:
    text = xmp.decode("utf-8", "replace")
    text = re.sub(r'\s+exif:GPS\w+="[^"]*"', "", text)
    text = re.sub(r"<exif:GPS\w+>.*?</exif:GPS\w+>", "", text, flags=re.S)
    return text.encode("utf-8")


def _edit_jpeg(data: bytes, changes: MetadataChanges) -> bytes:
    """Replaces the EXIF segment and drops or edits the others; the compressed image data is copied as it is."""
    if data[:2] != b"\xff\xd8":
        raise ValueError(L("This is not a JPEG file."))
    segments: list[tuple[int, bytes]] = []  # (marker, payload incl. length) before the scan
    position = 2
    exif = Image.Exif()
    exif_loaded = False
    while position + 4 <= len(data):
        if data[position] != 0xFF:
            break
        marker = data[position + 1]
        if marker == 0xDA:  # start of scan: the rest is image data
            break
        if marker in (0x01, *range(0xD0, 0xD9)):
            position += 2
            continue
        length = struct.unpack(">H", data[position + 2:position + 4])[0]
        payload = data[position + 4:position + 2 + length]
        if marker == 0xE1 and payload.startswith(b"Exif\x00\x00") and not exif_loaded:
            exif.load(b"Exif\x00\x00" + payload[6:]) if False else exif.load(payload[6:])
            exif_loaded = True
        else:
            segments.append((marker, data[position + 2:position + 2 + length]))
        position += 2 + length
    scan = data[position:]
    original_orientation = exif.get(0x0112, 1) if exif_loaded else 1
    new_exif = _changed_exif(exif, changes, original_orientation)

    kept: list[bytes] = []
    for marker, block in segments:
        payload = block[2:]
        if marker == 0xE1:  # XMP, or another EXIF
            if changes.remove_all:
                continue
            if payload.startswith(b"http://ns.adobe.com/xap/1.0/\x00") and changes.remove_location:
                header = b"http://ns.adobe.com/xap/1.0/\x00"
                body = _strip_xmp_location(payload[len(header):])
                block = struct.pack(">H", len(header) + len(body) + 2) + header + body
        elif marker == 0xED or marker == 0xFE:  # Photoshop IRB (IPTC), comments
            if changes.remove_all:
                continue
        elif 0xE3 <= marker <= 0xEF and marker != 0xEE and changes.remove_all:
            continue
        kept.append(bytes([0xFF, marker]) + block)

    exif_bytes = new_exif.tobytes() if len(new_exif) or exif_loaded else b""
    out = [b"\xff\xd8"]
    inserted = False
    for segment in kept:
        out.append(segment)
        # EXIF goes right after the JFIF header, as cameras write it.
        if not inserted and segment[1] == 0xE0:
            out.append(_exif_segment(exif_bytes))
            inserted = True
    if not inserted:
        out.insert(1, _exif_segment(exif_bytes))
    out.append(scan)
    return b"".join(out)


def _exif_segment(exif_bytes: bytes) -> bytes:
    if not exif_bytes:
        return b""
    body = exif_bytes if exif_bytes.startswith(b"Exif\x00\x00") else b"Exif\x00\x00" + exif_bytes
    if len(body) + 2 > 0xFFFF:
        raise ValueError("The metadata is too large for a JPEG file.")
    return b"\xff\xe1" + struct.pack(">H", len(body) + 2) + body


def _resave(source: str, output: str, fmt_: FileFormat, changes: MetadataChanges) -> None:
    """PNG and TIFF: the pixels are re-saved without loss."""
    with Image.open(source) as image:
        image.load()
        exif = image.getexif()
        original_orientation = exif.get(0x0112, 1)
        new_exif = _changed_exif(exif, changes, original_orientation)
        keywords: dict = {}
        icc = image.info.get("icc_profile")
        if icc:
            keywords["icc_profile"] = icc
        if "dpi" in image.info:
            keywords["dpi"] = image.info["dpi"]
        if fmt_ is FileFormat.PNG:
            if len(new_exif):
                keywords["exif"] = new_exif.tobytes()
            if not changes.remove_all:
                from PIL.PngImagePlugin import PngInfo

                info = PngInfo()
                for key, value in image.text.items() if hasattr(image, "text") else []:
                    info.add_text(key, value)
                keywords["pnginfo"] = info
            image.save(output, "PNG", **keywords)
        else:
            if len(new_exif):
                keywords["exif"] = new_exif
            image.save(output, "TIFF", compression="tiff_lzw" if image.mode != "1" else "group4", **keywords)


__all__ = ["read", "apply", "MetadataChanges", "MetadataField", "MetadataInfo", "io"]
