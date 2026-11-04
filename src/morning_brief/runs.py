"""When the refresh ran, and whether the page's data is from before the US open.

Each run is logged with what started it, so the page and the workflow's guard can
tell a scheduled pre-open run from a manual one, and an on-time run from a late one.
"""
from dataclasses import dataclass

import pandas as pd

NY = "America/New_York"
OPEN = "09:30"            # US cash equity open, New York time
EXPECTED_BY = "08:00"     # the pre-open refresh should have run by now on a weekday
AUTOMATIC = ("scheduler", "github-cron")  # triggers that skip if today's refresh already ran


def to_ny(ts) -> pd.Timestamp:
    t = pd.Timestamp(ts)
    return (t.tz_localize("UTC") if t.tz is None else t).tz_convert(NY)


def _at(day: pd.Timestamp, hhmm: str) -> pd.Timestamp:
    return pd.Timestamp(f"{day:%Y-%m-%d} {hhmm}", tz=NY)


def is_pre_open(ts) -> bool:
    """True if this instant is on a weekday before 9:30 New York time."""
    t = to_ny(ts)
    return t.weekday() < 5 and t < _at(t, OPEN)


def should_run(trigger: str, run_times: list, now) -> tuple[bool, str]:
    """Automatic triggers skip if a refresh already ran today (New York date); manual runs always go."""
    if trigger not in AUTOMATIC:
        return True, f"{trigger} run: always refreshes"
    today = to_ny(now).date()
    done = [t for t in run_times if to_ny(t).date() == today]
    if done:
        return False, f"already refreshed today at {to_ny(max(done)):%H:%M} New York time"
    return True, "no refresh yet today"


@dataclass
class Timing:
    level: str      # "ok", "info" or "warn"
    message: str    # empty when level is "ok"


def refresh_timing(last_fetch, now) -> Timing:
    """Is the page showing today's pre-open data? Says so plainly when it isn't.

    Weekdays only, holidays included, matching the schedule. The stale banner
    (moves.is_fetch_stale) still covers data that's more than a weekday old.
    """
    if not last_fetch:
        return Timing("warn", "No refresh has run yet.")
    fetched, now_ny = to_ny(last_fetch), to_ny(now)
    if now_ny.weekday() >= 5:
        return Timing("ok", "")
    if fetched.date() == now_ny.date():
        if fetched >= _at(fetched, OPEN):
            return Timing("info", f"Today's refresh ran at {fetched:%-I:%M %p} ET, after the US open, so moves "
                                  "marked live are mid-session, not pre-open.")
        return Timing("ok", "")
    if now_ny >= _at(now_ny, EXPECTED_BY):
        return Timing("warn", f"Today's pre-open refresh hasn't run (expected by {_hm(EXPECTED_BY)} ET). "
                              f"Showing data from {fetched:%a %b %d, %-I:%M %p} ET.")
    return Timing("ok", "")


def as_of_label(last_fetch) -> str:
    """'Wed Nov 04, 6:24 AM ET, pre-open', or the same with 'after the US open' / 'weekend'."""
    if not last_fetch:
        return "never"
    t = to_ny(last_fetch)
    when = "weekend" if t.weekday() >= 5 else "pre-open" if is_pre_open(t) else "after the US open"
    return f"{t:%a %b %d, %-I:%M %p} ET, {when}"


def _hm(hhmm: str) -> str:
    return f"{pd.Timestamp(f'2000-01-01 {hhmm}'):%-I:%M %p}"
