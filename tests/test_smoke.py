"""Smoke tests: the window builds in every language and timer actions stay in safe mode."""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def _setup():
    from PySide6.QtWidgets import QApplication
    from uzkit import app as appmod
    from uzkit.settings import Settings
    appmod.META = appmod.load_meta()
    appmod.SETTINGS = Settings(appmod.META["slug"] + "_test")
    return QApplication.instance() or QApplication([])


def test_window_creates():
    _setup()
    from uzkit import i18n
    from fokus_rejimi.window import MainWindow
    for lang in ("uz", "ru", "en"):
        i18n.set_language(lang)
        w = MainWindow()
        w.close()
    i18n.set_language("uz")


def test_translations_complete():
    from uzkit import i18n
    import fokus_rejimi.window  # noqa: registers strings
    assert i18n.missing_keys() == {}


def test_window_actions_safe():
    """Timer actions in the window never touch real hosts or processes (safe mode)."""
    qapp = _setup()
    from fokus_rejimi.blocker import DryRunExecutor
    from fokus_rejimi.hosts import DryRunHosts
    from fokus_rejimi.window import MainWindow
    w = MainWindow()
    assert isinstance(w.hosts, DryRunHosts) and isinstance(w.blocker.executor, DryRunExecutor)
    w.cfg.data["block_sites"] = True
    w.toggle_timer()
    assert w.timer.state == "running" and w.hosts.is_blocked()
    w.toggle_timer()
    w.skip_phase()
    assert w.timer.phase != "focus" and not w.hosts.is_blocked()
    w.stop_timer()
    for i in range(4):
        w.set_page(i)
        qapp.processEvents()
    w.page_block.add_names(["explorer.exe", "Game"])
    assert "game.exe" in [r["name"] for r in w.cfg["apps"]]
    assert "explorer.exe" not in [r["name"] for r in w.cfg["apps"]]
    w.close()
