"""Website blocking through the Windows hosts file.

The block lives between two marker lines, so removing it never touches anything else in
the file. The path is always passed in: tests work on temporary copies, the app passes the
real path only when the user has turned website blocking on.
"""
import logging
import os
import re
import shutil
import tempfile
import time
from pathlib import Path
from typing import Callable, Iterable, List, Optional

_log = logging.getLogger("hosts")

MARK_START = "# >>> FokusRejimi start"
MARK_END = "# <<< FokusRejimi end"
SYSTEM_HOSTS = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32" / "drivers" / "etc" / "hosts"

DEFAULT_SITES = ["youtube.com", "instagram.com", "tiktok.com", "facebook.com", "x.com", "reddit.com"]

_DOMAIN_RE = re.compile(r"^(?=.{1,253}$)([a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}$")


def normalize_domain(text: str) -> Optional[str]:
    """'https://www.YouTube.com/watch?v=1' -> 'youtube.com'. None if it is not a domain."""
    d = (text or "").strip().lower()
    d = re.sub(r"^[a-z]+://", "", d)
    d = d.split("/")[0].split("?")[0].split("#")[0].split(":")[0].strip(".")
    if d.startswith("www."):
        d = d[4:]
    try:
        d = d.encode("idna").decode("ascii")
    except Exception:
        return None
    return d if _DOMAIN_RE.match(d) else None


def expand(domains: Iterable[str]) -> List[str]:
    out = []
    for raw in domains:
        d = normalize_domain(raw)
        if not d:
            continue
        for host in (d, "www." + d):
            if host not in out:
                out.append(host)
    return out


def build_block(domains: Iterable[str], nl: str = "\r\n") -> str:
    hosts = expand(domains)
    lines = [MARK_START] + [f"0.0.0.0 {h}" for h in hosts] + [MARK_END]
    return nl.join(lines) + nl


def has_block(text: str) -> bool:
    return MARK_START in text


def strip_block(text: str) -> str:
    """Remove every marker block (also an unfinished one at the end of the file)."""
    out, inside = [], False
    for line in text.splitlines(keepends=True):
        s = line.strip()
        if s == MARK_START:
            inside = True
            continue
        if inside:
            if s == MARK_END:
                inside = False
            continue
        out.append(line)
    res = "".join(out)
    return res


def _detect_newline(text: str) -> str:
    return "\r\n" if "\r\n" in text or not text else "\n"


def add_block(text: str, domains: Iterable[str]) -> str:
    base = strip_block(text)
    nl = _detect_newline(text)
    if base and not base.endswith(("\n", "\r")):
        base += nl
    return base + build_block(domains, nl)


def _flush_dns():
    try:
        from uzkit.widgets import run_hidden
        run_hidden(["ipconfig", "/flushdns"], timeout=15)
    except Exception as ex:  # noqa
        _log.warning("flushdns failed: %s", ex)


class HostsManager:
    def __init__(self, path: Path, backup_dir: Path, flush: Callable[[], None] = _flush_dns):
        self.path = Path(path)
        self.backup_dir = Path(backup_dir)
        self.flush = flush

    def read(self) -> str:
        data = self.path.read_bytes()
        for enc in ("utf-8-sig", "cp1252", "latin-1"):
            try:
                return data.decode(enc)
            except UnicodeDecodeError:
                continue
        return data.decode("latin-1", errors="replace")

    def _write(self, text: str):
        # write next to the file and replace, so a crash never leaves a half-written hosts file
        tmp_fd, tmp = tempfile.mkstemp(dir=str(self.path.parent), prefix="hosts.", suffix=".tmp")
        try:
            with os.fdopen(tmp_fd, "wb") as f:
                f.write(text.encode("utf-8"))
            os.replace(tmp, self.path)
        except Exception:
            try:
                os.remove(tmp)
            except OSError:
                pass
            # some security tools lock replace on hosts; fall back to in-place write
            with open(self.path, "wb") as f:
                f.write(text.encode("utf-8"))

    def is_blocked(self) -> bool:
        try:
            return has_block(self.read())
        except OSError:
            return False

    def backup(self) -> Path:
        self.backup_dir.mkdir(parents=True, exist_ok=True)
        dst = self.backup_dir / f"hosts.{time.strftime('%Y%m%d-%H%M%S')}.bak"
        shutil.copy2(self.path, dst)
        baks = sorted(self.backup_dir.glob("hosts.*.bak"))
        for old in baks[:-10]:
            try:
                old.unlink()
            except OSError:
                pass
        return dst

    def apply(self, domains: Iterable[str]) -> int:
        """Write the block. Returns the number of host names blocked."""
        hosts = expand(domains)
        if not hosts:
            return 0
        text = self.read()
        if not has_block(text):
            self.backup()
        self._write(add_block(text, domains))
        self.flush()
        return len(hosts)

    def remove(self) -> bool:
        """Remove the block if present. Returns True when the file was changed."""
        try:
            text = self.read()
        except OSError:
            return False
        if not has_block(text):
            return False
        self._write(strip_block(text))
        self.flush()
        return True


class DryRunHosts:
    """Stand-in used in tests, screenshots and when site blocking is off."""

    def __init__(self):
        self.log: List[tuple] = []
        self.blocked = False

    def is_blocked(self) -> bool:
        return self.blocked

    def apply(self, domains: Iterable[str]) -> int:
        hosts = expand(domains)
        self.log.append(("apply", hosts))
        self.blocked = bool(hosts)
        return len(hosts)

    def remove(self) -> bool:
        was = self.blocked
        self.log.append(("remove",))
        self.blocked = False
        return was
