"""The file formats Mangosteen recognises. Detection is by name, as in the other Mangosteen apps."""

from __future__ import annotations

import os
from enum import Enum


class Category(Enum):
    IMAGE = "image"
    PDF = "pdf"
    DOCUMENT = "document"
    SUBTITLE = "subtitle"
    TABLE = "table"
    ARCHIVE = "archive"
    VIDEO = "video"
    AUDIO = "audio"

    @property
    def is_media(self) -> bool:
        return self in (Category.VIDEO, Category.AUDIO)


class FileFormat(Enum):
    # Images (read and write)
    JPG = "jpg"
    PNG = "png"
    WEBP = "webp"
    HEIC = "heic"
    TIFF = "tiff"
    AVIF = "avif"
    BMP = "bmp"
    GIF = "gif"
    # Images (read only)
    SVG = "svg"
    ICO = "ico"
    ICNS = "icns"
    PSD = "psd"
    JP2 = "jp2"
    TGA = "tga"
    EXR = "exr"
    PDF = "pdf"
    # Documents
    DOCX = "docx"
    DOC = "doc"
    ODT = "odt"
    RTF = "rtf"
    TXT = "txt"
    MD = "md"
    HTML = "html"
    # Subtitles
    SRT = "srt"
    VTT = "vtt"
    # Tables
    CSV = "csv"
    TSV = "tsv"
    XLSX = "xlsx"
    # Archives
    ZIP = "zip"
    TAR = "tar"
    TGZ = "tgz"
    # Video (m4v is read only)
    MP4 = "mp4"
    MOV = "mov"
    MKV = "mkv"
    WEBM = "webm"
    AVI = "avi"
    WMV = "wmv"
    M4V = "m4v"
    # Audio (aac is read only)
    MP3 = "mp3"
    M4A = "m4a"
    WAV = "wav"
    FLAC = "flac"
    OGG = "ogg"
    OPUS = "opus"
    AIFF = "aiff"
    WMA = "wma"
    AAC = "aac"

    @property
    def extension(self) -> str:
        return "tar.gz" if self is FileFormat.TGZ else self.value

    @property
    def display_name(self) -> str:
        return _DISPLAY_NAMES.get(self, self.value.upper())

    @property
    def category(self) -> Category:
        return _CATEGORIES.get(self, Category.IMAGE)

    @property
    def supports_alpha(self) -> bool:
        """Whether the encoded file can carry transparency. Opaque formats get a white background."""
        return self not in (FileFormat.JPG, FileFormat.BMP)

    @property
    def is_lossy(self) -> bool:
        return self in (FileFormat.JPG, FileFormat.HEIC, FileFormat.AVIF, FileFormat.WEBP)

    @property
    def is_raster_image(self) -> bool:
        return self.category is Category.IMAGE and self is not FileFormat.SVG


F = FileFormat

_DISPLAY_NAMES = {
    F.JPG: "JPG",
    F.WEBP: "WebP",
    F.JP2: "JPEG 2000",
    F.MD: "Markdown",
    F.TGZ: "TAR.GZ",
    F.WEBM: "WebM",
    F.OPUS: "Opus",
}

_CATEGORIES = {
    F.PDF: Category.PDF,
    **dict.fromkeys((F.DOCX, F.DOC, F.ODT, F.RTF, F.TXT, F.MD, F.HTML), Category.DOCUMENT),
    **dict.fromkeys((F.SRT, F.VTT), Category.SUBTITLE),
    **dict.fromkeys((F.CSV, F.TSV, F.XLSX), Category.TABLE),
    **dict.fromkeys((F.ZIP, F.TAR, F.TGZ), Category.ARCHIVE),
    **dict.fromkeys((F.MP4, F.MOV, F.MKV, F.WEBM, F.AVI, F.WMV, F.M4V), Category.VIDEO),
    **dict.fromkeys((F.MP3, F.M4A, F.WAV, F.FLAC, F.OGG, F.OPUS, F.AIFF, F.WMA, F.AAC), Category.AUDIO),
}

_ALIASES = {
    "jpeg": F.JPG, "jpe": F.JPG, "jfif": F.JPG,
    "tif": F.TIFF,
    "heif": F.HEIC, "hif": F.HEIC,
    "j2k": F.JP2, "jpf": F.JP2, "jpx": F.JP2,
    "dib": F.BMP,
    "markdown": F.MD, "mdown": F.MD, "text": F.TXT,
    "htm": F.HTML, "xhtml": F.HTML,
    "webvtt": F.VTT,
    "tab": F.TSV,
    "gz": F.TGZ,
    "qt": F.MOV, "mpeg4": F.MP4,
    "aif": F.AIFF, "aifc": F.AIFF, "oga": F.OGG, "wave": F.WAV,
}

_BY_EXTENSION = {f.value: f for f in FileFormat if f is not FileFormat.TGZ} | _ALIASES


def detect(path: str | os.PathLike[str]) -> FileFormat | None:
    """The format of a path, or None when the extension is unknown (folders included)."""
    name = os.path.basename(os.fspath(path).rstrip("/\\")).lower()
    if name.endswith(".tar.gz") or name.endswith(".tgz"):
        return FileFormat.TGZ
    _, dot, extension = name.rpartition(".")
    return _BY_EXTENSION.get(extension) if dot else None
