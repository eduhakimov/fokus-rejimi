from fokus_rejimi.timer import (EV_PHASE_DONE, EV_PHASE_START, EV_STOPPED, FOCUS, IDLE, LONG, PAUSED, RUNNING,
                                SHORT, PomodoroTimer, TimerConfig, fmt_mmss)


class Clock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


def make(**kw):
    c = Clock()
    cfg = TimerConfig(focus_min=25, short_min=5, long_min=15, long_every=4, **kw)
    return PomodoroTimer(cfg, clock=c), c


def test_start_and_complete_focus():
    t, c = make()
    evs = t.start()
    assert evs[0].kind == EV_PHASE_START and t.state == RUNNING
    c.t += 600
    assert t.tick() == [] and abs(t.remaining() - 900) < 1e-6
    c.t += 900
    evs = t.tick()
    assert evs[0].kind == EV_PHASE_DONE and evs[0].completed and evs[0].phase == FOCUS
    assert t.phase == SHORT and t.state == RUNNING     # auto_start_breaks default
    assert t.completed_focus == 1


def test_long_break_after_four():
    t, c = make(auto_start_focus=True)
    t.start()
    phases = []
    for _ in range(8):
        c.t += t.remaining() + 0.1
        t.tick()
        phases.append(t.phase)
    assert phases == [SHORT, FOCUS, SHORT, FOCUS, SHORT, FOCUS, LONG, FOCUS]


def test_pause_resume_keeps_remaining():
    t, c = make()
    t.start()
    c.t += 100
    t.pause()
    assert t.state == PAUSED
    c.t += 5000
    assert abs(t.remaining() - 1400) < 1e-6
    t.start()
    c.t += 1400
    assert t.tick()[0].completed


def test_stop_reports_elapsed_and_resets():
    t, c = make()
    t.start()
    c.t += 300
    evs = t.stop()
    assert evs[0].kind == EV_STOPPED and not evs[0].completed and abs(evs[0].elapsed - 300) < 1e-6
    assert t.state == IDLE and t.phase == FOCUS and t.remaining() == 1500


def test_skip_idle_does_not_start():
    t, c = make()
    evs = t.skip()
    assert evs == [] and t.phase == SHORT and t.state == IDLE
    t.skip()
    assert t.phase == FOCUS and t.state == IDLE


def test_skip_running_focus_not_counted():
    t, c = make(auto_start_breaks=False)
    t.start()
    c.t += 60
    evs = t.skip()
    assert evs[0].kind == EV_PHASE_DONE and not evs[0].completed
    assert t.completed_focus == 0 and t.phase == SHORT and t.state == IDLE


def test_config_applies_when_idle_only():
    t, c = make()
    t.start()
    t.apply_config(TimerConfig(focus_min=50))
    assert t.remaining() <= 1500
    t.stop()
    assert t.remaining() == 3000


def test_fmt():
    assert fmt_mmss(65) == "01:05"
    assert fmt_mmss(3725) == "1:02:05"
    assert fmt_mmss(-3) == "00:00"
