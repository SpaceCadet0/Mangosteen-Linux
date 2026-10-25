"""Runs file jobs off the UI thread, with the progress panel for anything that takes longer than a moment, a Stop
button, and one notification at the end."""

from __future__ import annotations

import os
import threading
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor

from PySide6.QtCore import QObject, QTimer, Signal

from ..core import log
from ..core.cancellation import Cancelled, CancellationToken
from ..core.loc import L, count, fmt
from .progress_hud import ProgressHud

HUD_DELAY_MS = 400

# work(input, token, progress) -> the new file or folder, or None when there was nothing to do
Work = Callable[[str, CancellationToken, Callable[[float], None]], "str | None"]


class _Run(QObject):
    """One job's state, living in the UI thread; worker threads talk to it only through signals."""

    progressed = Signal(int, int, str, float)
    finished = Signal(list, list, int, bool)


class Jobs(QObject):
    # Emitted in the UI thread: title, outputs, failure messages, stopped note (or "")
    reported = Signal(str, list, list, str)

    def __init__(self, notify: Callable[..., None], record: Callable[[str, list[str]], None],
                 on_done: Callable[[list[str]], None] | None = None) -> None:
        super().__init__()
        self._notify = notify
        self._record = record
        self._on_done = on_done
        self._runs: list[_Run] = []

    def run_each(self, title: str, done_title: str, inputs: list[str], work: Work, max_concurrent: int = 1) -> None:
        """Applies `work` to each input."""
        token = CancellationToken()
        run = _Run()
        self._runs.append(run)
        state = {"finished": False}
        hud_holder: dict[str, ProgressHud | None] = {"hud": None}
        total = len(inputs)

        def show_hud() -> None:
            if state["finished"]:
                return
            hud = ProgressHud(title)
            hud.stop_requested.connect(token.cancel)
            hud.show_hud()
            hud_holder["hud"] = hud

        timer = QTimer(self)
        timer.setSingleShot(True)
        timer.timeout.connect(show_hud)
        timer.start(HUD_DELAY_MS)

        def on_progress(index: int, _total: int, name: str, fraction: float) -> None:
            hud = hud_holder["hud"]
            if hud is not None:
                hud.report(index, total, name, fraction)

        def on_finished(outputs: list, failures: list, done: int, stopped: bool) -> None:
            state["finished"] = True
            timer.stop()
            hud = hud_holder["hud"]
            if hud is not None:
                hud.close()
                hud.deleteLater()
            note = fmt("Stopped after {0} of {1}.", done, total) if stopped else ""
            self._report(done_title, outputs, failures, note)
            if run in self._runs:
                self._runs.remove(run)
            run.deleteLater()

        run.progressed.connect(on_progress)
        run.finished.connect(on_finished)

        def execute() -> None:
            outputs: list[str] = []
            failures: list[str] = []
            lock = threading.Lock()
            done = [0]

            def one(index: int, path: str) -> None:
                if token.is_cancelled:
                    return
                name = os.path.basename(path.rstrip("/\\")) or path
                run.progressed.emit(index, total, name, 0.0)
                started = time.monotonic()
                last = [0.0]

                def progress(fraction: float) -> None:
                    if fraction - last[0] < 0.01 and fraction < 1:
                        return  # a few updates a second are plenty
                    last[0] = fraction
                    run.progressed.emit(index, total, name, fraction)

                try:
                    output = work(path, token, progress)
                    if output:
                        with lock:
                            outputs.append(output)
                        log.write(f"{title}: {path} -> {output} in {int((time.monotonic() - started) * 1000)} ms")
                except Cancelled:
                    pass
                except Exception as error:  # noqa: BLE001 - every failure is shown, none is lost
                    from ..convert.converter import describe_error

                    with lock:
                        failures.append(describe_error(error, name))
                    log.error(f"{title}: {path}", error)
                finally:
                    with lock:
                        done[0] += 1

            workers = max(1, min(max_concurrent, total or 1))
            with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="mangosteen-job") as pool:
                for index, path in enumerate(inputs):
                    pool.submit(one, index, path)
            run.finished.emit(outputs, failures, done[0], token.is_cancelled)

        threading.Thread(target=execute, name="mangosteen-jobs", daemon=True).start()

    def run_once(self, title: str, done_title: str, label: str, work: Callable[[], str]) -> None:
        """One job that turns all inputs into a single result; `label` is shown while it runs."""
        self.run_each(title, done_title, [label], lambda _path, _token, _progress: work())

    def _report(self, done_title: str, outputs: list[str], failures: list[str], stopped_note: str) -> None:
        # Every tool and conversion reports here, so this is where "Recent Results" learns about new files.
        self._record(done_title, outputs)
        if outputs and self._on_done:
            self._on_done(outputs)
        if failures:
            total = len(failures) + len(outputs)
            title = fmt("{0}: failed", done_title) if total == 1 else fmt("{0} of {1} failed", len(failures), total)
            self._notify(title, "\n".join(failures[:3]), error=True)
        elif stopped_note:
            self._notify(fmt("{0}: stopped", done_title), stopped_note, reveal=outputs[-1] if outputs else None)
        elif not outputs:
            self._notify(done_title, L("Nothing to do: the files already have that format."))
        else:
            body = os.path.basename(outputs[0].rstrip("/\\")) if len(outputs) == 1 else count(len(outputs), "file")
            self._notify(done_title, body, reveal=outputs[-1])
        self.reported.emit(done_title, outputs, failures, stopped_note)

