"""Streamlit dashboard: data status banner, latest changes, news brief.

    streamlit run app.py
"""
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

from morning_brief import checks, moves, storage  # noqa: E402
from morning_brief.config import DB_PATH, SUMMARY_PATH, load_config  # noqa: E402

st.set_page_config(page_title="Morning Brief", layout="wide")
cfg = load_config()

if not DB_PATH.exists():
    st.error("No data yet. Run `python scripts/refresh.py` first.")
    st.stop()

conn = storage.connect(DB_PATH)
prices = storage.load_prices(conn)
results = checks.run_all(prices, cfg, as_of=datetime.now(timezone.utc))
overall = checks.overall_status(results)
by_ticker = checks.worst_by_ticker(results, cfg.get("reconcile", []))
partners = checks.cross_checks(cfg.get("reconcile", []))
pair_status = checks.cross_check_status(results, cfg.get("reconcile", []))
sources = {i["ticker"]: i["source"] for i in cfg["instruments"]}

st.title("Morning Brief")
last_fetch = prices["fetched_at"].max() if not prices.empty else "never"
st.caption(f"Data last fetched {last_fetch} UTC")

# ---- 1. Data status banner: the first thing anyone sees ----
problems = [r for r in results if r.status != checks.Status.OK]
if overall == checks.Status.OK:
    st.success("All data checks passed.")
elif overall == checks.Status.WARN:
    st.warning(f"{moves.count_label(len(problems), 'data warning', 'data warnings')}. Numbers flagged below may be stale or unusual.")
else:
    n_failed = sum(r.status == checks.Status.FAIL for r in problems)
    st.error(f"{moves.count_label(n_failed, 'data check', 'data checks')} FAILED. Do not rely on flagged rows.")
if problems:
    with st.expander("Check details"):
        st.dataframe(
            pd.DataFrame([{"status": r.status.name, "check": r.check, "ticker": r.ticker, "detail": r.detail}
                          for r in sorted(problems, key=lambda r: -r.status)]),
            hide_index=True, width="stretch",
        )

# ---- 2. Latest change by asset class ----
FLAG = {checks.Status.OK: "", checks.Status.WARN: "⚠️", checks.Status.FAIL: "❌"}
rows = []
for inst in cfg["instruments"]:
    g = prices[prices["ticker"] == inst["ticker"]].sort_values("date")
    t = inst["ticker"]
    cross_check = moves.cross_check_label(sources[partners[t]], pair_status[t]) if t in partners else "unverified"
    flag = FLAG[by_ticker.get(inst["ticker"], checks.Status.OK)]  # same results as the banner
    if len(g) < 2:
        rows.append({"group": inst["group"], "name": inst["name"], "last": None, "Change": "n/a",
                     "from → to": None, "basis": None, "source": inst["source"], "cross-check": cross_check, "flag": flag})
        continue
    last, prev = g["close"].iloc[-1], g["close"].iloc[-2]
    latest = g.iloc[-1]
    change = f"{(last - prev) * 100:+.1f} bp" if inst["kind"] == "yield" else f"{(last / prev - 1) * 100:+.2f}%"
    rows.append({"group": inst["group"], "name": inst["name"], "last": moves.format_last(last, inst["kind"], inst["group"]), "Change": change,
                 "from → to": moves.date_span(g["date"].iloc[-2], latest["date"]),
                 "basis": moves.change_basis(latest["date"], latest["fetched_at"], cfg["sessions"][inst["session"]]),
                 "source": inst["source"], "cross-check": cross_check, "flag": flag})
table = pd.DataFrame(rows)

# One table per row: side by side, the rightmost columns get clipped on a laptop screen
for group, g in table.groupby("group", sort=False):
    st.subheader(group)
    st.dataframe(g.drop(columns="group"), hide_index=True, width="stretch")

st.caption("Each change compares a ticker's last two rows, so periods differ by market. "
           "live = that session was still open when fetched; it is not a real-time price.")
n_single = sum(i["ticker"] not in partners for i in cfg["instruments"])
st.caption(f"{n_single} of {len(cfg['instruments'])} instruments are single-source (unverified): "
           "passing checks means they look plausible, not that a second source agrees.")

# ---- 3. News brief with sources ----
st.subheader("Overnight news")
if SUMMARY_PATH.exists():
    s = json.loads(SUMMARY_PATH.read_text())
    links = {h["id"]: h for h in s.get("headlines", [])}
    if s.get("bullets"):
        for b in s["bullets"]:
            refs = " ".join(f"[[{n}]]({links[n]['link']})" for n in b["sources"] if n in links)
            st.markdown(f"- {moves.escape_dollars(b['bullet'])} {refs}")
        st.caption(f"AI-generated from the headlines below ({s['model']}). Check sources before acting.")
    elif s.get("error"):
        st.info(s["error"])
    else:
        st.info("No market-moving headlines overnight")
    with st.expander(f"All headlines ({len(links)})"):
        for h in links.values():
            date = moves.published_date(h.get("published"))
            st.markdown(f"[{h['id']}] **{h['source']}**{f' ({date})' if date else ''}: [{moves.escape_dollars(h['title'])}]({h['link']})")
else:
    st.info("No news summary yet.")
