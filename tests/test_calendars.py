"""A market closed for a holiday must not look stale or gappy, and a real miss still must."""
import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from morning_brief import calendars, checks  # noqa: E402
from morning_brief.checks import Status  # noqa: E402
from morning_brief.config import load_config  # noqa: E402

CFG = {"lookback_days": 60, "stale_warn_bdays": 1, "stale_fail_bdays": 3, "gap_warn": 3}


def rows(ticker, dates):
    return pd.DataFrame({"date": dates, "ticker": ticker, "close": 100.0, "source": "yfinance"})


def inst(ticker, calendar):
    return {"ticker": ticker, "source": "yfinance", "kind": "price", "calendar": calendar}


def test_nikkei_silver_week_holidays_are_not_gaps():
    # Sep 21-23, 2026 plus other Japanese holidays: five weekdays closed inside the window
    dates = calendars.sessions("XTKS", pd.Timestamp("2026-06-01"), pd.Timestamp("2026-10-30"))
    r = checks.check_gaps(rows("^N225", dates), CFG, [inst("^N225", "XTKS")])
    assert r[0].status == Status.OK and r[0].detail.startswith("0 missing")


def test_real_missing_sessions_still_warn():
    dates = calendars.sessions("XTKS", pd.Timestamp("2026-06-01"), pd.Timestamp("2026-10-30"))
    r = checks.check_gaps(rows("^N225", dates.delete([-5, -6, -7, -8])), CFG, [inst("^N225", "XTKS")])
    assert r[0].status == Status.WARN


def test_nikkei_is_fresh_through_its_holiday():
    # Tue Sep 22 pre-open: Monday was a holiday in Tokyo, so Friday is the latest session
    as_of = pd.Timestamp("2026-09-22 11:00", tz="UTC")
    dates = calendars.sessions("XTKS", pd.Timestamp("2026-08-01"), pd.Timestamp("2026-09-18"))
    assert checks.check_freshness(rows("^N225", dates), [inst("^N225", "XTKS")], as_of, CFG)[0].status == Status.OK


def test_us_futures_are_fresh_after_a_us_holiday():
    # Mon Jul 6 pre-open: Fri Jul 3 was the observed Independence Day holiday
    as_of = pd.Timestamp("2026-07-06 11:00", tz="UTC")
    dates = calendars.sessions("XNYS", pd.Timestamp("2026-06-01"), pd.Timestamp("2026-07-02"))
    assert checks.check_freshness(rows("ES=F", dates), [inst("ES=F", "XNYS")], as_of, CFG)[0].status == Status.OK


def test_a_session_really_missed_is_still_stale():
    as_of = pd.Timestamp("2026-07-07 11:00", tz="UTC")  # Monday's session should be in by Tuesday
    dates = calendars.sessions("XNYS", pd.Timestamp("2026-06-01"), pd.Timestamp("2026-07-02"))
    assert checks.check_freshness(rows("ES=F", dates), [inst("ES=F", "XNYS")], as_of, CFG)[0].status == Status.WARN


@pytest.mark.parametrize("name,closed,open_day", [
    ("USFED", "2026-10-12", "2026-10-13"),   # Columbus Day: bond market shut, NYSE open
    ("TARGET", "2026-05-01", "2026-05-04"),  # ECB publishes no rate on May 1
    ("FX", "2026-12-25", "2026-12-24"),      # Yahoo has no FX row on Christmas
])
def test_custom_calendars(name, closed, open_day):
    s = calendars.sessions(name, pd.Timestamp("2026-01-01"), pd.Timestamp("2026-12-31"))
    assert pd.Timestamp(closed) not in s and pd.Timestamp(open_day) in s


def test_no_calendar_means_weekdays():
    s = calendars.sessions(None, pd.Timestamp("2026-10-30"), pd.Timestamp("2026-11-02"))
    assert list(s) == [pd.Timestamp("2026-10-30"), pd.Timestamp("2026-11-02")]


def test_every_instrument_has_a_working_calendar():
    for i in load_config()["instruments"]:
        assert len(calendars.sessions(i["calendar"], pd.Timestamp("2026-01-01"), pd.Timestamp("2026-01-31"))) > 15


@pytest.mark.parametrize("ticker,calendar", [
    ("^N225", "XTKS"), ("^HSI", "XHKG"), ("^STOXX50E", "XETR"), ("ES=F", "XNYS"), ("^TNX", "XNYS"),
    ("DGS10", "USFED"), ("DEXJPUS", "USFED"), ("EURUSD=X", "FX"), ("ECB_EURUSD", "TARGET"),
])
def test_instruments_map_to_their_market(ticker, calendar):
    assert {i["ticker"]: i["calendar"] for i in load_config()["instruments"]}[ticker] == calendar
