"""End-to-end focus session against a TEMP copy of the hosts file and a dummy process this test starts.

Nothing here touches the real hosts file or any process the test did not spawn.
"""
import os
import shutil
import stat
import subprocess
import sys
import time
from pathlib import Path

import psutil
import pytest

from fokus_rejimi.blocker import ACTION_CLOSE, Blocker, ProcInfo, RealExecutor
from fokus_rejimi.hosts import SYSTEM_HOSTS, HostsManager, has_block

ORIGINALS = {
    "no_final_newline": b"# hosts\r\n127.0.0.1 localhost",
    "lf_only": b"127.0.0.1 localhost\n::1 localhost\n",
    "bom_utf8": b"\xef\xbb\xbf# Copyright (c) Microsoft Corp.\r\n127.0.0.1 localhost\r\n",
    "cp1251_comment": "# хосты\r\n127.0.0.1 localhost\r\n".encode("cp1251"),
    "empty": b"",
}


@pytest.mark.parametrize("name", list(ORIGINALS))
def test_apply_remove_gives_original_bytes_back(tmp_path, name):
    p = tmp_path / "hosts"
    p.write_bytes(ORIGINALS[name])
    m = HostsManager(p, tmp_path / "bak", flush=lambda: None)
    assert m.apply(["youtube.com"]) == 2
    assert has_block(m.read())
    m.apply(["youtube.com", "reddit.com"])          # applying again replaces the block
    assert m.read().count("FokusRejimi start") == 1
    assert m.remove()
    assert p.read_bytes() == ORIGINALS[name]


def test_copy_of_real_hosts_roundtrip(tmp_path):
    if not SYSTEM_HOSTS.exists():
        pytest.skip("no hosts file")
    p = tmp_path / "hosts"
    shutil.copyfile(SYSTEM_HOSTS, p)              # read only: the real file is never written
    original = p.read_bytes()
    m = HostsManager(p, tmp_path / "bak", flush=lambda: None)
    m.apply(["instagram.com", "https://www.tiktok.com/@x"])
    assert b"0.0.0.0 www.tiktok.com" in p.read_bytes()
    m.remove()
    assert p.read_bytes() == original


def test_read_only_hosts_copy_fails_cleanly(tmp_path):
    p = tmp_path / "hosts"
    p.write_bytes(b"127.0.0.1 localhost\r\n")
    os.chmod(p, stat.S_IREAD)
    try:
        m = HostsManager(p, tmp_path / "bak", flush=lambda: None)
        with pytest.raises(OSError):
            m.apply(["youtube.com"])
        assert p.read_bytes() == b"127.0.0.1 localhost\r\n"
        assert not list(tmp_path.glob("hosts.*.tmp"))
    finally:
        os.chmod(p, stat.S_IWRITE | stat.S_IREAD)


def _window():
    from PySide6.QtWidgets import QApplication
    from uzkit import app as appmod
    from uzkit.settings import Settings
    appmod.META = appmod.load_meta()
    appmod.SETTINGS = Settings(appmod.META["slug"] + "_test")
    QApplication.instance() or QApplication([])
    from fokus_rejimi.window import MainWindow
    return MainWindow()


def test_focus_session_blocks_sites_and_closes_dummy_app(tmp_path):
    from test_blocker import _dummy_exe
    w = _window()
    hosts = tmp_path / "hosts"
    hosts.write_bytes(b"127.0.0.1 localhost\r\n")
    w.hosts = HostsManager(hosts, tmp_path / "bak", flush=lambda: None)
    exe = _dummy_exe()
    env = dict(os.environ, PYTHONHOME=sys.base_prefix)
    proc = subprocess.Popen([str(exe), "-c", "import time; time.sleep(60)"], env=env,
                            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    try:
        time.sleep(1.0)
        if proc.poll() is not None:
            pytest.skip("dummy process did not start")

        def lister():                                  # only the dummy this test started is visible
            try:
                p = psutil.Process(proc.pid)
                return [ProcInfo(p.pid, p.name(), p.username())]
            except psutil.NoSuchProcess:
                return []

        w.blocker = Blocker(lister, RealExecutor(timeout=3, background=False), user=psutil.Process().username(),
                            warn_seconds=0.3)
        w.cfg.data.update(block_sites=True, block_apps=True, sites=["youtube.com"],
                          apps=[{"name": "dummygame.exe", "enabled": True, "action": ACTION_CLOSE}])
        w.protection_changed()
        w.blocker.warn_seconds = 0.3                       # instead of the 10 s from the settings
        w.toggle_timer()
        assert b"0.0.0.0 www.youtube.com" in hosts.read_bytes()
        w._scan_apps(time.time())
        assert w.blocker.pending and proc.poll() is None   # a warning first, nothing closed yet
        time.sleep(0.4)
        w._scan_apps(time.time())
        proc.wait(timeout=5)
        assert w.blocker.history and w.blocker.history[-1].ok
        w.stop_timer()
        assert hosts.read_bytes() == b"127.0.0.1 localhost\r\n"
    finally:
        if proc.poll() is None:
            proc.kill()
        w.close()


def test_file_exit_action_quits():
    w = _window()
    w.show()
    exit_act = [a for a in w.menu_file.actions() if a.shortcut().toString() == "Ctrl+Q"][0]
    exit_act.trigger()
    assert w._quitting and not w.isVisible()
