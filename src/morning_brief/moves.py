"""Describe what each row's change actually measures.

Markets close at different times, so at the pre-open the last two rows of one
ticker can be a session still trading while another's are yesterday's closes.
"""
import pandas as pd

from morning_brief.checks import Status

SOURCE_LABELS = {"yfinance": "Yahoo", "fred": "FRED", "ecb": "ECB"}
CHECK_MARKS = {Status.OK: "✓", Status.WARN: "⚠", Status.FAIL: "✗"}


def change_basis(row_date: pd.Timestamp, fetched_at: str, session: dict) -> str:
    """"live" if the row's session was still open when it was fetched, else the session's complete label."""
    close = pd.Timestamp(f"{row_date:%Y-%m-%d} {session['close']}", tz=session["tz"])
    fetched = pd.Timestamp(fetched_at)
    if fetched.tz is None:
        fetched = fetched.tz_localize("UTC")
    return "live" if fetched < close else session["complete"]


def cross_check_label(partner_source: str, status: Status, value: str | None = None,
                      date: pd.Timestamp | None = None) -> str:
    label = f"{CHECK_MARKS[status]} {SOURCE_LABELS[partner_source]}"
    return f"{label} {value} ({date:%a %m-%d})" if value is not None else label


def change_tint(change: str) -> str:
    """Cell style for a change: pale green up, pale red down. The sign stays, so color isn't the only cue."""
    if change.startswith(("n/a",)) or not any(c in "123456789" for c in change):
        return ""
    return "background-color: #e3f3ec" if change.startswith("+") else "background-color: #fbe9e4"


def is_fetch_stale(fetched_at: str | None, now) -> bool:
    """True once more than one weekday has passed since the fetch, by New York date."""
    if not fetched_at:
        return True
    fetched = pd.Timestamp(fetched_at)
    fetched = fetched.tz_localize("UTC") if fetched.tz is None else fetched
    fetched_day = fetched.tz_convert("America/New_York").tz_localize(None).normalize()
    today = pd.Timestamp(now).tz_convert("America/New_York").tz_localize(None).normalize()
    return len(pd.bdate_range(fetched_day + pd.Timedelta(days=1), today)) > 1


def format_fetched(fetched_at: str | None) -> str:
    return f"{pd.Timestamp(fetched_at):%a %b %d, %H:%M UTC}" if fetched_at else "never"


def count_label(n: int, singular: str, plural: str) -> str:
    return f"{n} {singular if n == 1 else plural}"


def published_date(published: str | None) -> str | None:
    return f"{pd.Timestamp(published):%Y-%m-%d}" if published else None


def format_last(value: float, kind: str, group: str) -> str:
    decimals = 3 if kind == "yield" else 4 if group == "FX" else 2
    return f"{value:.{decimals}f}"


def escape_dollars(text: str) -> str:
    """Streamlit markdown reads $...$ as math, which mangles text like "$10bn to $20bn"."""
    return text.replace("$", r"\$")


def date_span(prev_date: pd.Timestamp, last_date: pd.Timestamp) -> str:
    return f"{prev_date:%a %m-%d} → {last_date:%a %m-%d}"
