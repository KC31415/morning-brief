"""Data quality checks, run on every refresh before anything is shown.

Each check returns CheckResult objects. The dashboard shows the worst status
as a banner, so a late or broken feed is visible instead of silently stale.

Checks:
  freshness       latest date for each ticker vs the session we expect
  completeness    every configured ticker arrived; no bad values
  gaps            sessions missing from the recent history
  sanity          today's move vs that instrument's normal volatility
  reconciliation  two sources for the same series agree
"""
from dataclasses import dataclass
from enum import IntEnum

import numpy as np
import pandas as pd

from morning_brief.calendars import sessions


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
SOURCE_LAG_BDAYS = {"yfinance": 0, "fred": 1, "ecb": 0}


def expected_session(as_of: pd.Timestamp, calendar: str | None = None) -> pd.Timestamp:
    """Last completed session before `as_of` (we run before the open), on that market's calendar.

    Stored dates are naive, so a timezone-aware `as_of` is converted to New York
    time and made naive. A naive `as_of` is taken as already being local.
    """
    ts = pd.Timestamp(as_of)
    if ts.tz is not None:
        ts = ts.tz_convert("America/New_York").tz_localize(None)
    today = ts.normalize()
    return sessions(calendar, today - pd.Timedelta(days=30), today - pd.Timedelta(days=1))[-1]


def sessions_between(start: pd.Timestamp, end: pd.Timestamp, calendar: str | None = None) -> int:
    """Sessions after start, up to and including end (0 if start >= end)."""
    if start >= end:
        return 0
    return int((sessions(calendar, start, end) > start).sum())


def check_freshness(prices: pd.DataFrame, instruments: list[dict], as_of, cfg: dict) -> list[CheckResult]:
    latest = prices.groupby("ticker")["date"].max()
    out = []
    for inst in instruments:
        t = inst["ticker"]
        if t not in latest.index:
            continue  # completeness reports missing tickers
        calendar = inst.get("calendar")
        expected = expected_session(as_of, calendar)
        lag = inst.get("lag_bdays", SOURCE_LAG_BDAYS.get(inst["source"], 0))
        behind = sessions_between(latest[t], expected, calendar) - lag
        behind = max(behind, 0)
        if behind >= cfg["stale_fail_bdays"]:
            status = Status.FAIL
        elif behind >= cfg["stale_warn_bdays"]:
            status = Status.WARN
        else:
            status = Status.OK
        out.append(CheckResult("freshness", t, status,
                               f"latest {latest[t]:%Y-%m-%d}, expected {expected:%Y-%m-%d} ({behind} sessions behind)"))
    return out


def check_completeness(prices: pd.DataFrame, instruments: list[dict], cfg: dict) -> list[CheckResult]:
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
        elif len(s) < cfg["min_rows"]:
            out.append(CheckResult("completeness", t, Status.WARN, f"only {len(s)} rows, need {cfg['min_rows']}"))
        else:
            out.append(CheckResult("completeness", t, Status.OK, f"{len(s)} rows"))
    return out


def check_gaps(prices: pd.DataFrame, cfg: dict, instruments: list[dict] | None = None) -> list[CheckResult]:
    out = []
    calendars = {i["ticker"]: i.get("calendar") for i in instruments or []}
    for t, g in prices.groupby("ticker"):
        # Window by calendar, not by row count: counting the last N rows would
        # quietly skip past the very gaps we are trying to find.
        last = g["date"].max()
        span = pd.Timedelta(days=cfg["lookback_days"] * 2)  # calendar days, more than enough sessions
        expected = sessions(calendars.get(t), last - span, last)[-cfg["lookback_days"]:]
        dates = pd.DatetimeIndex(g.loc[g["date"] >= expected[0], "date"])
        missing = len(expected.difference(dates))
        status = Status.WARN if missing > cfg["gap_warn"] else Status.OK
        out.append(CheckResult("gaps", t, status, f"{missing} missing sessions in window"))
    return out


def daily_changes(series: pd.Series, kind: str) -> pd.Series:
    """% change for prices, absolute change for yields (percentage points)."""
    return series.diff() if kind == "yield" else series.pct_change()


def robust_vol(changes: pd.Series) -> float:
    """Typical size of a change that a few bad prints can't inflate.

    The median absolute deviation, scaled by 1.4826 so it equals the standard
    deviation on normal data. If most changes are zero the MAD is 0 even though
    the series moves, so fall back to the standard deviation.
    """
    mad = (changes - changes.median()).abs().median()
    return 1.4826 * mad if mad > 0 else changes.std()


def latest_move_z(prices: pd.DataFrame, inst: dict, cfg: dict) -> float | None:
    """The latest move in robust standard deviations, or None if there isn't enough movement to judge."""
    g = prices[prices["ticker"] == inst["ticker"]].sort_values("date")
    chg = daily_changes(g["close"], inst["kind"]).dropna().tail(cfg["lookback_days"] + 1)
    if len(chg) < 21:
        return None
    sd = robust_vol(chg.iloc[:-1])
    return None if not np.isfinite(sd) or sd == 0 else float(abs(chg.iloc[-1]) / sd)


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
        if (chg.tail(cfg["frozen_changes"]) == 0).all():
            out.append(CheckResult("sanity", t, Status.FAIL,
                                   f"no change in the last {cfg['frozen_changes']} sessions (frozen feed?)"))
            continue
        z = latest_move_z(prices, inst, cfg)
        if z is None:
            out.append(CheckResult("sanity", t, Status.FAIL, "price has not moved in the window (frozen feed?)"))
            continue
        if z >= cfg["move_fail_z"]:
            status = Status.FAIL
        elif z >= cfg["move_warn_z"]:
            status = Status.WARN
        else:
            status = Status.OK
        out.append(CheckResult("sanity", t, status, f"latest move is {z:.1f} robust std devs"))
    return out


def pair_name(pair: dict) -> str:
    return f"{pair['a']} vs {pair['b']}"


def check_reconciliation(prices: pd.DataFrame, pairs: list[dict]) -> list[CheckResult]:
    out = []
    wide = prices.pivot_table(index="date", columns="ticker", values="close")
    for p in pairs:
        a, b = p["a"], p["b"]
        name = pair_name(p)
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
    # Rows outlive an instrument in the database; only judge what is configured now
    prices = prices[prices["ticker"].isin([i["ticker"] for i in insts])]
    return (
        check_completeness(prices, insts, cfg)
        + check_freshness(prices, insts, as_of, cfg)
        + check_gaps(prices, cfg, insts)
        + check_sanity(prices, insts, cfg)
        + check_reconciliation(prices, config.get("reconcile", []))
    )


def compared_value(prices: pd.DataFrame, a: str, b: str) -> tuple[pd.Timestamp, float] | None:
    """The date reconciliation compares and series b's value on it: their last shared date."""
    wide = prices[prices["ticker"].isin([a, b])].pivot_table(index="date", columns="ticker", values="close")
    if a not in wide or b not in wide:
        return None
    both = wide[[a, b]].dropna()
    return None if both.empty else (both.index[-1], float(both[b].iloc[-1]))


def cross_checks(pairs: list[dict]) -> dict[str, str]:
    """Each ticker that has a second source, mapped to that source."""
    return {p["a"]: p["b"] for p in pairs} | {p["b"]: p["a"] for p in pairs}


def cross_check_status(results: list[CheckResult], pairs: list[dict]) -> dict[str, Status]:
    """The reconciliation result for each ticker in a pair."""
    by_pair = {r.ticker: r.status for r in results if r.check == "reconciliation"}
    out = {}
    for p in pairs:
        status = by_pair.get(pair_name(p), Status.WARN)
        out[p["a"]] = out[p["b"]] = status
    return out


def worst_by_ticker(results: list[CheckResult], pairs: list[dict]) -> dict[str, Status]:
    """Worst status per instrument. A reconciliation result counts against both sides of its pair."""
    members = {pair_name(p): (p["a"], p["b"]) for p in pairs}
    worst = {}
    for r in results:
        for t in members.get(r.ticker, (r.ticker,)):
            if t and r.status > worst.get(t, Status.OK):
                worst[t] = r.status
    # A reference series has no row of its own, so its problems show on the main row
    for p in pairs:
        if worst.get(p["b"], Status.OK) > worst.get(p["a"], Status.OK):
            worst[p["a"]] = worst[p["b"]]
    return worst


def overall_status(results: list[CheckResult]) -> Status:
    return max((r.status for r in results), default=Status.OK)
