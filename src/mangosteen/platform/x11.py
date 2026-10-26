"""Small questions about the X11 session."""

from __future__ import annotations

import functools
import os


def is_x11_session() -> bool:
    """An X display is reachable (a real X11 session, or XWayland inside a Wayland one)."""
    return bool(os.environ.get("DISPLAY"))


def is_wayland_session() -> bool:
    return os.environ.get("XDG_SESSION_TYPE", "").lower() == "wayland" or bool(os.environ.get("WAYLAND_DISPLAY"))


def can_watch_drags() -> bool:
    """Drags can only be seen in a real X11 session. In a Wayland session the file manager is usually a native Wayland
    window whose drags no other program can see, and XWayland would only get in the way of them (a drag could be
    left hanging), so watching is off there. MANGOSTEEN_WATCH_DRAGS_ON_WAYLAND=1 forces it on, for file managers that
    run under XWayland."""
    if not is_x11_session():
        return False
    return not is_wayland_session() or bool(os.environ.get("MANGOSTEEN_WATCH_DRAGS_ON_WAYLAND"))


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
