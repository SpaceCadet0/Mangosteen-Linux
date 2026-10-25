"""The two small sounds: a muted click when the pointer moves onto a segment and a soft two-note chime when a job is
done. They are synthesised once into the cache folder and played with Qt's sound effect."""

from __future__ import annotations

import math
import struct
import wave
from collections.abc import Callable

from ..core import log, paths

_RATE = 44_100


def _hover(t: float) -> float:
    # A short, muted click like pressing a trackpad: a soft low thump with a faint tick on top.
    thump = math.sin(2 * math.pi * 180 * t) * math.exp(-t * 320)
    tick = math.sin(2 * math.pi * 2600 * t) * math.exp(-t * 2200) * 0.35
    return (thump + tick) * 0.5


def _done(t: float) -> float:
    # A soft, low two-note chime (C5 then G5) with gentle attack and quick decay.
    def note(frequency: float, start: float, decay: float) -> float:
        local = t - start
        if local < 0:
            return 0.0
        attack = min(1.0, local / 0.006)
        return attack * math.exp(-local * decay) * (math.sin(2 * math.pi * frequency * local)
                                                    + 0.18 * math.sin(4 * math.pi * frequency * local))

    fade_out = min(1.0, (0.5 - t) / 0.03)
    return (note(523.25, 0, 13) + note(783.99, 0.085, 11)) * 0.32 * fade_out


def synthesize(path: str, duration: float, sample: Callable[[float], float]) -> None:
    count = int(_RATE * duration)
    with wave.open(path, "wb") as out:
        out.setnchannels(1)
        out.setsampwidth(2)
        out.setframerate(_RATE)
        out.writeframes(b"".join(struct.pack("<h", int(max(-1.0, min(1.0, sample(i / _RATE))) * 32767))
                                 for i in range(count)))


class Sounds:
    def __init__(self) -> None:
        self._effects: dict[str, object] = {}

    def _effect(self, name: str):  # noqa: ANN202
        if name in self._effects:
            return self._effects[name]
        effect = None
        try:
            from PySide6.QtCore import QUrl
            from PySide6.QtMultimedia import QSoundEffect

            folder = paths.cache_dir()
            folder.mkdir(parents=True, exist_ok=True)
            file = folder / f"{name}.wav"
            if not file.exists():
                if name == "hover":
                    synthesize(str(file), 0.022, _hover)
                else:
                    synthesize(str(file), 0.5, _done)
            effect = QSoundEffect()
            effect.setSource(QUrl.fromLocalFile(str(file)))
            effect.setVolume(0.45 if name == "hover" else 0.5)
        except Exception as error:  # noqa: BLE001 - no sound is not a problem
            log.write(f"sound unavailable: {error}")
        self._effects[name] = effect
        return effect

    def play(self, name: str) -> None:
        effect = self._effect(name)
        if effect is not None:
            effect.play()
