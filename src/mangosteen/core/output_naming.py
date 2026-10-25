"""Chooses where results go: next to the original, never overwriting anything."""

from __future__ import annotations

import os
import shutil
import uuid
from collections.abc import Callable


def _candidate(directory: str, base_name: str, extension: str, index: int) -> str:
    name = base_name if index == 1 else f"{base_name} {index}"
    return os.path.join(directory, f"{name}.{extension}" if extension else name)


def unique_path(directory: str, base_name: str, extension: str,
                exists: Callable[[str], bool] | None = None) -> str:
    """`photo.png`, or `photo 2.png`, `photo 3.png`… when taken."""
    exists = exists or os.path.lexists
    index = 1
    while exists(_candidate(directory, base_name, extension, index)):
        index += 1
    return _candidate(directory, base_name, extension, index)


def part_number(index: int, count: int) -> str:
    """1-based number of a part, zero-padded to the width of `count` so parts sort in order: "03" of 12."""
    number = str(index + 1)
    return number.rjust(len(str(count)), "0")


def base_name(path: str) -> str:
    name = os.path.basename(os.fspath(path).rstrip("/\\"))
    lower = name.lower()
    for double in (".tar.gz", ".tar.bz2", ".tar.xz"):
        if lower.endswith(double):
            return name[: -len(double)]
    stem, _ = os.path.splitext(name)
    return stem or name


def write_atomically(directory: str, name: str, extension: str, produce: Callable[[str], None]) -> str:
    """Runs `produce` against a hidden temporary file in `directory`, then moves the result to a unique
    final name. `produce` may create a file or a folder at the temporary path. Nothing is left behind
    if it raises."""
    temp = os.path.join(directory, f".mangosteen-{uuid.uuid4().hex}" + (f".{extension}" if extension else ""))
    try:
        produce(temp)
        is_folder = os.path.isdir(temp)
        if not is_folder and not os.path.isfile(temp):
            raise OSError("The converter produced no file.")
        # Another job may claim the same name between choosing and moving; retry with the next one.
        for _ in range(20):
            final = unique_path(directory, name, extension)
            try:
                if is_folder:
                    if os.path.lexists(final):
                        continue
                    os.rename(temp, final)
                else:
                    # Hard-link then unlink fails if the name was taken in the meantime; rename would overwrite.
                    os.link(temp, final)
                    os.unlink(temp)
                return final
            except FileExistsError:
                continue
            except OSError:
                if os.path.lexists(final):
                    continue
                if not is_folder:
                    # A file system without hard links: fall back to a plain move.
                    shutil.move(temp, final)
                    return final
                raise
        raise OSError(f"Could not find a free name for {name}.{extension}")
    finally:
        if os.path.isdir(temp) and not os.path.islink(temp):
            shutil.rmtree(temp, ignore_errors=True)
        elif os.path.lexists(temp):
            try:
                os.unlink(temp)
            except OSError:
                pass
