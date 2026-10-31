# Build notes

Bugs found while building this, how each was found, and what changed.

## 1. Timezone crash in the checks

- **What broke:** `refresh.py` and `app.py` pass `datetime.now(timezone.utc)` as `as_of`, but stored dates are naive. Comparing them in `bdays_between` raised `TypeError`, so no real refresh could finish the check step.
- **How it was found:** calling `run_all` with a timezone-aware time on synthetic data. The existing tests missed it because they all used a naive `AS_OF`.
- **What changed:** `expected_session` converts an aware `as_of` to New York time and drops the timezone. A naive `as_of` is used as given. New York rather than UTC, so the same instant gives the same session whichever zone it is written in, and the "US business day" means what it says.

## 2. NaN close crashing the upsert

- **What broke:** yfinance can return a row with a NaN close. SQLite stores NaN as NULL, which violates `close REAL NOT NULL`, so one bad row raised `IntegrityError` and stopped the whole refresh, despite the promise that one bad ticker never stops the run.
- **How it was found:** passing a NaN close to `upsert_prices` on an in-memory database, after noticing that only the FRED path dropped missing values.
- **What changed:** `fetch_yfinance` logs how many NaN closes a ticker returned and drops them. A ticker with only NaN closes is treated like one with no rows, so the freshness and completeness checks report it.

## 3. Unparseable LLM JSON losing the prompt and raw response

- **What broke:** `result.update(prompt=..., raw_response=..., bullets=validate(...))` evaluates `validate` first. When the model returned bad JSON, `validate` raised before anything was saved, so the response was lost in exactly the case where it most needed reviewing.
- **How it was found:** running `summarize` with a fake client that returned "not json" and seeing both fields come back as `None`, while the README said they were saved.
- **What changed:** the prompt is saved before the API call and the raw response is saved before validation. An API failure now keeps the prompt too.

## 4. Table not flagging ^TNX when reconciliation fails

- **What broke:** a reconciliation result is labeled `^TNX vs DGS10`, but the table looks up flags by a single ticker. The banner showed the failure while both rows in the table looked clean.
- **How it was found:** reading how `app.py` builds its flags, then confirming with a test that runs the real page through Streamlit's `AppTest` on a temporary database with the two series 100bp apart.
- **What changed:** new `checks.worst_by_ticker` counts a reconciliation result against both tickers in the pair, and `app.py` uses it. We can't tell from the gap alone which source is wrong, so both get flagged.

## 5. Frozen-feed check needing the whole window flat

- **What broke:** the check only fired when the standard deviation of the whole 60-change history was zero. A price flat for the last 40 sessions still passed, and freshness didn't catch it because the dates kept advancing.
- **How it was found:** flattening the tail of a synthetic series by different lengths and watching the sanity result stay OK.
- **What changed:** sanity also FAILs when the last 10 changes are all zero (`frozen_changes` in the config). That's two trading weeks, which is long enough that an unchanged close is very unlikely to be real. The whole-window test stays, for a long flat run followed by a single move.

## 6. A bad print inflating its own baseline

- **What broke:** the sanity check divided by the standard deviation of recent changes, which a single outlier inflates. A +50% bad print scored 51.9σ on the day, but the reversal the next day scored only 4.9σ, because the print was now in the baseline. That was just a WARN.
- **How it was found:** putting the bad print one day before the latest row of a synthetic series.
- **What changed:** new `robust_vol` uses the median absolute deviation scaled by 1.4826, so the 4 and 10 thresholds still read as standard deviations on normal data. The reversal now FAILs. If over half the changes are zero the MAD is 0, so it falls back to the standard deviation; otherwise a sticky series would score infinite on any move.
- **Trade-off:** the MAD ignores the tails, so it flags more real moves. On simulated Student-t returns (3 degrees of freedom, 60-day window), WARN-or-worse rose from 0.93% to 2.24% of instrument-days and FAIL from 0.06% to 0.15%. Across 23 instruments that's roughly one false FAIL a month if returns really are that fat-tailed. Check this against live data before trusting the thresholds.

## 7. Python version mismatch

- **What broke:** nothing failed yet, but the local venv ran Python 3.14 while `ci.yml` and `refresh.yml` use 3.12. Passing locally didn't show that the code works where it actually runs.
- **How it was found:** comparing `python --version` in the venv with the workflow files during setup.
- **What changed:** installed Python 3.12 with Homebrew and rebuilt `.venv` with it. New `tests/test_environment.py` fails if the running Python differs from either workflow, so the two can't drift apart unnoticed.

## 8. Changes that covered different periods with no label

- **What broke:** the README called these "overnight moves", and each row compares a ticker's last two rows. At the pre-open that mixes moves still in progress, finished Asian sessions and yesterday's US yields, and the table gave no way to tell them apart. The table's column was already called `change`, so the misleading word was in the README and a code comment.
- **How it was found:** the first live run, plus replaying which hourly bars existed before 11:00 UTC on a Friday.
- **What changed:** the column is now "Change", with new "from → to" and "basis" columns. `moves.change_basis` compares each row's `fetched_at` with its market's close, set per session in the config, so the label follows the data. Futures fetched on a Saturday say "last session", not "live". This labels the mix but doesn't remove it: `live` means the session was open when fetched, not that the price is current.

## 9. USD/CNH removed

- **What broke:** Yahoo returned only one row for `USDCNH=X`, and `CNH=X` was the same. `CNH=F` had 33 rows, and `USDCNY=X` is onshore yuan, which is a different rate.
- **How it was found:** the first live run warned on gaps and sanity for this ticker, and I tried the alternatives directly.
- **What changed:** removed from the config with no replacement. Removing it exposed a second bug: `check_gaps` looped over every ticker in the database, so old CNH rows would have kept warning. `run_all` now only judges configured tickers.

## 10. Weekend-dated rows

- **What broke:** a Saturday run stored a GBP/USD row dated Saturday, so its change ran Friday to Saturday while EUR/USD's ran Thursday to Friday.
- **How it was found:** the from and to dates of each ticker's last two rows, after the first live run.
- **What changed:** `fetch_all` drops weekend-dated rows from every source and logs a warning per ticker. This filters new data only, so a row already in a database stays there.

## 11. Row flags disagreeing with the banner

- **What broke:** `app.py` hard-coded ❌ for any ticker with fewer than two rows, while the banner used the check results. USD/CNH showed ❌ under a yellow banner. Completeness also passed it with a single row.
- **How it was found:** reading the rendered table from the first live run next to its banner.
- **What changed:** every row's flag now comes from the same check results as the banner. Completeness WARNs below `min_rows` (22), the history the sanity check needs for 21 changes. A ticker with no data at all still FAILs.

## 12. More reconciliation pairs

- **What was missing:** only the 10Y yield had a second source, so a wrong value anywhere else could look fine.
- **How it was found:** reviewing how credible free data is. Bloomberg can't feed a public cloud app, so official sources became the cross-check.
- **What changed:** added `^FVX` vs `DGS5`, `^IRX` vs `DTB3` and `EURUSD=X` vs the ECB reference rate, plus a new `fetch_ecb`. The new series also appear as table rows, like `DGS10` already did.
- **Choosing the 3M series:** `DGS3MO` differed from `^IRX` by about 16bp on average, enough to FAIL almost every day. `DTB3` differed by about 1bp. Going by those numbers and how the series are defined, the gap is quoting basis: `DTB3` and `^IRX` are on a discount basis, while `DGS3MO` is a bond-equivalent yield.
- **Tolerances:** measured over about 120 sessions on Oct 31, 2026. Warn sits just above the largest gap seen, and fail is about 3x warn.

| Pair | Median gap | 95th pct | Max | Warn | Fail |
|---|---|---|---|---|---|
| `^TNX` vs `DGS10` | 0.006 | 0.020 | 0.048 | 0.05 | 0.15 |
| `^FVX` vs `DGS5` | 0.007 | 0.020 | 0.041 | 0.05 | 0.15 |
| `^IRX` vs `DTB3` | 0.010 | 0.039 | 0.060 | 0.08 | 0.24 |
| `EURUSD=X` vs ECB | 0.0013 | 0.0040 | 0.0077 | 0.01 | 0.03 |

These cover one stretch of about 120 sessions, so a more stressed period could widen the gaps. The EUR/USD gap is mostly timing: the ECB fixes around 14:15 CET, while Yahoo's row closes later or is still live.

## 13. Source column and "unverified" marking

- **What was missing:** a green banner implied every number had been verified, but most instruments have only one source. Checks on those can show a value looks plausible, not that it's right.
- **How it was found:** listing which instruments the reconciliation pairs actually cover.
- **What changed:** new "source" and "cross-check" columns. Cross-check names the second source, or says "unverified". A caption under the tables gives the single-source count.

## 14. Known limitations documented, not fixed

- **What:** the Nikkei holiday gaps and yfinance's pandas deprecation warning, both seen on the first live run.
- **What changed:** added both to the README's known limitations. No code change, by choice.
