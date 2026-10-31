"""Data quality checks, run on every refresh before anything is shown.

Each check returns CheckResult objects. The dashboard shows the worst status
as a banner, so a late or broken feed is visible instead of silently stale.

Checks:
  freshness       latest date for each ticker vs the session we expect
  completeness    every configured ticker arrived; no bad values
  gaps            missing business days in the recent history
  sanity          today's move vs that instrument's normal volatility
  reconciliation  two sources for the same series agree
"""
from dataclasses import dataclass
from enum import IntEnum

import numpy as np
import pandas as pd


class Status(IntEnum):
    OK = 0
    WARN = 1
    FAIL = 2


@dataclass
class CheckResult:
    check: str
    ticker: str | None
    status: Status
    detail: str


# FRED publishes with about a one-day lag, so it is allowed to be one session behind.
SOURCE_LAG_BDAYS = {"yfinance": 0, "fred": 1}


def expected_session(as_of: pd.Timestamp) -> pd.Timestamp:
    """Last completed US business day before `as_of` (we run before the open).

    Ignores exchange holidays on purpose; a holiday shows up as a WARN, which is
    the honest outcome (a human should glance at it), not a FAIL.
    """
    return (pd.Timestamp(as_of).normalize() - pd.offsets.BDay(1)).normalize()


def bdays_between(start: pd.Timestamp, end: pd.Timestamp) -> int:
    """Business days from start to end (0 if start >= end)."""
    if start >= end:
        return 0
    return len(pd.bdate_range(start, end)) - 1


def check_freshness(prices: pd.DataFrame, instruments: list[dict], as_of, cfg: dict) -> list[CheckResult]:
    expected = expected_session(as_of)
    latest = prices.groupby("ticker")["date"].max()
    out = []
    for inst in instruments:
        t = inst["ticker"]
        if t not in latest.index:
            continue  # completeness reports missing tickers
        behind = bdays_between(latest[t], expected) - SOURCE_LAG_BDAYS.get(inst["source"], 0)
        behind = max(behind, 0)
        if behind >= cfg["stale_fail_bdays"]:
            status = Status.FAIL
        elif behind >= cfg["stale_warn_bdays"]:
            status = Status.WARN
        else:
            status = Status.OK
        out.append(CheckResult("freshness", t, status,
                               f"latest {latest[t]:%Y-%m-%d}, expected {expected:%Y-%m-%d} ({behind} bday behind)"))
    return out


def check_completeness(prices: pd.DataFrame, instruments: list[dict]) -> list[CheckResult]:
    out = []
    present = set(prices["ticker"])
    for inst in instruments:
        t = inst["ticker"]
        if t not in present:
            out.append(CheckResult("completeness", t, Status.FAIL, "no data received"))
            continue
        s = prices.loc[prices["ticker"] == t, "close"]
        if s.isna().any():
            out.append(CheckResult("completeness", t, Status.FAIL, f"{int(s.isna().sum())} missing values"))
        elif inst["kind"] == "price" and (s <= 0).any():
            out.append(CheckResult("completeness", t, Status.FAIL, "zero or negative price"))
        else:
            out.append(CheckResult("completeness", t, Status.OK, f"{len(s)} rows"))
    return out


def check_gaps(prices: pd.DataFrame, cfg: dict) -> list[CheckResult]:
    out = []
    for t, g in prices.groupby("ticker"):
        # Window by calendar, not by row count: counting the last N rows would
        # quietly skip past the very gaps we are trying to find.
        last = g["date"].max()
        expected = pd.bdate_range(end=last, periods=cfg["lookback_days"])
        dates = pd.DatetimeIndex(g.loc[g["date"] >= expected[0], "date"])
        missing = len(expected.difference(dates))
        status = Status.WARN if missing > cfg["gap_warn"] else Status.OK
        out.append(CheckResult("gaps", t, status, f"{missing} missing business days in window"))
    return out


def daily_changes(series: pd.Series, kind: str) -> pd.Series:
    """% change for prices, absolute change for yields (percentage points)."""
    return series.diff() if kind == "yield" else series.pct_change()


def check_sanity(prices: pd.DataFrame, instruments: list[dict], cfg: dict) -> list[CheckResult]:
    out = []
    for inst in instruments:
        t = inst["ticker"]
        g = prices[prices["ticker"] == t].sort_values("date")
        if g.empty:
            continue  # completeness already reports missing tickers
        chg =daily_changes(g["close"], inst["kind"]).dropna().tail(cfg["lookback_days"] + 1)
        if len(chg) < 21:
            out.append(CheckResult("sanity", t, Status.WARN, f"only {len(chg)} changes, too few to judge"))
            continue
        history, latest = chg.iloc[:-1], chg.iloc[-1]
        sd = history.std()
        if not np.isfinite(sd) or sd == 0:
            out.append(CheckResult("sanity", t, Status.FAIL, "price has not moved in the window (frozen feed?)"))
            continue
        z = abs(latest) / sd
        if z >= cfg["move_fail_z"]:
            status = Status.FAIL
        elif z >= cfg["move_warn_z"]:
            status = Status.WARN
        else:
            status = Status.OK
        out.append(CheckResult("sanity", t, status, f"latest move is {z:.1f} std devs"))
    return out


def check_reconciliation(prices: pd.DataFrame, pairs: list[dict]) -> list[CheckResult]:
    out = []
    wide = prices.pivot_table(index="date", columns="ticker", values="close")
    for p in pairs:
        a, b = p["a"], p["b"]
        name = f"{a} vs {b}"
        if a not in wide or b not in wide:
            out.append(CheckResult("reconciliation", name, Status.WARN, "one side missing, cannot compare"))
            continue
        both = wide[[a, b]].dropna()
        if both.empty:
            out.append(CheckResult("reconciliation", name, Status.WARN, "no overlapping dates"))
            continue
        day = both.index[-1]
        diff = abs(both.loc[day, a] - both.loc[day, b])
        if diff >= p["fail"]:
            status = Status.FAIL
        elif diff >= p["warn"]:
            status = Status.WARN
        else:
            status = Status.OK
        out.append(CheckResult("reconciliation", name, status, f"differ by {diff:.3f} on {day:%Y-%m-%d}"))
    return out


def run_all(prices: pd.DataFrame, config: dict, as_of) -> list[CheckResult]:
    insts, cfg = config["instruments"], config["checks"]
    return (
        check_completeness(prices, insts)
        + check_freshness(prices, insts, as_of, cfg)
        + check_gaps(prices, cfg)
        + check_sanity(prices, insts, cfg)
        + check_reconciliation(prices, config.get("reconcile", []))
    )


def overall_status(results: list[CheckResult]) -> Status:
    return max((r.status for r in results), default=Status.OK)
