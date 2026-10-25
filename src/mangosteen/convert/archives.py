"""ZIP, TAR and TAR.GZ: files and folders into archives, archives into each other, and extraction."""

from __future__ import annotations

import os
import shutil
import stat
import tarfile
import tempfile
import zipfile

from ..core import loc, output_naming
from ..core.file_format import Category, FileFormat, detect

# The largest unpacked size of one part of a document package, and of all parts together.
MAX_PART_BYTES = 256 << 20
MAX_TOTAL_BYTES = 1 << 30


def _entry_names(items: list[str]) -> list[str]:
    """Each item keeps its name as a top-level entry ("photo 2.jpg" when two items share a name)."""
    used: set[str] = set()
    names = []
    for item in items:
        name = os.path.basename(item.rstrip("/\\"))
        stem, extension = (name, "") if os.path.isdir(item) else os.path.splitext(name)
        index = 2
        candidate = name
        while candidate.lower() in used:
            candidate = f"{stem} {index}{extension}"
            index += 1
        used.add(candidate.lower())
        names.append(candidate)
    return names


def pack(items: list[str], target: FileFormat, output: str) -> None:
    """Archives files and folders into `output`."""
    if not items:
        raise ValueError("Nothing to archive.")
    names = _entry_names(items)
    if target is FileFormat.ZIP:
        with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED, allowZip64=True) as archive:
            for item, name in zip(items, names):
                _add_to_zip(archive, item, name)
    elif target in (FileFormat.TAR, FileFormat.TGZ):
        mode = "w:gz" if target is FileFormat.TGZ else "w"
        with tarfile.open(output, mode, format=tarfile.PAX_FORMAT) as archive:  # type: ignore[call-overload]
            for item, name in zip(items, names):
                archive.add(item, arcname=name, recursive=True)
    else:
        raise ValueError(f"{target.display_name} is not an archive format.")


def _add_to_zip(archive: zipfile.ZipFile, path: str, name: str) -> None:
    if os.path.isdir(path):
        entries = sorted(os.listdir(path))
        if not entries:
            archive.writestr(name + "/", b"")
        for entry in entries:
            _add_to_zip(archive, os.path.join(path, entry), f"{name}/{entry}")
    else:
        archive.write(path, name)


def add_to_archive(paths: list[str]) -> str:
    """"Archive": the selected files and folders go into one ZIP next to the first of them, named after the folder
    they share ("Photos.zip", or "Photos 2.zip" when that is taken), or after the item when there is only one."""
    first = os.path.abspath(paths[0].rstrip("/\\"))
    return output_naming.write_atomically(
        os.path.dirname(first) or first, bundle_name(paths), "zip", lambda out: pack(paths, FileFormat.ZIP, out))


def bundle_name(paths: list[str]) -> str:
    """The item's own name when there is one, else the name of the deepest folder all the items are in, or
    "Archive" when they only share the root."""
    if len(paths) == 1:
        return output_naming.base_name(paths[0].rstrip("/\\"))
    parents = [os.path.dirname(os.path.abspath(p.rstrip("/\\"))) for p in paths]
    try:
        common = os.path.commonpath(parents)
    except ValueError:
        common = ""
    name = os.path.basename(common.rstrip("/\\"))
    return name or "Archive"


def repack(archive: str, source: FileFormat, target: FileFormat, output: str) -> None:
    """Unpacks an archive and packs its contents again in another format."""
    workspace = tempfile.mkdtemp(prefix="mangosteen-")
    try:
        extract(archive, source, workspace)
        items = [os.path.join(workspace, n) for n in sorted(os.listdir(workspace)) if n != "__MACOSX"]
        if not items:
            raise ValueError(f"{os.path.basename(archive)} is empty.")
        pack(items, target, output)
    finally:
        shutil.rmtree(workspace, ignore_errors=True)


def extract_next_to_archive(archive: str, on_progress=None) -> str:  # noqa: ANN001
    """Extracts into a new folder named after the archive, next to it. Returns the folder."""
    fmt = detect(archive)
    if fmt is None or fmt.category is not Category.ARCHIVE:
        raise ValueError(f"{os.path.basename(archive)} is not an archive.")
    directory = os.path.dirname(os.path.abspath(archive))
    return output_naming.write_atomically(directory, output_naming.base_name(archive), "",
                                          lambda folder: extract(archive, fmt, folder))


def _safe_target(folder: str, name: str) -> str | None:
    """Where an entry goes inside `folder`, or None when its name would escape it (zip slip) or is junk."""
    name = name.replace("\\", "/")
    parts = [p for p in name.split("/") if p not in ("", ".")]
    if not parts or ".." in parts or name.startswith("/") or (len(parts[0]) == 2 and parts[0][1] == ":"):
        return None
    if parts[0] == "__MACOSX":
        return None
    target = os.path.join(folder, *parts)
    root = os.path.realpath(folder)
    if os.path.commonpath([root, os.path.realpath(target)]) != root:
        return None
    return target


def _legacy_zip_encoding() -> str:
    """The code page Windows Explorer used for ZIP names without the UTF-8 flag (866 on Russian Windows)."""
    return "cp866" if loc.system_language() == "ru" else "cp437"


def _zip_name(info: zipfile.ZipInfo, legacy: str) -> str:
    if info.flag_bits & 0x800:
        return info.filename
    raw = info.filename.encode("cp437", "replace")
    try:
        return raw.decode("utf-8")  # many tools write UTF-8 without setting the flag
    except UnicodeDecodeError:
        pass
    try:
        return raw.decode(legacy)
    except UnicodeDecodeError:
        return info.filename


def extract(archive: str, fmt: FileFormat, folder: str) -> None:
    os.makedirs(folder, exist_ok=True)
    if fmt is FileFormat.ZIP:
        _extract_zip(archive, folder)
    elif fmt in (FileFormat.TAR, FileFormat.TGZ):
        _extract_tar(archive, folder)
    else:
        raise ValueError(f"{fmt.display_name} is not an archive format.")


def _extract_zip(archive: str, folder: str) -> None:
    legacy = _legacy_zip_encoding()
    with zipfile.ZipFile(archive) as zf:
        for info in zf.infolist():
            name = _zip_name(info, legacy)
            target = _safe_target(folder, name)
            if target is None:
                continue
            if info.is_dir() or name.endswith("/"):
                os.makedirs(target, exist_ok=True)
                continue
            mode = (info.external_attr >> 16) & 0xFFFF
            if mode and stat.S_ISLNK(mode):
                continue  # symbolic links are not recreated
            os.makedirs(os.path.dirname(target), exist_ok=True)
            with zf.open(info) as source, open(target, "wb") as out:
                shutil.copyfileobj(source, out)
            if mode & 0o111:
                os.chmod(target, 0o755)


def _extract_tar(archive: str, folder: str) -> None:
    with tarfile.open(archive, "r:*") as tf:
        for member in tf:
            target = _safe_target(folder, member.name)
            if target is None:
                continue
            if member.isdir():
                os.makedirs(target, exist_ok=True)
            elif member.isfile():
                os.makedirs(os.path.dirname(target), exist_ok=True)
                source = tf.extractfile(member)
                if source is None:
                    continue
                with source, open(target, "wb") as out:
                    shutil.copyfileobj(source, out)
                if member.mode & 0o111:
                    os.chmod(target, 0o755)
            # links, devices and fifos are skipped on purpose


def check_unpacked_size(path: str, *skipped: str) -> None:
    """Refuses an Office or OpenDocument file (a ZIP package) whose parts unpack to more than the limits, before
    anything is inflated, so a crafted file cannot fill the memory. Parts that are never read (pictures, thumbnails)
    are named in `skipped` and do not count."""
    total = 0
    with zipfile.ZipFile(path) as zf:
        for info in zf.infolist():
            if any(info.filename.lower().startswith(prefix.lower()) for prefix in skipped):
                continue
            total += info.file_size
            if info.file_size > MAX_PART_BYTES or total > MAX_TOTAL_BYTES:
                raise ValueError(
                    f"{os.path.basename(path)} is too large to read: {info.filename} unpacks to "
                    f"{info.file_size // (1 << 20)} MB.")
