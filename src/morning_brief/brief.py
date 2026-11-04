"""A day's brief as plain data: everything the page shows, computed once and saved as JSON.

The refresh saves one snapshot per New York date in data/briefs/, so the static site can
rebuild every past day's page exactly as it was, and the archive survives redeploys.
The Streamlit app and the static site share the logic in checks, moves, ranking,
schedules and note; this module only collects their output.
"""
import json
from datetime import datetime
from pathlib import Path

import pandas as pd

from morning_brief import checks, moves, note, ranking, runs, schedules, storage
from morning_brief.config import ROOT

SNAPSHOT_DIR = ROOT / "data" / "briefs"
VERSION = 1
KEY_MARKETS = ["ES=F", "^TNX", "DX-Y.NYB", "CL=F", "GC=F", "^VIX"]


def _tint(change: str) -> str:
    css = moves.change_tint(change)
    return "" if not css else "up" if change.startswith("+") else "down"


def _row(r: dict) -> dict:
    return {"ticker": r["ticker"], "name": r["name"], "last": r["last"], "change": r["Change"], "tint": _tint(r["Change"]),
            "flag": r["flag"], "cross_check": r["cross-check"], "trend": [round(float(v), 6) for v in r["trend"]],
            "from_to": r["from → to"], "basis": r["basis"], "source": r["source"]}


def build(conn, cfg: dict, now: datetime, summary: dict | None) -> dict:
    """Everything the page shows for this moment, from the database and the saved news summary."""
    now = pd.Timestamp(now)
    prices = storage.load_prices(conn)
    events, status = storage.load_schedule_events(conn), storage.load_schedule_status(conn)
    sched_results = schedules.check_schedules(status, events, cfg.get("schedules", []), now)
    results = checks.run_all(prices, cfg, as_of=now.to_pydatetime()) + sched_results
    partners = checks.cross_checks(cfg.get("reconcile", []))
    view = schedules.build_view(status, events, cfg.get("schedules", []), now)
    last_fetch = prices["fetched_at"].max() if not prices.empty else None

    main = [i for i in cfg["instruments"] if not i.get("reference")]
    table = pd.DataFrame([moves.build_row(i, prices, results, cfg) for i in main])
    ranked, too_short = ranking.unusual_moves(prices, cfg)
    n_cross = sum(i["ticker"] in partners for i in main)
    coarse = moves.coarse_tickers(cfg.get("reconcile", []))
    n_coarse = sum(i["ticker"] in partners and i["ticker"] in coarse for i in main)
    overall, banner = moves.banner_message(results)

    groups = []
    for group, g in table.groupby("group", sort=False):
        groups.append({"name": group, "rows": [_row(r) for r in g.to_dict("records")]})
    by_ticker = {r["ticker"]: r for g in groups for r in g["rows"]}

    return {
        "version": VERSION,
        "date": f"{runs.to_ny(now):%Y-%m-%d}",
        "run_at": now.isoformat(timespec="seconds"),
        "last_fetch": last_fetch,
        "as_of": runs.as_of_label(last_fetch),
        "status": overall.name,
        "banner": banner,
        "problems": [{"status": r.status.name, "check": r.check, "ticker": r.ticker, "detail": r.detail}
                     for r in sorted(results, key=lambda r: -r.status) if r.status != checks.Status.OK],
        "coverage": {"checks": len(results), "instruments": len(main), "cross_checked": n_cross, "coarse": n_coarse,
                     "single_source": len(main) - n_cross},
        "headline": ranking.headline(ranked, cfg["checks"]),
        "tiles": [t for t in KEY_MARKETS if t in by_ticker and by_ticker[t]["last"] is not None],
        "groups": groups,
        "ranking": [{"name": r["name"], "change": r["change"], "z": round(float(r["z"]), 3)} for r in ranked.to_dict("records")],
        "thresholds": {"warn": cfg["checks"]["move_warn_z"], "fail": cfg["checks"]["move_fail_z"]},
        "too_short": too_short,
        "schedule": {"state": view.state, "today": view.today, "upcoming": view.upcoming, "failed": view.failed,
                     "covered": [s["name"] for s in cfg.get("schedules", [])]},
        "news": {k: (summary or {}).get(k) for k in ("model", "bullets", "headlines", "error")} if summary else None,
        "note": note.build(table, ranked, results, last_fetch, view, n_cross, cfg),
    }


def save(snapshot: dict, folder: Path | None = None) -> Path:
    """One file per New York date; a later refresh the same day replaces it, so each day keeps its latest data."""
    folder = folder or SNAPSHOT_DIR
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{snapshot['date']}.json"
    path.write_text(json.dumps(snapshot, indent=1, ensure_ascii=False, default=_plain) + "\n")
    return path


def load_all(folder: Path | None = None) -> list[dict]:
    """Every saved snapshot, newest first."""
    folder = folder or SNAPSHOT_DIR
    if not folder.exists():
        return []
    return sorted((json.loads(p.read_text()) for p in folder.glob("*.json")), key=lambda s: s["date"], reverse=True)


def _plain(value):
    """numpy and pandas scalars in news or schedule data, as plain JSON."""
    if hasattr(value, "item"):
        return value.item()
    if isinstance(value, (pd.Timestamp, datetime)):
        return value.isoformat()
    raise TypeError(f"not JSON serializable: {type(value)}")
