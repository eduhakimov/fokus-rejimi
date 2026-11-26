"""Session history in SQLite."""
import sqlite3
import threading
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional

SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    started TEXT NOT NULL,          -- ISO local time
    ended TEXT NOT NULL,
    day TEXT NOT NULL,              -- YYYY-MM-DD of the start
    phase TEXT NOT NULL,            -- focus | short | long
    planned_s REAL NOT NULL,
    actual_s REAL NOT NULL,
    completed INTEGER NOT NULL,
    task TEXT
);
CREATE INDEX IF NOT EXISTS ix_sessions_day ON sessions(day);
"""


class StatsDB:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self.con = sqlite3.connect(str(self.path), check_same_thread=False)
        self.con.executescript(SCHEMA)
        self.con.commit()

    def close(self):
        try:
            self.con.close()
        except Exception:
            pass

    def add(self, started: datetime, ended: datetime, phase: str, planned_s: float, actual_s: float,
            completed: bool, task: str = "") -> int:
        with self._lock:
            cur = self.con.execute(
                "INSERT INTO sessions(started, ended, day, phase, planned_s, actual_s, completed, task) "
                "VALUES (?,?,?,?,?,?,?,?)",
                (started.isoformat(timespec="seconds"), ended.isoformat(timespec="seconds"),
                 started.date().isoformat(), phase, float(planned_s), float(actual_s), int(bool(completed)),
                 (task or "").strip()[:200]))
            self.con.commit()
            return cur.lastrowid

    def clear(self):
        with self._lock:
            self.con.execute("DELETE FROM sessions")
            self.con.commit()

    # ------------------------------------------------------------------ queries
    def focus_minutes(self, day: date) -> float:
        r = self.con.execute("SELECT COALESCE(SUM(actual_s),0) FROM sessions WHERE phase='focus' AND day=?",
                             (day.isoformat(),)).fetchone()
        return r[0] / 60.0

    def day_summary(self, day: date) -> dict:
        r = self.con.execute(
            "SELECT COALESCE(SUM(actual_s),0), COALESCE(SUM(completed),0), COUNT(*)-COALESCE(SUM(completed),0) "
            "FROM sessions WHERE phase='focus' AND day=?", (day.isoformat(),)).fetchone()
        return {"minutes": r[0] / 60.0, "completed": int(r[1]), "interrupted": int(r[2])}

    def daily_minutes(self, days: int, today: Optional[date] = None) -> List[tuple]:
        """[(date, minutes)] for the last `days` days, oldest first, zero-filled."""
        today = today or date.today()
        start = today - timedelta(days=days - 1)
        rows = self.con.execute(
            "SELECT day, SUM(actual_s) FROM sessions WHERE phase='focus' AND day>=? AND day<=? GROUP BY day",
            (start.isoformat(), today.isoformat())).fetchall()
        m: Dict[str, float] = {d: s / 60.0 for d, s in rows}
        return [(start + timedelta(days=i), m.get((start + timedelta(days=i)).isoformat(), 0.0))
                for i in range(days)]

    def streak(self, today: Optional[date] = None) -> int:
        """Consecutive days with at least one completed focus session, ending today
        (or yesterday, if today has none yet)."""
        today = today or date.today()
        rows = self.con.execute("SELECT DISTINCT day FROM sessions WHERE phase='focus' AND completed=1").fetchall()
        days = {r[0] for r in rows}
        d = today if today.isoformat() in days else today - timedelta(days=1)
        n = 0
        while d.isoformat() in days:
            n += 1
            d -= timedelta(days=1)
        return n

    def totals(self) -> dict:
        r = self.con.execute(
            "SELECT COALESCE(SUM(actual_s),0), COALESCE(SUM(completed),0), COUNT(DISTINCT day) "
            "FROM sessions WHERE phase='focus'").fetchone()
        return {"minutes": r[0] / 60.0, "completed": int(r[1]), "days": int(r[2])}

    def recent(self, limit: int = 50) -> List[dict]:
        rows = self.con.execute(
            "SELECT started, ended, phase, planned_s, actual_s, completed, task FROM sessions "
            "WHERE phase='focus' ORDER BY started DESC LIMIT ?", (limit,)).fetchall()
        keys = ("started", "ended", "phase", "planned_s", "actual_s", "completed", "task")
        return [dict(zip(keys, r)) for r in rows]


def fill_demo(db: StatsDB, today: Optional[date] = None, days: int = 30, tasks: Optional[List[str]] = None):
    """Plausible sample history for screenshots."""
    import random
    rnd = random.Random(7)
    today = today or date.today()
    tasks = tasks or ["Hisobot", "Dizayn maketi", "Kod sharhi", "Ingliz tili", "Taqdimot"]
    for i in range(days, -1, -1):
        d = today - timedelta(days=i)
        if i != 0 and rnd.random() < 0.15:
            continue
        n = 2 if i == 0 else rnd.randint(2, 9)
        t = datetime(d.year, d.month, d.day, 9, 0)
        for k in range(n):
            completed = rnd.random() > 0.12
            actual = 25 * 60 if completed else rnd.randint(4, 20) * 60
            db.add(t, t + timedelta(seconds=actual), "focus", 1500, actual, completed, rnd.choice(tasks))
            t += timedelta(minutes=32)
