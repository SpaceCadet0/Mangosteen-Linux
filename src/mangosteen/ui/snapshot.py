"""Renders windows to images: `mangosteen --snapshot <what> <output.png> <files…>`.

`what` is `wheel:convert`, `wheel:tools`, `wheel:actions`, `settings`, `welcome`, `about`, `float`, or the id of a tool
window (for example `tool.crop`). Used to check layouts and to make the pictures in the README."""

from __future__ import annotations

import sys

from ..core import settings as settings_module
from ..core import wheel_catalog
from ..core.wheel_catalog import WheelKind


def run(qapp, what: str, output: str, files: list[str]) -> int:  # noqa: ANN001
    from ..core import loc
    from . import brand, teardown

    loc.set_language(settings_module.Settings.load().effective_language)
    brand.apply_palette(qapp)
    widget = build(qapp, what, files)
    if widget is None:
        print(f"mangosteen: nothing to show for “{what}”", file=sys.stderr)
        return 2
    widget.show()
    _settle(qapp, widget)
    widget.grab().save(output)
    print(output)
    teardown.delete_windows(qapp)
    return 0


def _settle(qapp, widget) -> None:  # noqa: ANN001
    """Waits (up to 20 s) for a tool's live preview to be drawn, and at least a moment for layouts."""
    import time

    from PySide6.QtCore import QCoreApplication

    started = time.monotonic()
    while True:
        QCoreApplication.processEvents()
        waited = time.monotonic() - started
        if getattr(widget, "is_settled", True) and waited > 0.6:
            break
        if waited > 20:
            break
        time.sleep(0.02)


def build(qapp, what: str, files: list[str]):  # noqa: ANN001, ANN201
    from .about import AboutWindow
    from .float_shelf import FloatShelf
    from .settings_window import SettingsWindow
    from .welcome import WelcomeWindow
    from .wheel import WheelWidget

    if what.startswith("wheel:"):
        kind = WheelKind(what.split(":", 1)[1])
        wheel = WheelWidget()
        items = wheel_catalog.items(kind, files)
        wheel.configure(kind, items, len(files))
        if items:
            wheel.highlight_for_test(0)
        return wheel
    if what == "settings":
        return SettingsWindow(settings_module.Settings(), drag_available=True)
    if what == "welcome":
        return WelcomeWindow({k: settings_module.Settings().modifier_for(k) for k in WheelKind}, True)
    if what == "about":
        return AboutWindow()
    if what == "float":
        shelf = FloatShelf()
        shelf.add(files)
        return shelf
    from .tools import registry

    class _Context:  # a stand-in for the application: tools only need its settings and a way to run jobs
        settings = settings_module.Settings()

    return registry.create(what, files, _Context())
