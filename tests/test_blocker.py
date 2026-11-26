import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import psutil
import pytest

from fokus_rejimi.blocker import (ACTION_CLOSE, ACTION_MINIMIZE, Blocker, DryRunExecutor, ProcInfo, RealExecutor,
                                  is_protected, normalize_name, user_app_names)

ME = "PC\\me"


class Clock:
    t = 0.0

    def __call__(self):
        return self.t


def test_normalize():
    assert normalize_name(" Steam ") == "steam.exe"
    assert normalize_name(r"C:\Games\Foo.EXE") == "foo.exe"
    assert is_protected("explorer") and is_protected("svchost.exe")


def test_warn_then_close_after_deadline():
    procs = [ProcInfo(10, "steam.exe", ME), ProcInfo(11, "notepad.exe", ME), ProcInfo(12, "Steam.exe", "OTHER\\x")]
    ex, clk = DryRunExecutor(), Clock()
    b = Blocker(lambda: procs, ex, user=ME, warn_seconds=10, clock=clk, own_pid=1)
    b.set_rules([{"name": "steam.exe", "enabled": True, "action": ACTION_CLOSE}])
    r = b.tick()
    assert [w.name for w in r["new"]] == ["steam.exe"] and ex.log == []
    clk.t = 5
    assert b.tick()["executed"] == []
    clk.t = 10.5
    r = b.tick()
    assert ex.log == [("close", [10])]          # the other user's process is untouched
    assert r["executed"][0].name == "steam.exe"


def test_warning_dropped_when_user_closes_app():
    procs = [ProcInfo(10, "discord.exe", ME)]
    ex, clk = DryRunExecutor(), Clock()
    b = Blocker(lambda: procs, ex, user=ME, warn_seconds=10, clock=clk, own_pid=1)
    b.set_rules([{"name": "discord.exe"}])
    b.tick()
    procs.clear()
    clk.t = 20
    assert b.tick()["executed"] == [] and ex.log == []


def test_deny_list_and_disabled_rules_ignored():
    procs = [ProcInfo(5, "explorer.exe", ME), ProcInfo(6, "telegram.exe", ME)]
    ex = DryRunExecutor()
    b = Blocker(lambda: procs, ex, user=ME, warn_seconds=0, own_pid=1)
    b.set_rules([{"name": "explorer.exe"}, {"name": "telegram.exe", "enabled": False}])
    assert b.rules == {}
    b.tick()
    b.tick()
    assert ex.log == []


def test_own_pid_and_unknown_owner_skipped():
    procs = [ProcInfo(1, "game.exe", ME), ProcInfo(2, "game.exe", None)]
    ex = DryRunExecutor()
    b = Blocker(lambda: procs, ex, user=ME, warn_seconds=0, own_pid=1)
    b.set_rules([{"name": "game.exe"}])
    assert b.matches() == {}


def test_minimize_rule_reminimizes_without_new_warning():
    procs = [ProcInfo(20, "telegram.exe", ME)]
    ex, clk = DryRunExecutor(), Clock()
    b = Blocker(lambda: procs, ex, user=ME, warn_seconds=3, clock=clk, own_pid=1)
    b.set_rules([{"name": "telegram.exe", "action": ACTION_MINIMIZE}])
    b.tick()
    clk.t = 4
    b.tick()
    assert ex.log == [("minimize", [20])]
    r = b.tick()
    assert r["new"] == [] and ex.log[-1] == ("minimize", [20])


def test_user_app_names_filters():
    procs = [ProcInfo(1, "Steam.exe", ME), ProcInfo(2, "svchost.exe", ME), ProcInfo(3, "x.exe", "B\\b"),
             ProcInfo(4, "System", None)]
    assert user_app_names(lambda: procs, user=ME) == ["steam.exe"]


def _dummy_exe() -> Path:
    """A copy of the Python interpreter named dummygame.exe in %TEMP%\\fokus_test."""
    d = Path(tempfile.gettempdir()) / "fokus_test"
    d.mkdir(exist_ok=True)
    exe = d / "dummygame.exe"
    if not exe.exists():
        shutil.copy2(Path(sys.base_prefix) / "python.exe", exe)
        for src in {Path(sys.executable).parent, Path(sys.base_prefix)}:
            for f in src.glob("*.dll"):
                if not (d / f.name).exists():
                    shutil.copy2(f, d / f.name)
    return exe


def test_real_executor_closes_own_dummy_process():
    """Only a process spawned by this test is ever closed."""
    exe = _dummy_exe()
    env = dict(os.environ)
    env["PYTHONHOME"] = sys.base_prefix
    proc = subprocess.Popen([str(exe), "-c", "import time; time.sleep(60)"], env=env,
                            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    try:
        time.sleep(1.0)
        if proc.poll() is not None:
            pytest.skip("dummy process did not start")
        me = psutil.Process().username()

        def lister():
            out = []
            for p in psutil.process_iter(["name", "username"]):
                if (p.info.get("name") or "").lower() == "dummygame.exe" and p.pid == proc.pid:
                    out.append(ProcInfo(p.pid, p.info["name"], p.info.get("username")))
            return out

        b = Blocker(lister, RealExecutor(timeout=3, background=False), user=me, warn_seconds=0.3)
        b.set_rules([{"name": "dummygame.exe", "action": ACTION_CLOSE}])
        r = b.tick()
        assert r["new"] and r["new"][0].pids == [proc.pid]
        assert proc.poll() is None              # nothing happens before the warning ends
        time.sleep(0.4)
        r = b.tick()
        assert r["executed"] and r["executed"][0].ok
        proc.wait(timeout=5)
        assert proc.poll() is not None
    finally:
        if proc.poll() is None:
            proc.kill()
