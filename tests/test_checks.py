"""Tests for the data quality checks, using small synthetic price histories."""
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from morning_brief import checks  # noqa: E402
from morning_brief.checks import Status  # noqa: E402

CFG = {"lookback_days": 60, "stale_warn_bdays": 1, "stale_fail_bdays": 3,
       "gap_warn": 3, "move_warn_z": 4.0, "move_fail_z": 10.0, "frozen_changes": 10}
AS_OF = pd.Timestamp("2026-10-30 11:00")  # a Friday; expected session = Thu 2026-10-29


def make_series(ticker, end="2026-10-29", n=80, start_price=100.0, vol=0.01, seed=0, source="yfinance"):
    rng = np.random.default_rng(seed)
    dates = pd.bdate_range(end=end, periods=n)
    closes = start_price * np.cumprod(1 + rng.normal(0, vol, n))
    return pd.DataFrame({"date": dates, "ticker": ticker, "close": closes, "source": source})


def inst(ticker, kind="price", source="yfinance"):
    return {"ticker": ticker, "name": ticker, "group": "g", "kind": kind, "source": source}


# ---------- freshness ----------
def test_expected_session_is_previous_business_day():
    assert checks.expected_session(pd.Timestamp("2026-11-02 08:00")) == pd.Timestamp("2026-10-30")  # Mon -> Fri


def test_fresh_series_passes():
    r = checks.check_freshness(make_series("A"), [inst("A")], AS_OF, CFG)
    assert r[0].status == Status.OK


def test_one_day_stale_warns_and_three_days_fails():
    warn = checks.check_freshness(make_series("A", end="2026-10-28"), [inst("A")], AS_OF, CFG)
    fail = checks.check_freshness(make_series("A", end="2026-10-26"), [inst("A")], AS_OF, CFG)
    assert warn[0].status == Status.WARN
    assert fail[0].status == Status.FAIL


def test_fred_allowed_one_day_lag():
    r = checks.check_freshness(make_series("DGS10", end="2026-10-28", source="fred"),
                               [inst("DGS10", "yield", "fred")], AS_OF, CFG)
    assert r[0].status == Status.OK


# ---------- completeness ----------
def test_missing_ticker_fails():
    r = checks.check_completeness(make_series("A"), [inst("A"), inst("B")])
    assert {x.ticker: x.status for x in r} == {"A": Status.OK, "B": Status.FAIL}


def test_zero_price_fails():
    df = make_series("A")
    df.loc[df.index[-1], "close"] = 0.0
    assert checks.check_completeness(df, [inst("A")])[0].status == Status.FAIL


# ---------- gaps ----------
def test_no_gaps_passes():
    assert checks.check_gaps(make_series("A"), CFG)[0].status == Status.OK


def test_gaps_warn_when_many_days_missing():
    # drop 5 recent days, well inside the 60-day window
    df = make_series("A").drop(index=[60, 61, 62, 63, 64])
    assert checks.check_gaps(df, CFG)[0].status == Status.WARN


# ---------- sanity ----------
def test_normal_move_passes():
    assert checks.check_sanity(make_series("A"), [inst("A")], CFG)[0].status == Status.OK


def test_huge_move_fails_as_bad_data():
    df = make_series("A")
    df.loc[df.index[-1], "close"] = df["close"].iloc[-2] * 1.5  # +50% on a 1% vol asset
    assert checks.check_sanity(df, [inst("A")], CFG)[0].status == Status.FAIL


def test_frozen_feed_fails():
    df = make_series("A")
    df["close"] = 100.0
    assert checks.check_sanity(df, [inst("A")], CFG)[0].status == Status.FAIL


def test_yield_uses_absolute_change():
    df = make_series("Y", start_price=4.0, vol=0.01)
    r = checks.check_sanity(df, [inst("Y", kind="yield")], CFG)
    assert r[0].status in (Status.OK, Status.WARN)


# ---------- reconciliation ----------
@pytest.mark.parametrize("gap,expected", [(0.01, Status.OK), (0.08, Status.WARN), (0.30, Status.FAIL)])
def test_reconciliation_thresholds(gap, expected):
    a = make_series("^TNX", start_price=4.2, vol=0.001)
    b = a.assign(ticker="DGS10", close=a["close"] + gap, source="fred")
    r = checks.check_reconciliation(pd.concat([a, b]), [{"a": "^TNX", "b": "DGS10", "warn": 0.05, "fail": 0.15}])
    assert r[0].status == expected


# ---------- overall ----------
def test_overall_is_worst_status():
    rs = [checks.CheckResult("x", "A", Status.OK, ""), checks.CheckResult("x", "B", Status.WARN, "")]
    assert checks.overall_status(rs) == Status.WARN


# ---------- timezone handling ----------
def test_checks_accept_timezone_aware_as_of():
    # Production passes datetime.now(timezone.utc); stored dates are naive.
    aware = pd.Timestamp("2026-10-30 11:00", tz="UTC")
    r = checks.check_freshness(make_series("A"), [inst("A")], aware, CFG)
    assert r[0].status == Status.OK


def test_aware_and_naive_as_of_give_same_session():
    assert checks.expected_session(pd.Timestamp("2026-10-30 11:00", tz="UTC")) == checks.expected_session(AS_OF)


def test_aware_as_of_is_read_as_new_york_time():
    # Same instant, same answer, whichever zone it is expressed in.
    utc = pd.Timestamp("2026-10-30 01:00", tz="UTC")  # still Thu 29th in New York
    assert checks.expected_session(utc) == pd.Timestamp("2026-10-28")
    assert checks.expected_session(utc.tz_convert("Asia/Tokyo")) == pd.Timestamp("2026-10-28")


# ---------- recently frozen feed ----------
def flat_tail(n_changes):
    df = make_series("A")
    df.loc[df.index[-n_changes:], "close"] = df["close"].iloc[-n_changes - 1]
    return df


def test_last_ten_changes_all_zero_fails():
    assert checks.check_sanity(flat_tail(10), [inst("A")], CFG)[0].status == Status.FAIL


def test_nine_zero_changes_is_not_frozen():
    assert checks.check_sanity(flat_tail(9), [inst("A")], CFG)[0].status == Status.OK


# ---------- robust volatility ----------
def test_reversal_after_bad_print_still_fails():
    # Yesterday's +50% print must not inflate the baseline that judges today's reversal.
    df = make_series("A")
    df.loc[df.index[-2], "close"] *= 1.5
    assert checks.check_sanity(df, [inst("A")], CFG)[0].status == Status.FAIL


def test_robust_vol_matches_std_on_normal_data():
    # The MAD is scaled so the 4 and 10 thresholds still read as standard deviations.
    x = pd.Series(np.random.default_rng(0).normal(0, 0.01, 5000))
    assert checks.robust_vol(x) == pytest.approx(x.std(), rel=0.05)


def test_mostly_unchanged_series_falls_back_to_std():
    # More than half the changes are zero, so the MAD is 0 even though the series moves.
    df = make_series("Y", start_price=4.0)
    steps = np.zeros(len(df))
    steps[::3] = 0.01
    steps[-1] = 0.01  # a real move today, which a zero baseline would turn into infinite z
    df["close"] = 4.0 + np.cumsum(steps)
    r = checks.check_sanity(df, [inst("Y", kind="yield")], CFG)[0]
    assert r.status == Status.OK


# ---------- instruments removed from the config ----------
def test_ticker_no_longer_configured_is_not_checked():
    # Rows stay in the database after an instrument is removed; they must not raise warnings.
    prices = pd.concat([make_series("A"), make_series("OLD", n=1)])
    config = {"instruments": [inst("A")], "checks": CFG}
    assert {r.ticker for r in checks.run_all(prices, config, AS_OF)} == {"A"}
