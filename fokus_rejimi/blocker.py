"""App blocking during focus sessions.

The Blocker decides; an executor acts. Both the process lister and the executor are
injectable, so the logic is tested without touching real processes.

Flow for a blocked app that appears during focus:
  1. scan() finds it -> a warning with a deadline (now + warn_seconds) is created
  2. the UI shows the warning overlay with a countdown
  3. after the deadline, if the process still runs -> executor closes or minimizes it
Only processes whose name is in the user's block list, owned by the current user and not
in the hard-coded deny list are ever touched.
"""
import logging
import os
import time
from dataclasses import dataclass, field
from typing import Callable, Dict, Iterable, List, Optional

_log = logging.getLogger("blocker")

ACTION_CLOSE = "close"
ACTION_MINIMIZE = "minimize"

# Never touched, whatever the block list says.
DENY = {
    "explorer.exe", "csrss.exe", "winlogon.exe", "wininit.exe", "services.exe", "svchost.exe", "lsass.exe",
    "lsaiso.exe", "smss.exe", "dwm.exe", "system", "system idle process", "registry", "memory compression",
    "fontdrvhost.exe", "sihost.exe", "ctfmon.exe", "taskhostw.exe", "taskmgr.exe", "conhost.exe",
    "runtimebroker.exe", "searchhost.exe", "startmenuexperiencehost.exe", "shellexperiencehost.exe",
    "textinputhost.exe", "securityhealthsystray.exe", "securityhealthservice.exe", "msmpeng.exe",
    "audiodg.exe", "spoolsv.exe", "dllhost.exe", "applicationframehost.exe", "lockapp.exe", "logonui.exe",
    "userinit.exe", "cmd.exe", "powershell.exe", "pwsh.exe", "windowsterminal.exe", "openconsole.exe",
    "python.exe", "pythonw.exe", "py.exe", "fokusrejimi.exe",
}

DEFAULT_RULES = [
    {"name": "steam.exe", "enabled": True, "action": ACTION_CLOSE},
    {"name": "discord.exe", "enabled": True, "action": ACTION_CLOSE},
    {"name": "epicgameslauncher.exe", "enabled": True, "action": ACTION_CLOSE},
    {"name": "telegram.exe", "enabled": False, "action": ACTION_MINIMIZE},
]


@dataclass
class ProcInfo:
    pid: int
    name: str
    username: Optional[str] = None


@dataclass
class Rule:
    name: str
    enabled: bool = True
    action: str = ACTION_CLOSE

    @staticmethod
    def from_dict(d: dict) -> "Rule":
        act = d.get("action", ACTION_CLOSE)
        return Rule(normalize_name(d.get("name", "")), bool(d.get("enabled", True)),
                    act if act in (ACTION_CLOSE, ACTION_MINIMIZE) else ACTION_CLOSE)


@dataclass
class Warning_:
    name: str
    action: str
    pids: List[int]
    deadline: float


@dataclass
class Executed:
    name: str
    action: str
    pids: List[int]
    ok: bool


def normalize_name(name: str) -> str:
    n = (name or "").strip().strip('"').lower()
    n = os.path.basename(n.replace("/", "\\"))
    if n and "." not in n:
        n += ".exe"
    return n


def is_protected(name: str) -> bool:
    return normalize_name(name) in DENY


# ---------------------------------------------------------------------- executors
class DryRunExecutor:
    """Records what would have happened. Used in tests, screenshots and the safe mode."""

    def __init__(self):
        self.log: List[tuple] = []

    def close(self, pids: List[int]) -> bool:
        self.log.append(("close", list(pids)))
        _log.info("dry-run close %s", pids)
        return True

    def minimize(self, pids: List[int]) -> bool:
        self.log.append(("minimize", list(pids)))
        _log.info("dry-run minimize %s", pids)
        return True


class RealExecutor:
    """Acts on real processes. The Blocker has already filtered the pids."""

    def __init__(self, timeout: float = 3.0, background: bool = True):
        self.timeout = timeout
        self.background = background   # wait/kill in a thread so the UI never freezes

    def close(self, pids: List[int]) -> bool:
        import psutil
        procs = []
        for pid in pids:
            try:
                p = psutil.Process(pid)
                p.terminate()
                procs.append(p)
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
        if not procs:
            return False

        def finish():
            try:
                _, alive = psutil.wait_procs(procs, timeout=self.timeout)
            except Exception:
                return
            for p in alive:
                try:
                    p.kill()
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    pass

        if self.background:
            import threading
            threading.Thread(target=finish, daemon=True).start()
        else:
            finish()
        return True

    def minimize(self, pids: List[int]) -> bool:
        try:
            import win32con
            import win32gui
            import win32process
        except ImportError:
            return False
        targets = set(pids)
        done = []

        def cb(hwnd, _):
            try:
                if not win32gui.IsWindowVisible(hwnd) or win32gui.IsIconic(hwnd):
                    return True
                if win32gui.GetWindow(hwnd, win32con.GW_OWNER):
                    return True
                _, pid = win32process.GetWindowThreadProcessId(hwnd)
                if pid in targets and win32gui.GetWindowText(hwnd):
                    win32gui.ShowWindow(hwnd, win32con.SW_MINIMIZE)
                    done.append(hwnd)
            except Exception:
                pass
            return True

        try:
            win32gui.EnumWindows(cb, None)
        except Exception:
            pass
        return bool(done)


# ---------------------------------------------------------------------- process listing
def current_username() -> Optional[str]:
    try:
        import psutil
        return psutil.Process().username()
    except Exception:
        return None


def list_processes() -> List[ProcInfo]:
    import psutil
    out = []
    for p in psutil.process_iter(["pid", "name", "username"]):
        try:
            info = p.info
            if info.get("name"):
                out.append(ProcInfo(info["pid"], info["name"], info.get("username")))
        except Exception:
            continue
    return out


def user_app_names(lister: Callable[[], List[ProcInfo]] = list_processes, user: Optional[str] = None) -> List[str]:
    """Process names that could reasonably be blocked (for the picker)."""
    user = user if user is not None else current_username()
    names = set()
    for p in lister():
        if not (p.name or "").lower().endswith(".exe") or not p.username:
            continue
        n = normalize_name(p.name)
        if n in DENY:
            continue
        if user and p.username.lower() != user.lower():
            continue
        names.add(n)
    return sorted(names)


# ---------------------------------------------------------------------- blocker
class Blocker:
    def __init__(self, lister: Callable[[], List[ProcInfo]], executor, user: Optional[str] = None,
                 warn_seconds: float = 10.0, clock: Callable[[], float] = time.time,
                 own_pid: Optional[int] = None):
        self.lister = lister
        self.executor = executor
        self.user = user
        self.warn_seconds = warn_seconds
        self.clock = clock
        self.own_pid = own_pid if own_pid is not None else os.getpid()
        self.rules: Dict[str, Rule] = {}
        self.pending: Dict[str, Warning_] = {}
        self.minimized: Dict[str, set] = {}      # name -> pids already handled by minimize
        self.history: List[Executed] = []

    def set_rules(self, rules: Iterable):
        self.rules = {}
        for r in rules:
            rule = r if isinstance(r, Rule) else Rule.from_dict(r)
            if rule.name and rule.enabled and not is_protected(rule.name):
                self.rules[rule.name] = rule

    def reset(self):
        self.pending.clear()
        self.minimized.clear()

    def matches(self) -> Dict[str, List[int]]:
        """Running processes that match an enabled rule, grouped by name."""
        found: Dict[str, List[int]] = {}
        if not self.rules:
            return found
        for p in self.lister():
            n = normalize_name(p.name)
            if n not in self.rules or n in DENY or p.pid == self.own_pid or p.pid in (0, 4):
                continue
            if self.user and p.username and p.username.lower() != self.user.lower():
                continue
            if self.user and not p.username:
                continue  # owner unknown (usually another user or a system process)
            found.setdefault(n, []).append(p.pid)
        return found

    def tick(self) -> dict:
        """Scan and act. Returns {'new': [Warning_], 'executed': [Executed], 'pending': [Warning_]}."""
        now = self.clock()
        found = self.matches()
        new, executed = [], []
        # forget warnings for apps that were closed by the user
        for name in list(self.pending):
            if name not in found:
                del self.pending[name]
        for name in list(self.minimized):
            if name not in found:
                del self.minimized[name]
        for name, pids in found.items():
            rule = self.rules[name]
            if rule.action == ACTION_MINIMIZE and name in self.minimized:
                fresh = [p for p in pids if p not in self.minimized[name]]
                # minimized apps that come back to the front are minimized again without a new warning
                again = [p for p in pids if p in self.minimized[name]]
                if again:
                    self.executor.minimize(again)
                if not fresh:
                    continue
                pids = fresh
            w = self.pending.get(name)
            if w is None:
                w = Warning_(name, rule.action, pids, now + self.warn_seconds)
                self.pending[name] = w
                new.append(w)
                continue
            w.pids = pids
            if now >= w.deadline:
                if rule.action == ACTION_CLOSE:
                    ok = self.executor.close(pids)
                else:
                    ok = self.executor.minimize(pids)
                    self.minimized.setdefault(name, set()).update(pids)
                ex = Executed(name, rule.action, list(pids), ok)
                executed.append(ex)
                self.history.append(ex)
                del self.pending[name]
        return {"new": new, "executed": executed, "pending": list(self.pending.values())}
