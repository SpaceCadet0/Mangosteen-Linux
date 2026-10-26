"""Watches for file drags in other applications (X11) and reports modifier-key taps made while a drag is going on.

How it works without any special permission:

* A drag-and-drop between windows is announced by the source taking ownership of the `XdndSelection`. The XFixes
  extension tells us when that happens, so nothing is polled while no drag is going on (0 % CPU at rest).
* The dragged files are asked of the source the way a drop target does: a conversion of `XdndSelection` to
  `text/uri-list`. GTK sources answer anyone. Qt sources answer only the window under the pointer, so for those the
  list stays empty here and the wheel, being a drop target itself, receives it through the normal drag-and-drop
  protocol as soon as the pointer moves over it (`nudge` makes that happen at once).
* While the drag lasts, the pointer is queried a hundred times a second: its button mask says when the drag is
  over, and its modifier mask says which keys are held. A key pressed and released alone within 0.8 s is a "tap".

Wayland has no way to see a drag in another application; the wheel is then opened from the tray or a file manager."""

from __future__ import annotations

import select
import threading
import time
from urllib.parse import unquote, urlparse

from PySide6.QtCore import QObject, Signal

from ..core import log

# X11 modifier masks, as in the pointer query's state.
_MASKS = {"shift": 0x01, "ctrl": 0x04, "alt": 0x08, "super": 0x40}
_BUTTON1 = 0x100
_POLL_SECONDS = 1 / 60  # quick enough for a key tap, light enough for a Raspberry Pi
# A press longer than this is treated as a hold (a file manager's Shift-to-move), not a tap.
MAX_TAP_SECONDS = 0.8


def parse_uri_list(data: bytes | str) -> list[str]:
    """The local paths in a `text/uri-list` payload."""
    text = data.decode("utf-8", "replace") if isinstance(data, bytes) else data
    paths = []
    for line in text.replace("\r\n", "\n").split("\n"):
        line = line.strip().strip("\x00")
        if not line or line.startswith("#"):
            continue
        parsed = urlparse(line)
        if parsed.scheme == "file":
            paths.append(unquote(parsed.path))
    return paths


class TapTracker:
    """Turns a stream of modifier masks into taps: all modifiers released within `MAX_TAP_SECONDS` of the first
    press, with nothing else pressed in between, is a tap of the modifiers that were held."""

    def __init__(self, clock=time.monotonic) -> None:  # noqa: ANN001
        self._clock = clock
        self._last = 0
        self._pressed = 0
        self._start: float | None = None

    def reset(self, flags: int = 0) -> None:
        self._last, self._pressed, self._start = flags, 0, None

    def update(self, flags: int) -> int | None:
        """Feed the current modifier mask; returns the tapped mask when a tap just ended."""
        if flags == self._last:
            return None
        tapped = None
        if self._last == 0:
            self._pressed = flags
            self._start = self._clock()
        elif flags == 0:
            if self._start is not None and self._clock() - self._start <= MAX_TAP_SECONDS:
                tapped = self._pressed
            self._pressed, self._start = 0, None
        else:
            self._pressed |= flags
        self._last = flags
        return tapped


def modifier_name(mask: int) -> str | None:
    """"shift", "ctrl", "alt" or "super" when exactly that modifier was tapped."""
    for name, bit in _MASKS.items():
        if mask == bit:
            return name
    return None


class DragMonitor(QObject):
    drag_started = Signal(list)  # file paths
    modifier_tapped = Signal(str, list)  # modifier name, file paths
    drag_ended = Signal()

    def __init__(self) -> None:
        super().__init__()
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self.running = False

    def start(self) -> bool:
        """Starts watching; False when there is no X server or it lacks the XFixes extension."""
        if self._thread is not None:
            return self.running
        try:
            from Xlib import display

            connection = display.Display()
            if not connection.has_extension("XFIXES"):
                connection.close()
                log.write("drag monitor: no XFixes extension")
                return False
        except Exception as error:  # noqa: BLE001
            log.write(f"drag monitor: no X11 ({error})")
            return False
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, args=(connection,), name="mangosteen-drag", daemon=True)
        self.running = True
        self._thread.start()
        return True

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=2)
        self._thread = None
        self.running = False

    # MARK: The watching thread

    def _run(self, connection) -> None:  # noqa: ANN001
        from Xlib import X
        from Xlib.ext import xfixes

        try:
            root = connection.screen().root
            xdnd = connection.intern_atom("XdndSelection")
            uri_list = connection.intern_atom("text/uri-list")
            holder = connection.intern_atom("MANGOSTEEN_DND")
            requestor = root.create_window(0, 0, 1, 1, 0, connection.screen().root_depth,
                                           event_mask=X.PropertyChangeMask)
            connection.xfixes_query_version()
            connection.xfixes_select_selection_input(requestor, xdnd, xfixes.XFixesSetSelectionOwnerNotifyMask)
            connection.flush()
            while not self._stop.is_set():
                ready, _, _ = select.select([connection.fileno()], [], [], 0.5)
                if not ready and not connection.pending_events():
                    continue
                while connection.pending_events():
                    event = connection.next_event()
                    if getattr(event, "owner", None) and self._is_selection_notify(connection, event, xdnd):
                        self._drag(connection, root, requestor, xdnd, uri_list, holder)
        except Exception as error:  # noqa: BLE001 - the monitor must never take the app down
            log.error("drag monitor", error)
        finally:
            try:
                connection.close()
            except Exception:  # noqa: BLE001
                pass
            self.running = False

    @staticmethod
    def _is_selection_notify(connection, event, xdnd) -> bool:  # noqa: ANN001
        return getattr(event, "selection", None) == xdnd

    def _drag(self, connection, root, requestor, xdnd, uri_list, holder) -> None:  # noqa: ANN001
        """A drag may have started: if it carries files, follow it until the button is released."""
        pointer = root.query_pointer()
        if not pointer.mask & _BUTTON1:
            return  # a selection changed with no mouse drag behind it
        paths = self._request_files(connection, requestor, xdnd, uri_list, holder)
        log.write(f"drag started, {len(paths)} files known")
        self.drag_started.emit(paths)
        tracker = TapTracker()
        tracker.reset(pointer.mask & sum(_MASKS.values()))
        while not self._stop.is_set():
            state = root.query_pointer().mask
            if not state & _BUTTON1:
                break
            tapped = tracker.update(state & sum(_MASKS.values()))
            if tapped is not None and (name := modifier_name(tapped)):
                self.modifier_tapped.emit(name, paths)
            time.sleep(_POLL_SECONDS)
        self.drag_ended.emit()
        # Anything that queued up during the drag (selection notifications of the drop) is not a new drag.
        while connection.pending_events():
            connection.next_event()

    def _request_files(self, connection, requestor, xdnd, uri_list, holder) -> list[str]:  # noqa: ANN001
        """Asks the drag source for the file list, as a drop target would."""
        from Xlib import X

        requestor.delete_property(holder)
        requestor.convert_selection(xdnd, uri_list, holder, X.CurrentTime)
        connection.flush()
        deadline = time.monotonic() + 0.25
        while time.monotonic() < deadline:
            select.select([connection.fileno()], [], [], 0.05)
            while connection.pending_events():
                event = connection.next_event()
                if event.type == X.SelectionNotify:
                    if event.property == X.NONE:
                        return []
                    reply = requestor.get_full_property(holder, X.AnyPropertyType)
                    requestor.delete_property(holder)
                    connection.flush()
                    if reply is None or not reply.value:
                        return []
                    return parse_uri_list(bytes(reply.value))
        return []


def nudge() -> bool:
    """Moves the pointer one pixel and back with XTest, so a drag source that sends its position only on motion tells
    the window now under the pointer (the wheel) about the drag. Returns False without XTest."""
    try:
        from Xlib import X, display
        from Xlib.ext import xtest

        connection = display.Display()
        try:
            if not connection.has_extension("XTEST"):
                return False
            for delta in (1, -1):
                xtest.fake_input(connection, X.MotionNotify, 1, 0, X.NONE, delta, 0)
                connection.sync()
                time.sleep(0.012)
            return True
        finally:
            connection.close()
    except Exception as error:  # noqa: BLE001
        log.write(f"nudge failed: {error}")
        return False
