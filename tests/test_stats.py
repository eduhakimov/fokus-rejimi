from datetime import date, datetime, timedelta

from fokus_rejimi.stats import StatsDB, fill_demo


def test_summary_and_streak(tmp_path):
    db = StatsDB(tmp_path / "s.sqlite")
    today = date(2026, 3, 10)
    for back in (0, 1, 2, 4):
        d = today - timedelta(days=back)
        t = datetime(d.year, d.month, d.day, 10)
        db.add(t, t + timedelta(minutes=25), "focus", 1500, 1500, True, "a")
    t = datetime(2026, 3, 10, 12)
    db.add(t, t + timedelta(minutes=7), "focus", 1500, 420, False, "b")
    s = db.day_summary(today)
    assert s == {"minutes": 32.0, "completed": 1, "interrupted": 1}
    assert db.streak(today) == 3
    assert db.streak(today + timedelta(days=1)) == 3    # today empty, yesterday counts
    assert db.streak(today + timedelta(days=2)) == 0
    days = db.daily_minutes(7, today)
    assert len(days) == 7 and days[-1] == (today, 32.0) and days[-4][1] == 0
    assert db.recent(1)[0]["task"] == "b"
    db.clear()
    assert db.totals()["completed"] == 0
    db.close()


def test_demo(tmp_path):
    db = StatsDB(tmp_path / "d.sqlite")
    fill_demo(db, date(2026, 1, 31))
    assert db.totals()["minutes"] > 100
    db.close()
