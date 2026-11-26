"""Pomodoro timer state machine.

The timer has no Qt dependency. Time comes from an injectable clock (seconds, float),
so tests can drive it deterministically. The UI calls tick() a few times per second
and reacts to the returned events.
"""
import time
from dataclasses import dataclass
from typing import Callable, List, Optional

FOCUS = "focus"
SHORT = "short"
LONG = "long"

IDLE = "idle"
RUNNING = "running"
PAUSED = "paused"

# event names returned by tick() and the control methods
EV_PHASE_DONE = "phase_done"        # the current phase ran to the end
EV_PHASE_START = "phase_start"      # a new phase was started (automatically or by start())
EV_STOPPED = "stopped"


@dataclass
class TimerConfig:
    focus_min: float = 25
    short_min: float = 5
    long_min: float = 15
    long_every: int = 4             # long break after every N focus sessions
    auto_start_breaks: bool = True
    auto_start_focus: bool = False

    def duration(self, phase: str) -> float:
        m = {FOCUS: self.focus_min, SHORT: self.short_min, LONG: self.long_min}[phase]
        return max(1.0, float(m) * 60.0)


@dataclass
class Event:
    kind: str
    phase: str
    completed: bool = False
    elapsed: float = 0.0            # seconds actually spent in the phase
    planned: float = 0.0
    started_at: float = 0.0


class PomodoroTimer:
    def __init__(self, config: Optional[TimerConfig] = None, clock: Callable[[], float] = time.time):
        self.cfg = config or TimerConfig()
        self.clock = clock
        self.phase = FOCUS
        self.state = IDLE
        self.completed_focus = 0     # focus sessions finished in the current cycle (reset on stop)
        self.total_focus_today = 0
        self._remaining = self.cfg.duration(FOCUS)
        self._end_at = 0.0
        self._phase_started = 0.0
        self._paused_total = 0.0
        self._paused_at = 0.0

    # ------------------------------------------------------------------ queries
    @property
    def planned(self) -> float:
        return self.cfg.duration(self.phase)

    def remaining(self) -> float:
        if self.state == RUNNING:
            return max(0.0, self._end_at - self.clock())
        return max(0.0, self._remaining)

    def progress(self) -> float:
        """0..1 of the current phase that has passed."""
        p = self.planned
        return min(1.0, max(0.0, 1.0 - self.remaining() / p)) if p else 0.0

    def elapsed(self) -> float:
        return max(0.0, self.planned - self.remaining())

    @property
    def is_focus(self) -> bool:
        return self.phase == FOCUS

    @property
    def active(self) -> bool:
        """A session is in progress (running or paused)."""
        return self.state in (RUNNING, PAUSED)

    def next_break(self) -> str:
        n = max(1, int(self.cfg.long_every))
        return LONG if (self.completed_focus % n == 0 and self.completed_focus > 0) else SHORT

    # ------------------------------------------------------------------ control
    def apply_config(self, cfg: TimerConfig):
        """New durations take effect at once only when the timer is idle."""
        self.cfg = cfg
        if self.state == IDLE:
            self._remaining = self.cfg.duration(self.phase)

    def start(self) -> List[Event]:
        if self.state == RUNNING:
            return []
        now = self.clock()
        if self.state == PAUSED:
            self._paused_total += now - self._paused_at
            self._end_at = now + self._remaining
            self.state = RUNNING
            return []
        self._begin(self.phase, now)
        return [Event(EV_PHASE_START, self.phase, planned=self.planned, started_at=now)]

    def pause(self):
        if self.state != RUNNING:
            return
        self._remaining = max(0.0, self._end_at - self.clock())
        self._paused_at = self.clock()
        self.state = PAUSED

    def toggle(self) -> List[Event]:
        if self.state == RUNNING:
            self.pause()
            return []
        return self.start()

    def stop(self) -> List[Event]:
        """Abort the current phase and return to an idle focus phase."""
        evs: List[Event] = []
        if self.active:
            evs.append(self._finish_event(EV_STOPPED, completed=False))
        self.phase = FOCUS
        self.state = IDLE
        self.completed_focus = 0
        self._remaining = self.cfg.duration(FOCUS)
        return evs

    def skip(self) -> List[Event]:
        """End the current phase early (not counted as completed) and move on."""
        evs: List[Event] = []
        was_active = self.active
        if was_active:
            evs.append(self._finish_event(EV_PHASE_DONE, completed=False))
        evs += self._advance(auto=was_active)
        return evs

    def tick(self) -> List[Event]:
        if self.state != RUNNING:
            return []
        if self.clock() < self._end_at:
            return []
        evs = [self._finish_event(EV_PHASE_DONE, completed=True)]
        if self.phase == FOCUS:
            self.completed_focus += 1
            self.total_focus_today += 1
        evs += self._advance(auto=True)
        return evs

    # ------------------------------------------------------------------ internals
    def _begin(self, phase: str, now: float):
        self.phase = phase
        self.state = RUNNING
        self._phase_started = now
        self._paused_total = 0.0
        self._end_at = now + self.cfg.duration(phase)

    def _finish_event(self, kind: str, completed: bool) -> Event:
        el = self.planned if completed else self.elapsed()
        return Event(kind, self.phase, completed=completed, elapsed=el, planned=self.planned,
                     started_at=self._phase_started)

    def _advance(self, auto: bool) -> List[Event]:
        nxt = self.next_break() if self.phase == FOCUS else FOCUS
        should_run = auto and (self.cfg.auto_start_breaks if nxt != FOCUS else self.cfg.auto_start_focus)
        if should_run:
            now = self.clock()
            self._begin(nxt, now)
            return [Event(EV_PHASE_START, nxt, planned=self.planned, started_at=now)]
        self.phase = nxt
        self.state = IDLE
        self._remaining = self.cfg.duration(nxt)
        return []

    # ------------------------------------------------------------------ demo (screenshots)
    def set_demo(self, phase: str, remaining: float, completed: int):
        now = self.clock()
        self.phase = phase
        self.completed_focus = completed
        self.state = PAUSED
        self._remaining = remaining
        self._phase_started = now - (self.cfg.duration(phase) - remaining)
        self._paused_at = now


def fmt_mmss(seconds: float) -> str:
    s = int(round(max(0.0, seconds)))
    if s >= 3600:
        return f"{s // 3600}:{(s % 3600) // 60:02d}:{s % 60:02d}"
    return f"{s // 60:02d}:{s % 60:02d}"
