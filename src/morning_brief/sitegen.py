"""Render the static site: the latest brief, one archived page per day, and an archive index.

    python scripts/build_site.py --out public

Everything is computed here, in Python, by the same code the checks use. The browser
only draws charts, switches between precomputed demo results, and works out whether the
data is stale at the moment someone is looking, since a static page can't know that
when it's built.
"""
import html
import json
import re
import shutil
from datetime import datetime
from pathlib import Path

import pandas as pd
from jinja2 import Environment, FileSystemLoader, select_autoescape
from markupsafe import Markup

from morning_brief import brief, demo, history, incidents, runs, schedules, storage
from morning_brief.config import ROOT

WEB = ROOT / "web"
SITE_URL = "https://kc31415.github.io/morning-brief/"
HOME_URL = "https://kc31415.github.io"
REPO_URL = "https://github.com/KC31415/morning-brief"


# ---- small formatting helpers, used as template filters ----

def md(text: str | None) -> Markup:
    """The page's own short markdown (**bold** and [text](url)) as safe HTML. Everything else is escaped."""
    if not text:
        return Markup("")
    out = html.escape(text)
    out = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", out)
    out = re.sub(r"\[([^\]]+)\]\((https?://[^)\s]+)\)", r'<a href="\2">\1</a>', out)
    return Markup(out)


def sparkline(values: list, width: int = 120, height: int = 32, color: str = "currentColor") -> Markup:
    """An inline SVG line, so sparklines need no JavaScript."""
    vals = [float(v) for v in values if v is not None]
    if len(vals) < 2:
        return Markup("")
    lo, hi = min(vals), max(vals)
    span = (hi - lo) or 1.0
    pts = " ".join(f"{i * (width - 2) / (len(vals) - 1) + 1:.1f},{height - 2 - (v - lo) / span * (height - 4):.1f}"
                   for i, v in enumerate(vals))
    return Markup(f'<svg class="spark" viewBox="0 0 {width} {height}" width="{width}" height="{height}" aria-hidden="true">'
                  f'<polyline fill="none" stroke="{color}" stroke-width="1.6" points="{pts}"/></svg>')


def long_date(day: str) -> str:
    return f"{pd.Timestamp(day):%a %b %d, %Y}"


def env() -> Environment:
    e = Environment(loader=FileSystemLoader(WEB / "templates"), autoescape=select_autoescape(["html", "j2"]),
                    trim_blocks=True, lstrip_blocks=True)
    e.filters.update(md=md, sparkline=sparkline, long_date=long_date,
                     tojson_safe=lambda v: Markup(json.dumps(v, ensure_ascii=False).replace("</", "<\\/")))
    return e


# ---- latest-page extras: computed at build time from the database ----

def demo_results(prices: pd.DataFrame, cfg: dict, as_of, schedule_results, instruments: list[dict] | None = None) -> dict:
    """Every instrument × fault the demo offers, run through the real checks on a copy of the data."""
    out = {}
    insts = instruments or [i for i in cfg["instruments"] if not i.get("reference")]
    for inst in insts:
        if (prices["ticker"] == inst["ticker"]).sum() < 2:
            continue
        runs_for = {}
        for fault in demo.faults_for(inst):
            sim = demo.simulate(prices, cfg, inst["ticker"], fault, as_of, schedule_results)
            runs_for[demo.FAULTS[fault]] = {"status": sim.status_after.name, "banner": sim.banner,
                                            "findings": [str(md(f.text)) for f in sim.findings],
                                            "message": sim.message, "row": str(md(sim.row_text))}
        out[inst["name"]] = runs_for
    return out


def incident_view(cfg: dict) -> dict | None:
    pair = next((p for p in cfg.get("reconcile", []) if p["a"] == incidents.VIX_FEB_2026["a"]), None)
    df = incidents.load()
    if df is None or pair is None:
        return None
    days = incidents.replay(df, pair)
    return {"summary": incidents.summary(df, pair),
            "rows": [{"date": f"{r['date']:%a %b %d}", "yahoo": f"{r['a']:.2f}", "fred": f"{r['b']:.2f}",
                      "gap": f"{r['gap']:.2f}", "status": r["status"].name if hasattr(r["status"], "name") else str(r["status"])}
                     for r in days.to_dict("records")]}


def history_series(prices: pd.DataFrame, cfg: dict) -> dict:
    """Each main instrument's stored closes, for the interactive history chart."""
    out = {}
    for inst in cfg["instruments"]:
        if inst.get("reference"):
            continue
        g = prices[prices["ticker"] == inst["ticker"]].sort_values("date")
        if len(g):
            out[inst["name"]] = {"dates": [f"{d:%Y-%m-%d}" for d in g["date"]], "closes": [round(float(c), 6) for c in g["close"]]}
    return out


def track_record(conn) -> dict:
    check_log, refresh_log = storage.load_check_runs(conn), storage.load_refresh_runs(conn)
    return {"headline": history.headline(check_log, refresh_log),
            "findings": history.findings(check_log).to_dict("records"),
            "refreshes": history.refreshes(check_log, refresh_log).to_dict("records")}


# ---- the build ----

def build(out: Path, conn, cfg: dict, summary: dict | None, now: datetime, snapshots: list[dict] | None = None,
          demo_instruments: list[dict] | None = None) -> list[Path]:
    """Write the whole site to `out`. Returns the HTML pages written."""
    snapshots = snapshots if snapshots is not None else brief.load_all()
    if not snapshots:
        # A first deploy before any refresh has saved one: build today's from the database, without saving it
        snapshots = [brief.build(conn, cfg, now, summary)]
    latest = snapshots[0]

    if out.exists():
        shutil.rmtree(out)
    (out / "briefs").mkdir(parents=True)
    shutil.copytree(WEB / "static", out / "assets")
    (out / ".nojekyll").write_text("")

    prices = storage.load_prices(conn)
    as_of = pd.Timestamp(latest["run_at"]).to_pydatetime()
    sched = schedules.check_schedules(storage.load_schedule_status(conn), storage.load_schedule_events(conn),
                                      cfg.get("schedules", []), pd.Timestamp(as_of))
    extras = {"demo": demo_results(prices, cfg, as_of, sched, demo_instruments), "incident": incident_view(cfg),
              "history": history_series(prices, cfg), "track": track_record(conn)}

    e = env()
    common = {"site_url": SITE_URL, "home_url": HOME_URL, "repo_url": REPO_URL, "built_at": runs.as_of_label(now.isoformat()),
              "archive": [{"date": s["date"], "status": s["status"], "headline": s.get("headline")} for s in snapshots]}
    written = []

    def write(path: Path, template: str, **ctx):
        path.write_text(e.get_template(template).render(**common, **ctx))
        written.append(path)

    write(out / "index.html", "brief.html.j2", s=latest, mode="latest", base="", extras=extras)
    for s in snapshots:
        write(out / "briefs" / f"{s['date']}.html", "brief.html.j2", s=s, mode="archive", base="../", extras=None,
              is_latest=s["date"] == latest["date"])
    write(out / "archive.html", "archive.html.j2", base="", latest=latest)
    write(out / "404.html", "404.html.j2", base="/morning-brief/")
    (out / "latest.json").write_text(json.dumps(latest, indent=1, ensure_ascii=False) + "\n")
    return written
