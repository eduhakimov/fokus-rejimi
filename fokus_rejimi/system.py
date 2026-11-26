"""Small system helpers: safe mode, autostart (opt-in), paths."""
import os
import sys
from pathlib import Path
from typing import Callable, Optional

RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
RUN_NAME = "FokusRejimi"


def safe_mode() -> bool:
    """True while testing, taking screenshots or self-testing.

    In safe mode the app never writes the hosts file, never acts on real processes and
    keeps its data in a temporary folder.
    """
    if os.environ.get("PYTEST_CURRENT_TEST") or os.environ.get("FOKUS_SAFE") == "1":
        return True
    return any(a in sys.argv for a in ("--screenshot", "--selftest"))


def build_run_command(exe: Optional[str] = None, frozen: Optional[bool] = None,
                      script: Optional[str] = None) -> str:
    """Command line stored in HKCU\\...\\Run. Starts minimized to the tray."""
    frozen = getattr(sys, "frozen", False) if frozen is None else frozen
    exe = exe or sys.executable
    if frozen:
        return f'"{exe}" --tray'
    pyw = exe
    if exe.lower().endswith("python.exe"):
        cand = exe[:-len("python.exe")] + "pythonw.exe"
        if os.path.exists(cand):
            pyw = cand
    script = script or str(Path(sys.argv[0]).resolve())
    return f'"{pyw}" "{script}" --tray'


def _reg_writer(name: str, value: Optional[str]):
    import winreg
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as k:
        if value is None:
            try:
                winreg.DeleteValue(k, name)
            except FileNotFoundError:
                pass
        else:
            winreg.SetValueEx(k, name, 0, winreg.REG_SZ, value)


def _reg_reader(name: str) -> Optional[str]:
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as k:
            return winreg.QueryValueEx(k, name)[0]
    except OSError:
        return None


def set_autostart(enabled: bool, writer: Callable = _reg_writer, command: Optional[str] = None):
    writer(RUN_NAME, (command or build_run_command()) if enabled else None)


def autostart_enabled(reader: Callable = _reg_reader) -> bool:
    return bool(reader(RUN_NAME))
