"""A small log file: every wheel opened, every result and every error, for bug reports."""

from __future__ import annotations

import logging
import logging.handlers
import sys
import traceback

from . import paths

_logger = logging.getLogger("mangosteen")
_ready = False


def _setup() -> None:
    global _ready
    if _ready:
        return
    _ready = True
    _logger.setLevel(logging.INFO)
    _logger.propagate = False
    try:
        paths.state_dir().mkdir(parents=True, exist_ok=True)
        handler = logging.handlers.RotatingFileHandler(
            paths.log_file(), maxBytes=512_000, backupCount=1, encoding="utf-8"
        )
        handler.setFormatter(logging.Formatter("%(asctime)s %(message)s", "%Y-%m-%d %H:%M:%S"))
        _logger.addHandler(handler)
    except OSError:
        pass
    if sys.stderr is not None and sys.stderr.isatty():
        _logger.addHandler(logging.StreamHandler(sys.stderr))


def write(message: str) -> None:
    _setup()
    _logger.info(message)


def error(context: str, exc: BaseException) -> None:
    _setup()
    detail = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__)).rstrip()
    _logger.error("%s: %s\n%s", context, exc, detail)
