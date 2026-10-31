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
