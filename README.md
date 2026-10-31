# Morning Brief

![tests](https://github.com/YOUR_USERNAME/morning-brief/actions/workflows/ci.yml/badge.svg)

**Live app:** YOUR_STREAMLIT_URL

A pre-open market dashboard that puts the latest cross-asset moves and a short, sourced news brief on one page, and **tells you when its own data is wrong.**

This is a public rebuild of a dashboard I built during my 2026 sales & trading internship, which 30+ traders and salespeople used every morning. That version had one real weakness: when a data source arrived late or incomplete, the page still loaded and looked normal. This version is built around fixing that. No code or data from the original is used here; everything runs on free public sources.

![screenshot](docs/screenshot.png)

## What it does

- **Latest change** for ~25 instruments across equities, rates, FX and commodities (% change for prices, basis points for yields), each labeled with its from → to dates and basis: live, last session or prior US session
- **Data status banner** at the top: green if every check passes, yellow for warnings, red if something failed, with details on exactly which series and why
- **News brief:** 3–5 LLM-written bullets on what matters for the open, each linked to the headlines it came from
- **Runs itself** every weekday before the open via GitHub Actions

## Data checks

Every refresh runs these before anything is displayed:

| Check | What it catches | Example |
|---|---|---|
| Freshness | A feed that didn't update | Copper's latest close is 3 business days old → FAIL |
| Completeness | A ticker that never arrived, zero or missing prices | Wheat returned no rows → FAIL |
| Gaps | Holes in recent history | 5 missing days in the last 60 → WARN |
| Sanity | Moves too large to be real | A 1%-vol asset "moves" 50% → FAIL, almost certainly bad data |
| Frozen feed | A price that hasn't changed in two weeks | Last 10 daily changes all zero → FAIL |
| Reconciliation | Two sources disagreeing | 10Y yield from Yahoo vs FRED differs by >15bp → FAIL |

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
  ingest.py                   yfinance + FRED -> one table
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

- Freshness and gap checks use weekday calendars, not exchange holiday calendars, so a holiday (especially for Nikkei and Hang Seng) shows as a warning. I chose a false WARN over a missed real problem; exchange calendars are the next fix.
- Free data sources have delays and occasional bad prints. That is part of why the checks exist, but this is not production market data.
- Sanity thresholds (4 and 10 standard deviations) are judgment calls, not tuned.
- I check LLM summaries by reading them against the cited headlines, not with an automated accuracy test.

## What I'd do differently / next

YOUR OWN WORDS: what you learned building this version, where Claude Code helped or was wrong, what you'd change.

## Built with

Python, pandas, SQLite, Streamlit, GitHub Actions. I used Claude Code throughout; see notes on where it helped and where I had to correct it: YOUR NOTES.
