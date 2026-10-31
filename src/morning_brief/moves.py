"""Describe what each row's change actually measures.

Markets close at different times, so at the pre-open the last two rows of one
ticker can be a session still trading while another's are yesterday's closes.
"""
import pandas as pd


def change_basis(row_date: pd.Timestamp, fetched_at: str, session: dict) -> str:
    """"live" if the row's session was still open when it was fetched, else the session's complete label."""
    close = pd.Timestamp(f"{row_date:%Y-%m-%d} {session['close']}", tz=session["tz"])
    fetched = pd.Timestamp(fetched_at)
    if fetched.tz is None:
        fetched = fetched.tz_localize("UTC")
    return "live" if fetched < close else session["complete"]


def format_last(value: float, kind: str) -> str:
    return f"{value:.3f}" if kind == "yield" else f"{value:.2f}"


def escape_dollars(text: str) -> str:
    """Streamlit markdown reads $...$ as math, which mangles text like "$10bn to $20bn"."""
    return text.replace("$", r"\$")


def date_span(prev_date: pd.Timestamp, last_date: pd.Timestamp) -> str:
    return f"{prev_date:%a %m-%d} → {last_date:%a %m-%d}"
