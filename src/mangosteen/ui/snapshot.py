"""Renders windows to images: `mangosteen --snapshot <what> <output.png> <files…>`.

`what` is `wheel:convert`, `wheel:tools`, `wheel:actions`, `settings`, `welcome`, `about`, `float`, or the id of a tool
window (for example `tool.crop`). Used to check layouts and to make the pictures in the README."""

from __future__ import annotations

import os
import sys

from ..core import settings as settings_module
from ..core import wheel_catalog
from ..core.wheel_catalog import WheelKind
from ..imaging.redact import RedactionStyle


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
    height = os.environ.get("MANGOSTEEN_SNAPSHOT_HEIGHT")
    if height:  # the README shows some windows side by side at one height
        widget.resize(widget.width(), max(int(height), widget.minimumSizeHint().height()))
    _settle(qapp, widget)
    if os.environ.get("MANGOSTEEN_SNAPSHOT_DEMO") and _demo(what, widget):
        _settle(qapp, widget, 1.2)
    widget.grab().save(output)
    print(output)
    teardown.delete_windows(qapp)
    return 0


def _demo(what: str, widget) -> bool:  # noqa: ANN001
    """For the README pictures: puts a tool in the middle of its work (a few marks, a hidden area, a selected stretch),
    as if someone were using it. Positions suit the sample photos in docs/samples. True when something was done."""
    from ..imaging.annotations import Annotation
    from ..imaging.geometry import UnitRect

    if what == "tool.annotate":
        canvas = widget.canvas
        width, height = canvas.full_size
        canvas.annotations += [
            Annotation("rectangle", rect=(width * 0.6, height * 0.38, width * 0.24, height * 0.37), line_width=8),
            Annotation("arrow", start=(width * 0.34, height * 0.82), end=(width * 0.57, height * 0.64), line_width=9),
            Annotation("number", start=(width * 0.6, height * 0.38), number=1, font_size=44),
        ]
        canvas.update()
        return True
    if what == "tool.redact":
        widget._canvas.regions.append(UnitRect(0.02, 0.03, 0.22, 0.35))  # noqa: SLF001
        widget._render()  # noqa: SLF001
        return True
    duration = getattr(getattr(widget, "_pane", None), "timeline", None)
    duration = duration.duration if duration is not None else 0.0
    if what == "tool.trimMedia" and duration:
        widget._pane.timeline.set_selection(duration * 0.2, duration * 0.72, emit=True)  # noqa: SLF001
        widget._pane.seek(duration * 0.45)  # noqa: SLF001
        return True
    if what == "tool.bleep" and duration:
        widget._pane.seek(duration * 0.42)  # noqa: SLF001
        widget._add()  # noqa: SLF001
        return True
    if what == "tool.redactVideo" and duration:
        widget._pane.seek(duration * 0.3)  # noqa: SLF001
        widget._add_region(UnitRect(0.6, 0.36, 0.25, 0.42))  # noqa: SLF001
        widget._style_control.set_value(RedactionStyle.PIXELATE)  # noqa: SLF001
        widget._style_changed(RedactionStyle.PIXELATE)  # noqa: SLF001
        return True
    return False


def _settle(qapp, widget, at_least: float = 0.6) -> None:  # noqa: ANN001
    """Waits (up to 20 s) for a tool's live preview to be drawn, and at least a moment for layouts."""
    import time

    from PySide6.QtCore import QCoreApplication

    started = time.monotonic()
    while True:
        QCoreApplication.processEvents()
        waited = time.monotonic() - started
        if getattr(widget, "is_settled", True) and waited > at_least:
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
