import wave

import numpy as np

from fokus_rejimi import system
from fokus_rejimi.config import DEFAULTS, Config
from fokus_rejimi.sounds import CHIMES, chime, ensure_sounds


def test_chime_shape(tmp_path):
    x = chime(CHIMES["focus_end"])
    assert x.ndim == 1 and np.max(np.abs(x)) <= 0.71 and abs(x[0]) < 0.01 and abs(x[-1]) < 0.01
    files = ensure_sounds(tmp_path)
    assert set(files) == set(CHIMES)
    with wave.open(str(files["break_end"])) as w:
        assert w.getframerate() == 44100 and w.getnchannels() == 2 and w.getnframes() > 44100


def test_autostart_uses_injected_writer():
    calls = []
    cmd = system.build_run_command(exe=r"C:\Apps\FokusRejimi.exe", frozen=True)
    assert cmd == '"C:\\Apps\\FokusRejimi.exe" --tray'
    system.set_autostart(True, writer=lambda n, v: calls.append((n, v)), command=cmd)
    system.set_autostart(False, writer=lambda n, v: calls.append((n, v)))
    assert calls == [("FokusRejimi", cmd), ("FokusRejimi", None)]
    assert system.autostart_enabled(reader=lambda n: None) is False
    assert "--tray" in system.build_run_command(exe=r"C:\py\python.exe", frozen=False, script=r"C:\x\main.py")


def test_safe_mode_in_tests():
    assert system.safe_mode()


class FakeSettings:
    def __init__(self, data):
        self.data = data
        self.saved = None

    def get(self, k, d=None):
        return self.data.get(k, d)

    def set(self, k, v):
        self.saved = (k, v)


def test_config_validates_types():
    s = FakeSettings({"fokus": {"focus_min": "abc", "short_min": 7, "strict": 1, "sites": ["a.com"], "junk": 1}})
    c = Config(s)
    assert c["focus_min"] == DEFAULTS["focus_min"] and c["short_min"] == 7
    assert c["strict"] is False and c["sites"] == ["a.com"] and "junk" not in c.data
    c.set("long_min", 20)
    assert s.saved[1]["long_min"] == 20
    tc = c.timer_config()
    assert tc.short_min == 7 and tc.long_min == 20
    c2 = Config(s, persist=False)
    s.saved = None
    c2.set("long_min", 30)
    assert s.saved is None


def test_phrase_match():
    from fokus_rejimi.pages import PhraseDialog
    assert PhraseDialog.matches("  i choose  to give up this SESSION ", "I choose to give up this session")
    assert not PhraseDialog.matches("I choose", "I choose to give up this session")
    assert not PhraseDialog.matches("", "")
