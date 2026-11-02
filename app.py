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
last_fetch = prices["fetched_at"].max() if not prices.empty else None
st.caption(f"Cross-asset moves before the US open, with checks that flag bad data.  \n"
           f"Data last fetched {moves.format_fetched(last_fetch)}")

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
KEY_MARKETS = ["ES=F", "^TNX", "DX-Y.NYB", "CL=F", "GC=F", "^VIX"]
TREND_DAYS = 20
rows = []
main_instruments = [i for i in cfg["instruments"] if not i.get("reference")]
for inst in main_instruments:
    g = prices[prices["ticker"] == inst["ticker"]].sort_values("date")
    t = inst["ticker"]
    if t in partners:
        compared = checks.compared_value(prices, t, partners[t])
        value = moves.format_last(compared[1], inst["kind"], inst["group"]) if compared else None
        cross_check = moves.cross_check_label(sources[partners[t]], pair_status[t], value, compared[0] if compared else None)
    else:
        cross_check = "unverified"
    flag = FLAG[by_ticker.get(inst["ticker"], checks.Status.OK)]  # same results as the banner
    if len(g) < 2:
        rows.append({"ticker": t, "group": inst["group"], "name": inst["name"], "last": None, "Change": "n/a",
                     "trend": g["close"].tolist(), "from → to": None, "basis": None,
                     "source": moves.SOURCE_LABELS[inst["source"]], "cross-check": cross_check, "flag": flag})
        continue
    last, prev = g["close"].iloc[-1], g["close"].iloc[-2]
    latest = g.iloc[-1]
    change = f"{(last - prev) * 100:+.1f} bp" if inst["kind"] == "yield" else f"{(last / prev - 1) * 100:+.2f}%"
    rows.append({"ticker": t, "group": inst["group"], "name": inst["name"],
                 "last": moves.format_last(last, inst["kind"], inst["group"]), "Change": change,
                 "trend": g["close"].tail(TREND_DAYS).tolist(),
                 "from → to": moves.date_span(g["date"].iloc[-2], latest["date"]),
                 "basis": moves.change_basis(latest["date"], latest["fetched_at"], cfg["sessions"][inst["session"]]),
                 "source": moves.SOURCE_LABELS[inst["source"]], "cross-check": cross_check, "flag": flag})
table = pd.DataFrame(rows)

by_key = table.set_index("ticker")
tiles = [t for t in KEY_MARKETS if t in by_key.index and pd.notna(by_key.loc[t, "last"])]
# A wrapping row, so tile values stay whole on narrower screens
with st.container(horizontal=True):
    for t in tiles:
        row = by_key.loc[t]
        st.metric(f"{row['name']} {row['flag']}".strip(), row["last"], row["Change"], border=True, width=195,
                  chart_data=row["trend"], chart_type="line",
                  help=f"{row['from → to']} ({row['basis']}). The line shows the last {TREND_DAYS} closes.")

# Fixed pixel widths that add up to fit a 1024px screen with no column clipped
COLUMNS = {
    "name": st.column_config.TextColumn("Instrument", width=140),
    "last": st.column_config.TextColumn("Last", width=70),
    "Change": st.column_config.TextColumn("Change", width=65),
    "trend": st.column_config.LineChartColumn(f"{TREND_DAYS}d trend", width=65),
    "from → to": st.column_config.TextColumn("From → to", width=150),
    "basis": st.column_config.TextColumn("Basis", width=105),
    "source": st.column_config.TextColumn("Source", width=55),
    "cross-check": st.column_config.TextColumn("Cross-check", width=175),
    "flag": st.column_config.TextColumn("Flag", width=40),
}
# One table per row: side by side, the rightmost columns get clipped on a laptop screen
for group, g in table.groupby("group", sort=False):
    st.subheader(group)
    styled = g.drop(columns=["group", "ticker"]).style.map(moves.change_tint, subset=["Change"])
    st.dataframe(styled, hide_index=True, width="stretch", column_config=COLUMNS)

st.caption("Each change compares a ticker's last two rows, so periods differ by market. "
           "live = that session was still open when fetched; it is not a real-time price.")
n_single = sum(i["ticker"] not in partners for i in main_instruments)
st.caption(f"{n_single} of {len(main_instruments)} instruments are single-source (unverified): "
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
    elif s.get("error") == "no headlines":
        st.info("No new official releases since the previous US close.")
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

# ---- 4. How the page checks itself ----
st.divider()
with st.expander("How the data checks work"):
    st.markdown("""
- **Completeness:** every instrument arrived with enough history and no bad values.
- **Freshness:** the latest row is from the session we expect.
- **Gaps:** no business days are missing from recent history.
- **Sanity:** today's move is plausible for that instrument, and the price isn't frozen.
- **Reconciliation:** two sources for the same series agree.
""")
st.caption("Built from free public sources, not production market data. "
           "[Source code and build notes](https://github.com/KC31415/morning-brief)")
