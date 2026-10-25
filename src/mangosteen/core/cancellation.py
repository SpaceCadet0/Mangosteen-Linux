"""Shared between a running job and the UI that can stop it. Thread-safe."""

from __future__ import annotations

import threading
from collections.abc import Callable


class Cancelled(Exception):
    """Raised inside a job when the user pressed Stop."""


class CancellationToken:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._event = threading.Event()
        self._handlers: list[Callable[[], None]] = []

    @property
    def is_cancelled(self) -> bool:
        return self._event.is_set()

    def cancel(self) -> None:
        with self._lock:
            if self._event.is_set():
                return
            self._event.set()
            handlers, self._handlers = self._handlers, []
        for handler in handlers:
            handler()

    def on_cancel(self, handler: Callable[[], None]) -> None:
        """Runs `handler` on cancellation, or immediately if already cancelled."""
        with self._lock:
            if not self._event.is_set():
                self._handlers.append(handler)
                return
        handler()

    def throw_if_cancelled(self) -> None:
        if self._event.is_set():
            raise Cancelled()
