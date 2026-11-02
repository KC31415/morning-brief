"""Describe what each row's change actually measures.

Markets close at different times, so at the pre-open the last two rows of one
ticker can be a session still trading while another's are yesterday's closes.
"""
import pandas as pd

from morning_brief import checks
from morning_brief.checks import Status

SOURCE_LABELS = {"yfinance": "Yahoo", "fred": "FRED", "ecb": "ECB"}
CHECK_MARKS = {Status.OK: "✓", Status.WARN: "⚠", Status.FAIL: "✗"}
FLAGS = {Status.OK: "", Status.WARN: "⚠️", Status.FAIL: "❌"}
TREND_DAYS = 20


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


def banner_message(results: list) -> tuple[Status, str]:
    """The overall status and the sentence the page's banner shows for it."""
    overall = checks.overall_status(results)
    problems = [r for r in results if r.status != Status.OK]
    if overall == Status.OK:
        return overall, "All data checks passed."
    if overall == Status.WARN:
        return overall, (f"{count_label(len(problems), 'data warning', 'data warnings')}. "
                         "Numbers flagged below may be stale or unusual.")
    n_failed = sum(r.status == Status.FAIL for r in problems)
    return overall, f"{count_label(n_failed, 'data check', 'data checks')} FAILED. Do not rely on flagged rows."


def build_row(inst: dict, prices: pd.DataFrame, results: list, config: dict) -> dict:
    """One table row. The flag comes from the same results as the banner."""
    pairs = config.get("reconcile", [])
    partners = checks.cross_checks(pairs)
    sources = {i["ticker"]: i["source"] for i in config["instruments"]}
    t = inst["ticker"]
    g = prices[prices["ticker"] == t].sort_values("date")
    if t in partners:
        compared = checks.compared_value(prices, t, partners[t])
        value = format_last(compared[1], inst["kind"], inst["group"]) if compared else None
        status = checks.cross_check_status(results, pairs)[t]
        cross_check = cross_check_label(sources[partners[t]], status, value, compared[0] if compared else None)
    else:
        cross_check = "single source"
    row = {"ticker": t, "group": inst["group"], "name": inst["name"], "last": None, "Change": "n/a",
           "trend": g["close"].tail(TREND_DAYS).tolist(), "from → to": None, "basis": None,
           "source": SOURCE_LABELS[inst["source"]], "cross-check": cross_check,
           "flag": FLAGS[checks.worst_by_ticker(results, pairs).get(t, Status.OK)]}
    if len(g) >= 2:
        last, prev = g["close"].iloc[-1], g["close"].iloc[-2]
        latest = g.iloc[-1]
        row.update(last=format_last(last, inst["kind"], inst["group"]),
                   Change=f"{(last - prev) * 100:+.1f} bp" if inst["kind"] == "yield" else f"{(last / prev - 1) * 100:+.2f}%",
                   **{"from → to": date_span(g["date"].iloc[-2], latest["date"])},
                   basis=change_basis(latest["date"], latest["fetched_at"], config["sessions"][inst["session"]]))
    return row
