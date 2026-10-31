"""Which headlines make it into the brief."""
import sys
import types
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from morning_brief import news  # noqa: E402

FEED = [{"name": "F", "url": "x"}]


def entry(title, when):
    return {"title": title, "published_parsed": pd.Timestamp(when).timetuple()}


def fake_feed(monkeypatch, entries):
    parsed = types.SimpleNamespace(bozo=False, entries=entries)
    monkeypatch.setattr(news.feedparser, "parse", lambda url: parsed)


def titles(items):
    return [i["title"] for i in items]


def test_cutoff_on_monday_is_fridays_close():
    # Oct 30 is still daylight time: 4pm New York = 20:00 UTC
    now = pd.Timestamp("2026-11-02 11:00", tz="UTC")
    assert news.previous_close(now) == pd.Timestamp("2026-10-30 20:00", tz="UTC")


def test_cutoff_midweek_is_yesterdays_close():
    # After the clocks change: 4pm New York = 21:00 UTC
    now = pd.Timestamp("2026-11-04 11:00", tz="UTC")
    assert news.previous_close(now) == pd.Timestamp("2026-11-03 21:00", tz="UTC")


def test_monday_run_covers_friday_afternoon(monkeypatch):
    fake_feed(monkeypatch, [entry("Friday after close", "2026-10-30 21:00"), entry("Friday before close", "2026-10-30 19:00")])
    items = news.fetch_headlines(FEED, now=pd.Timestamp("2026-11-02 11:00", tz="UTC"))
    assert titles(items) == ["Friday after close"]
