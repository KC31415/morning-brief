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

from morning_brief import checks, demo, moves, ranking, storage  # noqa: E402
from morning_brief.config import DB_PATH, SUMMARY_PATH, load_config  # noqa: E402

st.set_page_config(page_title="Morning Brief", layout="wide")
cfg = load_config()

if not DB_PATH.exists():
    st.error("No data yet. Run `python scripts/refresh.py` first.")
    st.stop()

conn = storage.connect(DB_PATH)
prices = storage.load_prices(conn)
results = checks.run_all(prices, cfg, as_of=datetime.now(timezone.utc))
partners = checks.cross_checks(cfg.get("reconcile", []))

st.title("Morning Brief")
last_fetch = prices["fetched_at"].max() if not prices.empty else None
st.caption(f"Cross-asset moves before the US open, with checks that flag bad data.  \n"
           f"Data last fetched {moves.format_fetched(last_fetch)}")

# ---- 1. Data status banner: the first thing anyone sees ----
if moves.is_fetch_stale(last_fetch, pd.Timestamp.now(tz="UTC")):
    st.error(f"Data is stale: last updated {moves.format_fetched(last_fetch)}. The refresh may have stopped running.")
problems = [r for r in results if r.status != checks.Status.OK]
overall, banner = moves.banner_message(results)
{checks.Status.OK: st.success, checks.Status.WARN: st.warning, checks.Status.FAIL: st.error}[overall](banner)
if problems:
    with st.expander("Check details"):
        st.dataframe(
            pd.DataFrame([{"status": r.status.name, "check": r.check, "ticker": r.ticker, "detail": r.detail}
                          for r in sorted(problems, key=lambda r: -r.status)]),
            hide_index=True, width="stretch",
        )

st.markdown("**Try to break it:** inject a bad print and watch the checks catch it. "
            "[Open the demo](#try-to-break-it)")

# ---- 2. Latest change by asset class ----
KEY_MARKETS = ["ES=F", "^TNX", "DX-Y.NYB", "CL=F", "GC=F", "^VIX"]
main_instruments = [i for i in cfg["instruments"] if not i.get("reference")]
rows = [moves.build_row(inst, prices, results, cfg) for inst in main_instruments]
table = pd.DataFrame(rows)

by_key = table.set_index("ticker")
tiles = [t for t in KEY_MARKETS if t in by_key.index and pd.notna(by_key.loc[t, "last"])]
# A wrapping row, so tile values stay whole on narrower screens
with st.container(horizontal=True):
    for t in tiles:
        row = by_key.loc[t]
        st.metric(f"{row['name']} {row['flag']}".strip(), row["last"], row["Change"], border=True, width=195,
                  chart_data=row["trend"], chart_type="line",
                  help=f"{row['from → to']} ({row['basis']}). The line shows the last {moves.TREND_DAYS} closes.")

# Fixed pixel widths that add up to fit a 1024px screen with no column clipped
COLUMNS = {
    "name": st.column_config.TextColumn("Instrument", width=140),
    "last": st.column_config.TextColumn("Last", width=70),
    "Change": st.column_config.TextColumn("Change", width=65),
    "trend": st.column_config.LineChartColumn(f"{moves.TREND_DAYS}d trend", width=65),
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
st.caption(f"{n_single} of {len(main_instruments)} instruments are single source: "
           "passing checks means they look plausible, not that a second source agrees.")

# ---- 3. How unusual is today? Comparable across assets, unlike raw percentages ----
st.subheader("How unusual is today?")
ranked, too_short = ranking.unusual_moves(prices, cfg)
if ranked.empty:
    st.info("Not enough history to rank today's moves yet.")
else:
    st.altair_chart(ranking.chart(ranked, cfg["checks"]), width="stretch")
    note = ("Each move is measured against that instrument's own recent volatility, using the sanity check's number. "
            "Moves cover different periods by market; see the tables above.")
    st.caption(note + (f" Not enough history to rank: {', '.join(too_short)}." if too_short else ""))

# ---- 4. Try to break it: real checks on a throwaway copy of the data ----
st.subheader("Try to break it", anchor="try-to-break-it")
st.caption("Inject a fault into an in-memory copy of the data and rerun the real checks. Results are simulated: "
           "nothing is saved, and the banner at the top of this page doesn't change.")
with st.container(border=True):
    breakable = [i for i in main_instruments if (prices["ticker"] == i["ticker"]).sum() >= 2]
    if breakable:
        names = [i["name"] for i in breakable]
        pick, fault_pick = st.columns(2)
        name = pick.selectbox("Instrument", names, index=names.index("Gold") if "Gold" in names else 0, key="demo_instrument")
        inst = breakable[names.index(name)]
        labels = [demo.FAULTS[f] for f in demo.faults_for(inst)]
        fault_label = fault_pick.selectbox("Fault", labels, key="demo_fault")
        if st.button("Inject fault (simulated)", key="demo_inject"):
            fault = next(k for k, v in demo.FAULTS.items() if v == fault_label)
            sim = demo.simulate(prices, cfg, inst["ticker"], fault, datetime.now(timezone.utc))
            st.markdown("**Simulated result. Real data is unchanged.**")
            {checks.Status.OK: st.success, checks.Status.WARN: st.warning, checks.Status.FAIL: st.error}[sim.status_after](sim.banner)
            if sim.findings:
                for finding in sim.findings:
                    st.markdown(f"- {finding.text}")
            else:
                st.info(sim.message)
            st.markdown(sim.row_text)
    else:
        st.info("Not enough data to run the demo yet.")

# ---- 5. News brief with sources ----
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

# ---- 6. How the page checks itself ----
st.divider()
with st.expander("How the data checks work"):
    st.markdown("""
- **Completeness:** every instrument arrived with enough history and no bad values.
- **Freshness:** the latest row is from the session we expect.
- **Gaps:** no business days are missing from recent history.
- **Sanity:** today's move is plausible for that instrument, and the price isn't frozen.
- **Reconciliation:** two sources for the same series agree.
""")
st.caption("Second-source data retrieved from FRED, Federal Reserve Bank of St. Louis, which does not endorse this page. "
           "VIX: Chicago Board Options Exchange, CBOE Volatility Index [VIXCLS]. "
           "Copyright, 2016, Chicago Board Options Exchange, Inc. Reprinted with permission.")
st.caption("Built from free public sources, not production market data. "
           "[Source code and build notes](https://github.com/KC31415/morning-brief)")
