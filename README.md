# Morning Brief

![tests](https://github.com/KC31415/morning-brief/actions/workflows/ci.yml/badge.svg)

**Live app:** https://kechun-morning-brief.streamlit.app

A pre-open market dashboard that puts the latest cross-asset moves and a short, sourced news brief on one page, and **tells you when its own data is wrong.**

This is a public rebuild of a dashboard I built during my 2026 sales & trading internship, which 30+ traders and salespeople used every morning. That version had one real weakness: when a data source arrived late or incomplete, the page still loaded and looked normal. This version is built around fixing that. No code or data from the original is used here; everything runs on free public sources.

![screenshot](docs/screenshot.png)

## What it does

- **Latest change** for 21 instruments across equities, rates, FX and commodities (% change for prices, basis points for yields), each labeled with its from → to dates and basis: live, last session or prior US session
- **Source and cross-check** on every row, showing the second source's value and date, or "single source"
- **Data status banner** at the top: green if every check passes, yellow for warnings, red if something failed, with details on exactly which series and why
- **Stale-page banner:** red if the last fetch is more than one business day old, whatever the checks say
- **News brief:** 0–5 LLM-written bullets on what matters for the open, each linked to the headlines it came from
- **Runs itself** every weekday before the open via GitHub Actions, opening a GitHub issue on any FAIL and closing it after the next clean run

## Data checks

Every refresh runs these before anything is displayed:

| Check | What it catches | Example |
|---|---|---|
| Freshness | A feed that didn't update | Copper's latest close is 3 business days old → FAIL |
| Completeness | A ticker with no stored data, too little history, or zero or missing prices | New ticker has no rows → FAIL; only 1 row → WARN |
| Gaps | Holes in recent history | 5 missing sessions in the last 60 → WARN; market holidays don't count |
| Sanity | Moves too large to be real | A 1%-vol asset "moves" 50% → FAIL, almost certainly bad data |
| Frozen feed | A price that hasn't changed in two weeks | Last 10 daily changes all zero → FAIL |
| Reconciliation | Two sources disagreeing | Yields, VIX, USD/JPY, GBP/USD and WTI vs FRED; EUR/USD vs the ECB. 10Y differs by ≥15bp → FAIL |

Results are stored in a `check_runs` table, so I can query how often each feed has problems:

```sql
SELECT ticker, check_name, COUNT(*) AS failures
FROM check_runs WHERE status = 'FAIL'
GROUP BY 1, 2 ORDER BY failures DESC;
```

## LLM summary guardrails

- The model sees only the headlines passed in and is told not to add outside facts
- Every bullet must cite headline IDs; bullets citing IDs that were never sent are dropped automatically
- Prompts and raw responses are saved so summaries can be reviewed afterward
- With no API key or on any error, the page falls back to raw headlines instead of breaking

## How it works

```
scripts/refresh.py            runs the pipeline once
  ingest.py                   yfinance + FRED + ECB -> one table
  storage.py                  SQLite (prices, check_runs)
  checks.py                   data quality checks
  news.py / summarize.py      RSS headlines -> cited LLM bullets
app.py                        Streamlit dashboard
.github/workflows/refresh.yml weekday pre-open schedule
.github/workflows/ci.yml      tests on every push
```

## Run it locally

```bash
pip install -r requirements.txt
export ANTHROPIC_API_KEY=...      # optional; without it you get headlines only
python scripts/refresh.py
streamlit run app.py
pytest -q
```

## Known limitations

- Freshness and gap checks use market holiday calendars matched to what each source publishes, but sources don't follow them perfectly: Yahoo's Euro Stoxx 50 skipped about 7 days in two years that Xetra's calendar counts as sessions, and FRED rates can skip or include Good Friday. One-off days can still WARN.
- yfinance triggers a pandas deprecation warning (`sort_index(inplace=True)`) on every ticker. It clutters the log but breaks nothing today; it may fail once pandas removes that keyword.
- Free data sources have delays and occasional bad prints. That is part of why the checks exist, but this is not production market data.
- Sanity thresholds (4 and 10 standard deviations) are judgment calls, not tuned.
- I check LLM summaries by reading them against the cited headlines, not with an automated accuracy test.

## What I'd do differently / next

The starter code passed all 21 of its tests and still couldn’t finish a real refresh: the tests used timezone-free times, and production didn’t. Since then I test with the same kinds of inputs the code sees in production, and I run against live data early. Next I’d tune the sanity thresholds on more live history, since right now they’re judgment calls. Reading the AI summaries by hand taught me that citation checks prove a headline exists, not that it supports the bullet. And I’d look for a licensed news source, because sticking to official feeds with clear reuse terms often leaves the brief empty.

## Built with

Python, pandas, SQLite, Streamlit and GitHub Actions, with data from yfinance, FRED, the ECB and official RSS feeds. The starter code was generated with Claude. I then used Claude Code to find and fix bugs, one commit and regression test at a time. Most bugs only appeared on real data, like a crash when the API response started with a thinking block instead of text. Each bug, how it was found, and what changed is logged in docs/build-notes.md.
