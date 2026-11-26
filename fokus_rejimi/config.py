"""User settings with defaults. Stored under one key in uzkit's settings.json."""
import copy

from .blocker import DEFAULT_RULES
from .hosts import DEFAULT_SITES
from .timer import TimerConfig

DEFAULTS = {
    "focus_min": 25,
    "short_min": 5,
    "long_min": 15,
    "long_every": 4,
    "auto_start_breaks": True,
    "auto_start_focus": False,
    "daily_goal_min": 120,
    "block_apps": True,
    "apps": DEFAULT_RULES,
    "warn_seconds": 10,
    "block_sites": False,          # opt-in: needs administrator rights
    "sites": DEFAULT_SITES,
    "strict": False,
    "strict_phrase": "",           # empty -> language default
    "sound": True,
    "volume": 70,
    "break_overlay": True,
    "close_to_tray": True,
    "task": "",
}


class Config:
    KEY = "fokus"

    def __init__(self, settings, persist: bool = True):
        self.settings = settings
        self.persist = persist
        stored = (settings.get(self.KEY, {}) if settings else {}) or {}
        self.data = copy.deepcopy(DEFAULTS)
        for k, v in stored.items():
            if k not in DEFAULTS:
                continue
            d = DEFAULTS[k]
            num = (int, float)
            if isinstance(d, bool):
                ok = isinstance(v, bool)
            elif isinstance(d, num):
                ok = isinstance(v, num) and not isinstance(v, bool)
            else:
                ok = isinstance(v, type(d))
            if ok:
                self.data[k] = v

    def __getitem__(self, k):
        return self.data.get(k, DEFAULTS.get(k))

    def get(self, k, default=None):
        return self.data.get(k, default)

    def set(self, k, v):
        self.data[k] = v
        self.save()

    def update(self, **kw):
        self.data.update(kw)
        self.save()

    def save(self):
        if self.persist and self.settings is not None:
            try:
                self.settings.set(self.KEY, self.data)
            except Exception:
                pass

    def timer_config(self) -> TimerConfig:
        def num(k, lo, hi):
            try:
                return min(hi, max(lo, float(self.data.get(k, DEFAULTS[k]))))
            except (TypeError, ValueError):
                return DEFAULTS[k]
        return TimerConfig(focus_min=num("focus_min", 1, 180), short_min=num("short_min", 1, 60),
                           long_min=num("long_min", 1, 120), long_every=int(num("long_every", 1, 12)),
                           auto_start_breaks=bool(self.data.get("auto_start_breaks")),
                           auto_start_focus=bool(self.data.get("auto_start_focus")))
