"""Replay a real day when two sources disagreed, through the real reconciliation check.

The demo's faults are simulated. This one isn't: on Fri Feb 6, 2026 Yahoo's VIX close and
FRED's VIXCLS differed by about 2.6 points (build notes, entry 21). The values come from a
file fetched from both sources, never typed in, and the page states whatever the check
returns on them.
"""
import logging
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from morning_brief import checks, ingest
from morning_brief.config import ROOT

log = logging.getLogger(__name__)

VIX_FEB_2026 = {
    "a": "^VIX", "b": "VIXCLS", "day": "2026-02-06",
    "start": "2026-01-30", "end": "2026-02-13",   # a week either side
    "path": ROOT / "data" / "incidents" / "vix-2026-02-06.csv",
}
LABELS = {"yfinance": "Yahoo", "fred": "FRED"}


def fetch(incident: dict = VIX_FEB_2026, days: int = 400) -> pd.DataFrame:
    """Both sources' closes around the incident, from the same fetchers the refresh uses."""
    df = pd.concat([ingest.fetch_yfinance([incident["a"]], days), ingest.fetch_fred([incident["b"]], days)],
                   ignore_index=True)
    df = df[(df["date"] >= incident["start"]) & (df["date"] <= incident["end"])]
    return df.assign(fetched_at=datetime.now(timezone.utc).isoformat(timespec="seconds"))


def ensure(incident: dict = VIX_FEB_2026) -> bool:
    """Fetch the file once, if it's missing. A failed fetch writes nothing, so the page says it isn't loaded."""
    path: Path = incident["path"]
    if path.exists():
        return True
    try:
        df = fetch(incident)
    except Exception:
        log.exception("incident fetch failed")
        return False
    if set(df["ticker"]) != {incident["a"], incident["b"]}:
        log.warning("incident fetch is missing a source (got %s); not saving it", sorted(set(df["ticker"])))
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    df.assign(date=df["date"].dt.strftime("%Y-%m-%d")).to_csv(path, index=False)
    log.info("saved %d incident rows to %s", len(df), path)
    return True


def load(incident: dict = VIX_FEB_2026) -> pd.DataFrame | None:
    path: Path = incident["path"]
    if not path.exists():
        return None
    return pd.read_csv(path, parse_dates=["date"])


def replay(df: pd.DataFrame, pair: dict) -> pd.DataFrame:
    """Each shared date, with the status the real reconciliation check gives on the data up to that day."""
    wide = df.pivot_table(index="date", columns="ticker", values="close")[[pair["a"], pair["b"]]].dropna()
    rows = []
    for day in wide.index:
        result = checks.check_reconciliation(df[df["date"] <= day], [pair])[0]
        rows.append({"date": day, "a": wide.loc[day, pair["a"]], "b": wide.loc[day, pair["b"]],
                     "gap": abs(wide.loc[day, pair["a"]] - wide.loc[day, pair["b"]]), "status": result.status,
                     "detail": result.detail})
    return pd.DataFrame(rows)


def summary(df: pd.DataFrame, pair: dict, incident: dict = VIX_FEB_2026) -> str:
    """One sentence on the incident day, written from the data and the check's actual result."""
    days = replay(df, pair)
    hit = days[days["date"] == pd.Timestamp(incident["day"])]
    if hit.empty:
        return f"The fetched data has no shared date on {pd.Timestamp(incident['day']):%a %b %d, %Y}, so there's nothing to replay."
    r = hit.iloc[0]
    sources = df.drop_duplicates("ticker").set_index("ticker")["source"]
    a, b = LABELS.get(sources[pair["a"]], pair["a"]), LABELS.get(sources[pair["b"]], pair["b"])
    verdict = {checks.Status.FAIL: f"FAIL (fail at ≥ {pair['fail']:g})",
               checks.Status.WARN: f"WARN (warn at ≥ {pair['warn']:g})",
               checks.Status.OK: f"OK: the gap is under the warn line of {pair['warn']:g}, so this check would not have caught it"}
    return (f"On {r['date']:%a %b %d, %Y}, {a}'s VIX close was {r['a']:.2f} and {b}'s was {r['b']:.2f}, "
            f"a gap of {r['gap']:.2f}. The real reconciliation check, run on that day's data, returns "
            f"{verdict[r['status']]}.")
