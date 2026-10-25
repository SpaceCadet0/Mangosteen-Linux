"""The recent results shown in the tray menu: the newest first, `KEPT` kept on disk, `SHOWN` shown. An entry whose
files are all gone (deleted, moved) disappears."""

from __future__ import annotations

import json
import os
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass, field

from . import log

KEPT = 20
SHOWN = 10


@dataclass
class ResultEntry:
    title: str
    time: float
    outputs: list[str] = field(default_factory=list)


class ResultHistory:
    def __init__(self, file: str | os.PathLike[str]) -> None:
        self.file = os.fspath(file)
        self.entries: list[ResultEntry] = []

    @classmethod
    def load(cls, file: str | os.PathLike[str]) -> ResultHistory:
        history = cls(file)
        try:
            with open(history.file, encoding="utf-8") as stream:
                history.entries = [ResultEntry(**entry) for entry in json.load(stream)]
        except (OSError, ValueError, TypeError):
            history.entries = []
        return history

    def add(self, title: str, outputs: list[str], when: float | None = None) -> None:
        outputs = list(outputs)
        if not outputs:
            return
        self.entries.insert(0, ResultEntry(title, when if when is not None else time.time(), outputs))
        del self.entries[KEPT:]
        self._save()

    def live(self, exists: Callable[[str], bool] | None = None) -> list[ResultEntry]:
        """The entries to show, with only the outputs that still exist; entries with none left are dropped."""
        exists = exists or os.path.lexists
        live = [ResultEntry(e.title, e.time, [o for o in e.outputs if exists(o)]) for e in self.entries]
        live = [e for e in live if e.outputs]
        if len(live) != len(self.entries) or any(len(a.outputs) != len(b.outputs) for a, b in zip(live, self.entries)):
            self.entries = live
            self._save()
        return live[:SHOWN]

    def remove(self, entry: ResultEntry) -> None:
        self.entries = [e for e in self.entries if not (e.time == entry.time and e.title == entry.title)]
        self._save()

    def clear(self) -> None:
        self.entries = []
        self._save()

    def _save(self) -> None:
        try:
            os.makedirs(os.path.dirname(os.path.abspath(self.file)), exist_ok=True)
            with open(self.file, "w", encoding="utf-8") as stream:
                json.dump([asdict(e) for e in self.entries], stream, indent=2, ensure_ascii=False)
        except OSError as error:
            log.error("history", error)
