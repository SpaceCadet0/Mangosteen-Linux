"""Small questions about the X11 session."""

from __future__ import annotations

import functools
import os


def is_x11_session() -> bool:
    return bool(os.environ.get("DISPLAY"))


@functools.lru_cache(maxsize=1)
def has_compositor() -> bool:
    """Translucent windows (the wheel's soft shadow) need a compositing manager; without one the wheel is drawn
    opaque inside a round mask."""
    if os.environ.get("MANGOSTEEN_NO_COMPOSITOR"):
        return False
    from PySide6.QtGui import QGuiApplication

    if QGuiApplication.platformName() in ("offscreen", "wayland", "minimal"):
        return True
    if not is_x11_session():
        return True
    try:
        from Xlib import display

        connection = display.Display()
        try:
            owner = connection.get_selection_owner(connection.intern_atom(f"_NET_WM_CM_S{connection.get_default_screen()}"))
            return owner != 0
        finally:
            connection.close()
    except Exception:  # noqa: BLE001 - when in doubt, assume a compositor
        return True
