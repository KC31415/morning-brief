"""The "What's scheduled today" panel, tested on saved copies of each source."""
import json
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from streamlit.testing.v1 import AppTest

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "streamlit_app" / "app.py"
sys.path.insert(0, str(ROOT / "src"))

from morning_brief import checks, config, schedules, storage  # noqa: E402
from morning_brief.checks import Status  # noqa: E402

FIXTURES = ROOT / "tests" / "fixtures" / "schedules"
NOW = pd.Timestamp("2026-11-02 11:00", tz="UTC")  # a Monday, 6am in New York
SOURCES = [{"name": "BEA", "parser": "bea", "urls": ["u"], "link": "https://bea.example/", "max_days_to_next": 45},
           {"name": "Treasury", "parser": "treasury", "urls": ["t"], "link": "https://td.example/", "max_days_to_next": 7}]


def sample(name):
    return (FIXTURES / name).read_text()


def find(events, text):
    return [e for e in events if text in e.event]


# ---------- parsers ----------
def test_bea_reads_date_time_and_news_releases_only():
    events = schedules.parse_bea(sample("bea.html"))
    trade = find(events, "International Trade")[0]
    assert (trade.date, trade.time) == ("2026-11-04", "08:30")
    assert len(find(events, "GDP (Second Estimate)")) == 1


def test_census_reads_indicator_with_period_and_time():
    events = schedules.parse_census(sample("census.html"))
    assert all(e.date.startswith("2026-1") and e.time for e in events)
    trade = find(events, "International Trade")[0]
    assert ", " in trade.event and trade.time == "08:30"


def test_census_handles_next_years_page():
    events = schedules.parse_census(sample("census_next_year.html"))
    assert events[0].date == "2027-01-04" and events[0].time == "10:00"


def test_fomc_has_both_days_and_no_invented_time():
    events = schedules.parse_fomc(sample("fomc.html"))
    december = [e for e in events if e.date in ("2026-12-08", "2026-12-09")]
    assert [e.date for e in december] == ["2026-12-08", "2026-12-09"]
    assert all(e.time is None for e in events)
    assert "projections" in december[1].event


def test_fomc_month_spanning_meeting():
    html = '<h4><a>2027 FOMC Meetings</a></h4><div class="fomc-meeting__month x"><strong>Apr/May</strong></div>' \
           '<div class="fomc-meeting__date y">30-1</div>'
    assert [e.date for e in schedules.parse_fomc(html)] == ["2027-04-30", "2027-05-01"]


def test_ecb_keeps_monetary_policy_meetings_only_with_no_time():
    events = schedules.parse_ecb(sample("ecb.html"))
    assert {"2026-12-16", "2026-12-17"} <= {e.date for e in events}
    assert not find(events, "non-monetary") and not find(events, "General Council")
    assert all(e.time is None for e in events)


def test_treasury_keeps_published_times_and_never_guesses_blank_ones():
    events = schedules.parse_treasury(sample("treasury.json"))
    published = [e for e in events if e.date == "2026-11-02"]
    assert published and all(e.time == "11:30" for e in published)
    assert find(events, "17-Week")[0].time is None
    assert find(events, "10-Year Note")[0].date == "2026-11-10"


@pytest.mark.parametrize("parser", ["bea", "census", "fomc", "ecb"])
def test_changed_page_format_is_an_error_not_an_empty_calendar(parser):
    with pytest.raises(ValueError):
        schedules.PARSERS[parser]("<html>we redesigned the page</html>")


def test_unreadable_time_is_not_guessed():
    assert schedules.parse_time("around lunchtime") is None
    assert schedules.parse_time("") is None
    assert schedules.parse_time("2:00 PM") == "14:00"


# ---------- fetching ----------
class Response:
    def __init__(self, text="", status=200):
        self.text, self.status = text, status

    def raise_for_status(self):
        if self.status >= 400:
            raise OSError(f"HTTP {self.status}")


def test_failed_source_is_recorded_and_others_still_load():
    def http(url, **kwargs):
        return Response(status=403) if url == "u" else Response(sample("treasury.json"))

    events, status = schedules.fetch_all(SOURCES, NOW, http)
    assert {e.source for e in events} == {"Treasury"}
    assert status["BEA"].startswith("HTTP 403") and status["Treasury"] is None


def test_one_good_year_page_is_enough_when_another_fails():
    source = {"name": "Census", "parser": "census", "urls": ["a", "b"], "link": "x"}

    def http(url, **kwargs):
        return Response(status=404) if url == "b" else Response(sample("census.html"))

    events, status = schedules.fetch_all([source], NOW, http)
    assert events and status["Census"] is None


def test_year_in_a_url_is_filled_in():
    seen = []
    source = {"name": "Census", "parser": "census", "urls": ["c-{year}.html"], "link": "x"}
    schedules.fetch_all([source], NOW, lambda url, **k: seen.append(url) or Response(sample("census.html")))
    assert seen == ["c-2026.html"]


# ---------- storage ----------
def db():
    conn = sqlite3.connect(":memory:")
    conn.executescript(storage.SCHEMA)
    return conn


EVENT = schedules.Event("BEA", "GDP", "2026-11-02", "08:30", "https://bea.example/")


def test_events_round_trip_with_event_time_source_and_link():
    conn = db()
    storage.save_schedules(conn, [EVENT], {"BEA": None}, "2026-11-02T11:00:00+00:00")
    row = storage.load_schedule_events(conn).iloc[0]
    assert (row["event"], row["event_time"], row["source"], row["link"]) == ("GDP", "08:30", "BEA", "https://bea.example/")


def test_good_fetch_replaces_old_events_so_cancellations_disappear():
    conn = db()
    storage.save_schedules(conn, [EVENT], {"BEA": None}, "t1")
    storage.save_schedules(conn, [schedules.Event("BEA", "Trade", "2026-11-04", "08:30", "l")], {"BEA": None}, "t2")
    assert list(storage.load_schedule_events(conn)["event"]) == ["Trade"]


def test_failed_fetch_keeps_old_events_and_last_good_time():
    conn = db()
    storage.save_schedules(conn, [EVENT], {"BEA": None}, "t1")
    storage.save_schedules(conn, [], {"BEA": "HTTP 500"}, "t2")
    assert list(storage.load_schedule_events(conn)["event"]) == ["GDP"]
    status = storage.load_schedule_status(conn).set_index("source").loc["BEA"]
    assert (status["last_success"], status["last_attempt"], status["error"]) == ("t1", "t2", "HTTP 500")


# ---------- checks ----------
def status_frame(rows):
    return pd.DataFrame(rows, columns=["source", "last_attempt", "last_success", "error"])


def events_frame(rows):
    return pd.DataFrame(rows, columns=["source", "event", "event_date", "event_time", "link", "fetched_at"])


FUTURE = [("BEA", "GDP", "2026-11-04", "08:30", "l", "t"), ("Treasury", "Bill", "2026-11-03", None, "l", "t")]
FRESH = "2026-11-02T10:00:00+00:00"


def results(status_rows, event_rows=FUTURE):
    return {r.ticker: r for r in schedules.check_schedules(status_frame(status_rows), events_frame(event_rows), SOURCES, NOW)}


def test_healthy_sources_pass():
    r = results([("BEA", FRESH, FRESH, None), ("Treasury", FRESH, FRESH, None)])
    assert {x.status for x in r.values()} == {Status.OK} and {x.check for x in r.values()} == {"schedule"}


def test_failed_fetch_is_flagged():
    r = results([("BEA", FRESH, "2026-11-01T10:00:00+00:00", "HTTP 403"), ("Treasury", FRESH, FRESH, None)])
    assert r["BEA"].status == Status.WARN and "HTTP 403" in r["BEA"].detail


def test_source_never_loaded_is_flagged():
    assert results([("Treasury", FRESH, FRESH, None)])["BEA"].status == Status.WARN


def test_old_fetch_is_stale():
    old = "2026-10-20T10:00:00+00:00"
    r = results([("BEA", old, old, None), ("Treasury", FRESH, FRESH, None)])
    assert r["BEA"].status == Status.WARN and "stale" in r["BEA"].detail


def test_loaded_but_nothing_upcoming_is_stale():
    r = results([("BEA", FRESH, FRESH, None), ("Treasury", FRESH, FRESH, None)],
                [("BEA", "Old", "2026-10-01", None, "l", "t"), FUTURE[1]])
    assert r["BEA"].status == Status.WARN and "no event in the next 45 days" in r["BEA"].detail


# ---------- what the panel shows ----------
def view(status_rows, event_rows):
    return schedules.build_view(status_frame(status_rows), events_frame(event_rows), SOURCES, NOW)


OK = [("BEA", FRESH, FRESH, None), ("Treasury", FRESH, FRESH, None)]


def test_today_is_sorted_by_time_with_unpublished_times_last_and_labeled():
    v = view(OK, [("Treasury", "Noon thing", "2026-11-02", "11:30", "l", "t"), ("BEA", "No time", "2026-11-02", None, "l", "t"),
                  ("BEA", "Early", "2026-11-02", "08:30", "l", "t")])
    assert [e["event"] for e in v.today] == ["Early", "Noon thing", "No time"]
    assert [e["time"] for e in v.today] == ["8:30 AM ET", "11:30 AM ET", "time not published"]


def test_today_follows_new_york_not_utc():
    late = pd.Timestamp("2026-11-03 03:00", tz="UTC")  # 10pm Monday in New York
    assert schedules.today_new_york(late) == "2026-11-02"


def test_next_five_business_days_skip_the_weekend():
    friday = pd.Timestamp("2026-11-06 12:00", tz="UTC")
    assert schedules.next_business_days(friday, 5)[:2] == ["2026-11-09", "2026-11-10"]
    assert len(schedules.next_business_days(friday, 5)) == 5


def test_same_release_from_two_agencies_is_one_row_with_both_links():
    v = view(OK, [("BEA", "Trade, Sept", "2026-11-02", "08:30", "b", "t"), ("Treasury", "Trade, Sept", "2026-11-02", "08:30", "c", "t")])
    assert len(v.today) == 1 and [s[0] for s in v.today[0]["sources"]] == ["BEA", "Treasury"]


def test_no_events_is_different_from_could_not_load():
    quiet = view(OK, [])
    assert quiet.state == "no_events" and quiet.failed == []
    partial = view([OK[0], ("Treasury", FRESH, None, "HTTP 500")], [])
    assert partial.state == "partial" and partial.failed == ["Treasury"]
    nothing = view([("BEA", FRESH, None, "HTTP 500"), ("Treasury", FRESH, None, "HTTP 500")], [])
    assert nothing.state == "not_loaded"


# ---------- the page ----------
def page(tmp_path, monkeypatch, event_rows=(), status_for=lambda name: None):
    path = tmp_path / "brief.db"
    conn = sqlite3.connect(path)
    conn.executescript(storage.SCHEMA)
    now = datetime.now(timezone.utc)
    end = checks.expected_session(now, "XNYS")
    stamp = now.isoformat(timespec="seconds")
    storage.upsert_prices(conn, pd.DataFrame({"date": pd.bdate_range(end=end, periods=80), "ticker": "GC=F",
                                              "close": 100 + np.cumsum(np.random.default_rng(0).normal(0, 1, 80)),
                                              "source": "yfinance", "fetched_at": stamp}))
    names = [s["name"] for s in config.load_config()["schedules"]]
    storage.save_schedules(conn, list(event_rows), {n: status_for(n) for n in names}, stamp)
    conn.close()
    monkeypatch.setattr(config, "DB_PATH", path)
    monkeypatch.setattr(config, "SUMMARY_PATH", tmp_path / "summary.json")
    return AppTest.from_file(str(APP), default_timeout=30).run()


def today_str():
    return schedules.today_new_york(pd.Timestamp.now(tz="UTC"))


def markdown(at):
    return " ".join(m.value for m in at.markdown)


def test_panel_sits_above_news_and_shows_todays_event_with_link(tmp_path, monkeypatch):
    event = schedules.Event("BEA", "GDP release", today_str(), "08:30", "https://www.bea.gov/news/schedule")
    at = page(tmp_path, monkeypatch, [event])
    assert not at.exception
    heads = [s.value for s in at.subheader]
    assert heads.index("What's scheduled today") == heads.index("Overnight news") - 1
    assert "8:30 AM ET" in markdown(at) and "GDP release" in markdown(at) and "https://www.bea.gov/news/schedule" in markdown(at)


def test_page_says_no_events_only_when_calendars_loaded(tmp_path, monkeypatch):
    at = page(tmp_path, monkeypatch)
    assert any("No events scheduled today" in i.value for i in at.info)


def test_page_says_could_not_load_and_flags_check_details(tmp_path, monkeypatch):
    at = page(tmp_path, monkeypatch, status_for=lambda name: "HTTP 500")
    assert not any("No events scheduled today" in i.value for i in at.info)
    assert any("Couldn't load" in e.value for e in list(at.warning) + list(at.error))
    details = pd.concat([d.value for d in at.dataframe if "check" in d.value.columns])
    assert "schedule" in set(details["check"])


def test_page_is_honest_that_bls_is_not_covered(tmp_path, monkeypatch):
    at = page(tmp_path, monkeypatch)
    assert any("BLS" in c.value and "CPI" in c.value for c in at.caption)


def test_no_llm_is_involved():
    assert "anthropic" not in (ROOT / "src" / "morning_brief" / "schedules.py").read_text()


def test_configured_sources_are_the_ones_that_work():
    names = {s["name"] for s in config.load_config()["schedules"]}
    assert names == {"BEA", "Census", "FOMC", "ECB", "Treasury"}
    assert all(json.dumps(s) for s in config.load_config()["schedules"])
