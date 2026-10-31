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


def test_items_are_sorted_before_taking_the_first_n(monkeypatch):
    # The newest item is last in the feed, past the per-feed limit.
    older = [entry(f"older {i}", f"2026-11-03 22:{i:02d}") for i in range(20)]
    fake_feed(monkeypatch, older + [entry("newest", "2026-11-04 10:00")])
    items = news.fetch_headlines(FEED, per_feed=15, now=pd.Timestamp("2026-11-04 11:00", tz="UTC"))
    assert len(items) == 15 and items[0]["title"] == "newest"


def test_undated_items_sort_last_and_are_kept(monkeypatch):
    fake_feed(monkeypatch, [{"title": "undated"}, entry("dated", "2026-11-04 10:00")])
    items = news.fetch_headlines(FEED, now=pd.Timestamp("2026-11-04 11:00", tz="UTC"))
    assert titles(items) == ["dated", "undated"]
