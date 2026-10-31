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


def cross_check_label(partner_source: str, status: Status) -> str:
    return f"{CHECK_MARKS[status]} {SOURCE_LABELS[partner_source]}"


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
