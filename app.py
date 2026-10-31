"""Streamlit dashboard: data status banner, overnight moves, news brief.

    streamlit run app.py
"""
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

from morning_brief import checks, storage  # noqa: E402
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
by_ticker = {}
for r in results:
    if r.ticker and r.status > by_ticker.get(r.ticker, checks.Status.OK):
        by_ticker[r.ticker] = r.status

st.title("Morning Brief")
last_fetch = prices["fetched_at"].max() if not prices.empty else "never"
st.caption(f"Data last fetched {last_fetch} UTC")

# ---- 1. Data status banner: the first thing anyone sees ----
problems = [r for r in results if r.status != checks.Status.OK]
if overall == checks.Status.OK:
    st.success("All data checks passed.")
elif overall == checks.Status.WARN:
    st.warning(f"{len(problems)} data warnings. Numbers flagged below may be stale or unusual.")
else:
    st.error(f"{sum(r.status == checks.Status.FAIL for r in problems)} data checks FAILED. Do not rely on flagged rows.")
if problems:
    with st.expander("Check details"):
        st.dataframe(
            pd.DataFrame([{"status": r.status.name, "check": r.check, "ticker": r.ticker, "detail": r.detail}
                          for r in sorted(problems, key=lambda r: -r.status)]),
            hide_index=True, use_container_width=True,
        )

# ---- 2. Overnight moves by asset class ----
FLAG = {checks.Status.OK: "", checks.Status.WARN: "⚠️", checks.Status.FAIL: "❌"}
rows = []
for inst in cfg["instruments"]:
    g = prices[prices["ticker"] == inst["ticker"]].sort_values("date")
    if len(g) < 2:
        rows.append({"group": inst["group"], "name": inst["name"], "last": None, "change": "n/a",
                     "as of": None, "flag": "❌"})
        continue
    last, prev = g["close"].iloc[-1], g["close"].iloc[-2]
    change = f"{(last - prev) * 100:+.1f} bp" if inst["kind"] == "yield" else f"{(last / prev - 1) * 100:+.2f}%"
    rows.append({"group": inst["group"], "name": inst["name"], "last": round(last, 4), "change": change,
                 "as of": g["date"].iloc[-1].strftime("%Y-%m-%d"), "flag": FLAG[by_ticker.get(inst["ticker"], checks.Status.OK)]})
table = pd.DataFrame(rows)

cols = st.columns(2)
for i, (group, g) in enumerate(table.groupby("group", sort=False)):
    with cols[i % 2]:
        st.subheader(group)
        st.dataframe(g.drop(columns="group"), hide_index=True, use_container_width=True)

# ---- 3. News brief with sources ----
st.subheader("Overnight news")
if SUMMARY_PATH.exists():
    s = json.loads(SUMMARY_PATH.read_text())
    links = {h["id"]: h for h in s.get("headlines", [])}
    if s.get("bullets"):
        for b in s["bullets"]:
            refs = " ".join(f"[[{n}]]({links[n]['link']})" for n in b["sources"] if n in links)
            st.markdown(f"- {b['bullet']} {refs}")
        st.caption(f"AI-generated from the headlines below ({s['model']}). Check sources before acting.")
    elif s.get("error"):
        st.info(s["error"])
    with st.expander(f"All headlines ({len(links)})"):
        for h in links.values():
            st.markdown(f"[{h['id']}] **{h['source']}**: [{h['title']}]({h['link']})")
else:
    st.info("No news summary yet.")
