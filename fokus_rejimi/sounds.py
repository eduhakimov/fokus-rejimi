"""Chime synthesis (numpy) and playback.

The chimes are soft bell-like tones: a few inharmonic partials with exponential decay and
a short attack, so they do not click. Files are generated once into the data folder.
"""
import logging
import wave
from pathlib import Path
from typing import Iterable, Tuple

import numpy as np

_log = logging.getLogger("sounds")
SR = 44100

# (start time s, base frequency Hz, gain)
CHIMES = {
    "focus_end": [(0.0, 659.25, 0.9), (0.22, 783.99, 0.8), (0.44, 1046.50, 0.75)],    # E5 G5 C6, rising
    "break_end": [(0.0, 880.00, 0.8), (0.25, 659.25, 0.85)],                         # A5 E5, two notes
    "warning": [(0.0, 523.25, 0.6), (0.18, 523.25, 0.6)],                            # C5 twice, short
}
# bell-like partials (ratio, relative amplitude, decay multiplier)
PARTIALS = [(1.0, 1.0, 1.0), (2.0, 0.45, 1.6), (3.01, 0.22, 2.3), (4.17, 0.10, 3.1), (5.43, 0.05, 4.0)]


def tone(freq: float, duration: float = 1.6, sr: int = SR, decay: float = 3.2) -> np.ndarray:
    t = np.arange(int(duration * sr)) / sr
    out = np.zeros_like(t)
    for ratio, amp, dmul in PARTIALS:
        out += amp * np.sin(2 * np.pi * freq * ratio * t) * np.exp(-decay * dmul * t)
    attack = np.minimum(1.0, t / 0.008)            # 8 ms fade-in removes clicks
    return out * attack


def chime(notes: Iterable[Tuple[float, float, float]], sr: int = SR, tail: float = 1.8) -> np.ndarray:
    notes = list(notes)
    total = max(s for s, _, _ in notes) + tail
    buf = np.zeros(int(total * sr))
    for start, freq, gain in notes:
        x = tone(freq, tail, sr) * gain
        i = int(start * sr)
        buf[i:i + len(x)] += x[:len(buf) - i]
    fade = np.minimum(1.0, (len(buf) - np.arange(len(buf))) / (0.05 * sr))   # soft end
    buf *= fade
    peak = np.max(np.abs(buf)) or 1.0
    return buf / peak * 0.7


def write_wav(path: Path, data: np.ndarray, sr: int = SR):
    pcm = (np.clip(data, -1, 1) * 32767).astype("<i2")
    stereo = np.repeat(pcm[:, None], 2, axis=1)
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes(stereo.tobytes())


def ensure_sounds(folder: Path) -> dict:
    out = {}
    for name, notes in CHIMES.items():
        p = Path(folder) / f"{name}.wav"
        if not p.exists() or p.stat().st_size < 1000:
            try:
                write_wav(p, chime(notes))
            except Exception as ex:  # noqa
                _log.warning("cannot write %s: %s", p, ex)
                continue
        out[name] = p
    return out


class Player:
    """QSoundEffect with a winsound fallback."""

    def __init__(self, files: dict):
        self.files = files
        self.volume = 0.7
        self.muted = False
        self._effects = {}
        try:
            from PySide6.QtCore import QUrl
            from PySide6.QtMultimedia import QSoundEffect
            for name, path in files.items():
                e = QSoundEffect()
                e.setSource(QUrl.fromLocalFile(str(path)))
                self._effects[name] = e
        except Exception as ex:  # noqa
            _log.info("QtMultimedia not available: %s", ex)

    def play(self, name: str):
        if self.muted or self.volume <= 0 or name not in self.files:
            return
        e = self._effects.get(name)
        if e is not None and e.status() != e.Status.Error:
            e.setVolume(float(self.volume))
            e.play()
            return
        try:
            import winsound
            winsound.PlaySound(str(self.files[name]), winsound.SND_FILENAME | winsound.SND_ASYNC)
        except Exception:
            pass
