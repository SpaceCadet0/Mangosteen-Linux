"""Where Mangosteen keeps its settings, history and log (XDG base directories)."""

from __future__ import annotations

import os
from pathlib import Path


def _xdg(variable: str, fallback: str) -> Path:
    value = os.environ.get(variable)
    return Path(value) if value and os.path.isabs(value) else Path.home() / fallback


def _override() -> Path | None:
    """MANGOSTEEN_HOME puts everything in one folder; the tests and portable installs use it."""
    value = os.environ.get("MANGOSTEEN_HOME")
    return Path(value) if value else None


def config_dir() -> Path:
    return _override() or _xdg("XDG_CONFIG_HOME", ".config") / "mangosteen"


def data_dir() -> Path:
    return _override() or _xdg("XDG_DATA_HOME", ".local/share") / "mangosteen"


def state_dir() -> Path:
    return _override() or _xdg("XDG_STATE_HOME", ".local/state") / "mangosteen"


def cache_dir() -> Path:
    return _override() or _xdg("XDG_CACHE_HOME", ".cache") / "mangosteen"


def log_file() -> Path:
    return state_dir() / "mangosteen.log"


def settings_file() -> Path:
    return config_dir() / "settings.json"


def history_file() -> Path:
    return state_dir() / "history.json"


def autostart_file() -> Path:
    return _xdg("XDG_CONFIG_HOME", ".config") / "autostart" / "mangosteen.desktop"
