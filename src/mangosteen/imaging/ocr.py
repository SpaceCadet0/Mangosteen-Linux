"""Recognising text in photos and scanned PDFs with Tesseract, on the device."""

from __future__ import annotations

import os
import tempfile
import time
from collections.abc import Callable

from PIL import Image

from ..convert import images, pdf
from ..core import capabilities, external, output_naming
from ..core.cancellation import Cancelled, CancellationToken
from ..core.file_format import FileFormat, detect
from ..core.loc import L, fmt
from .redact import available_ocr_languages

# How long one picture or PDF page may take.
TIME_LIMIT = 60.0


class NoText(Exception):
    def __init__(self, name: str) -> None:
        super().__init__(fmt("No text was found in “{0}”.", name))


class TimedOut(Exception):
    def __init__(self, name: str | None = None) -> None:
        super().__init__(fmt("Could not recognise the text in “{0}” in a minute; recognition was stopped.", name)
                         if name else L("Could not recognise the text in a minute; recognition was stopped."))


def accepts(path: str) -> bool:
    fmt_ = detect(path)
    return fmt_ is not None and (fmt_.is_raster_image or fmt_ is FileFormat.PDF)


def recognize(image: Image.Image, languages: list[str] | None = None, time_limit: float = TIME_LIMIT,
              cancellation: CancellationToken | None = None) -> str:
    """The text of one image, line by line in reading order."""
    if not capabilities.has_tesseract():
        raise external.ToolMissing("tesseract")
    languages = languages if languages is not None else available_ocr_languages()
    with tempfile.TemporaryDirectory(prefix="mangosteen-") as folder:
        path = os.path.join(folder, "page.png")
        image.convert("RGB").save(path)
        arguments = [path, "stdout", "--psm", "3"]
        if languages:
            arguments += ["-l", "+".join(languages)]
        import subprocess

        process = subprocess.Popen([external.locate("tesseract") or "tesseract", *arguments], stdout=subprocess.PIPE,
                                   stderr=subprocess.PIPE, stdin=subprocess.DEVNULL)
        if cancellation is not None:
            cancellation.on_cancel(lambda: process.poll() is None and process.kill())
        deadline = time.monotonic() + time_limit
        while True:
            try:
                out, err = process.communicate(timeout=0.2)
                break
            except subprocess.TimeoutExpired:
                if cancellation is not None and cancellation.is_cancelled:
                    process.kill()
                    process.communicate()
                    raise Cancelled() from None
                if time.monotonic() >= deadline:
                    process.kill()
                    process.communicate()
                    raise TimedOut() from None
        if process.returncode != 0:
            raise external.ToolFailure("tesseract", process.returncode, err.decode("utf-8", "replace")[-400:])
    return out.decode("utf-8", "replace").strip()


def recognize_file(path: str, progress: Callable[[float], None] | None = None,
                   cancellation: CancellationToken | None = None) -> str:
    """Writes `<name> (text).txt` next to the original. PDF pages are rendered at 300 dpi and separated by a page
    break."""
    name = os.path.basename(path)
    try:
        if detect(path) is FileFormat.PDF:
            count = pdf.page_count(path)
            pages = []
            for index in range(count):
                if cancellation is not None:
                    cancellation.throw_if_cancelled()
                pages.append(recognize(pdf.render_page(path, index, 300), cancellation=cancellation))
                if progress:
                    progress((index + 1) / max(count, 1))
            text = "\n\f\n".join(pages)
        else:
            text = recognize(images.load(path)[0], cancellation=cancellation)
            if progress:
                progress(1.0)
    except TimedOut as error:
        raise TimedOut(name) from error
    if not text.replace("\f", "").strip():
        raise NoText(name)

    def produce(output: str) -> None:
        with open(output, "w", encoding="utf-8") as stream:
            stream.write(text + "\n")

    return output_naming.write_atomically(os.path.dirname(os.path.abspath(path)),
                                          f"{output_naming.base_name(path)} ({L('text')})", "txt", produce)
