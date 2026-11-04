# Build notes

Bugs found while building this, how each was found, and what changed.

## Judgment calls at a glance

The decisions an interviewer is most likely to ask about, and where each is argued.

| Decision | What I chose | Why, in one line | Entry |
|---|---|---|---|
| Sanity check's volatility | Median absolute deviation, not standard deviation | One bad print can't inflate its own baseline; costs more false WARNs on fat tails | 6 |
| Reconciliation tolerances | Warn just above the largest measured gap, fail at about 3x | Set from ~120 to ~500 shared days of data, not picked by hand | 12, 21 |
| 3M T-bill reference | `DTB3`, not `DGS3MO` | Same discount-basis quoting as `^IRX`: 1bp typical gap vs 16bp | 12 |
| "single source" wording | Not "unverified" | A single-source value isn't known to be wrong, only unchecked | 21 |
| Nikkei cross-check | Left out | FRED's notes say redistribution needs Nikkei's permission | 21 |
| VIX cross-check | Kept, with FRED's required notice | Treated as personal non-commercial use; one config line to remove | 21 |
| Stooq, CNBC, Investing.com, FT, WSJ | Not used | Their terms bar redistribution, or they're subscription publishers | 19, 21 |
| BLS (CPI, jobs) | Not covered, and the page says so daily | It returns 403 to automated requests; I didn't work around that | 19, 27 |
| Futures holiday calendar | `XNYS`, not `CMES` | Matches the dates Yahoo actually publishes: 0 misses vs 13 | 22 |
| News brief | 0 to 5 bullets, may be empty | A prompt demanding 3 to 5 made the model pad with speculation | 17 |
| Schedule panel | No LLM; only times the source printed | A guessed release time on a trading page is worse than none | 27 |
| Missed or late refresh | Outside trigger + guard + dead-man's switch | GitHub's cron missed three days, then ran 7h20m late | 28, 29, 31 |
| Chart scale | Scaled to the data, FAIL named at the edge | Drawing a 10σ line on every quiet day left most of the chart empty | 26, 33 |
| Database in git | Kept, for now | Simplest way to serve Streamlit Cloud; history grows about 90 KB a run | 35 |

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

## 15. Thinking block breaking the LLM summary

- **What broke:** `summarize.py` assumed `msg.content[0]` was a text block. The API can return a thinking block first, which has no `.text`, so a successful response raised `AttributeError` and the page got no bullets. The existing `except` caught it, so the run fell back to headlines, but the response was lost.
- **How it was found:** the first refresh with a real API key returned HTTP 200 and then logged this error. Earlier tests used a mocked response containing only a text block, so they couldn't catch it.
- **What changed:** the code now takes the first block where `type == "text"`. If there's none, it saves the error "summary failed: response had no text block" and keeps the prompt. New tests cover a thinking block followed by text, and a thinking block alone.

## 16. Raising max_tokens to 2000

- **Why:** thinking counts toward `max_tokens`. At 800, the model could use most or all of the limit on thinking, leaving no text block or JSON cut off mid-way, and either one loses the bullets.
- **How it was found:** reviewing the limit while fixing the thinking-block bug. It hasn't been seen failing on a real response.
- **What changed:** `max_tokens` went from 800 to 2000. That leaves much more room but isn't a guarantee, so the "no text block" and parse errors stay in place as the fallback.

## 17. Padded news bullets

- **What broke:** the live summary worked, but it padded irrelevant personal-finance headlines with speculation, such as "may be relevant to healthcare-exposed names at the open." The prompt demanded 3 to 5 bullets, so it had to produce them even with nothing to say, and the only feed returning items was mostly personal finance.
- **How it was found:** reading the live bullets against their headlines by hand. No automated check caught it, and none could have: citation validation proves a headline exists, not that it supports the bullet. Those padded bullets cited real headlines and passed.
- **Why the Fed and CNBC feeds returned 0 items:** the 18-hour cutoff on a weekend, not broken URLs. Checked on Saturday Oct 31 at 17:32 UTC, when the cutoff was Friday 23:32 UTC. Both returned HTTP 200 with items (Fed 20, CNBC 30), but the newest were Thursday 20:30 and Friday 11:16 UTC. The Fed feed's parser warning is a harmless charset mismatch, and its entries still parse.
- **Feeds:** replaced MarketWatch top stories with FT Markets, WSJ Markets and Investing.com stock news. Through `fetch_headlines` at that time they returned 8, 1 and 10 items inside the cutoff.
- **Prompt:** now asks for 0 to 5 bullets, says what counts as market news, returns `[]` if nothing qualifies, and forbids phrasing like "may be relevant" or "could affect" unless the headline itself says it.
- **Page:** an empty list shows "No market-moving headlines overnight". If validation drops every bullet, the run now records an error, so bad citations can't look like a quiet night.
- **Limits:** the tests check the prompt's wording and how the code handles an empty answer, not whether the model obeys. Only reading live output can check that, so manual review stays. The feeds can't be tested offline, and the 18-hour cutoff also means a Monday pre-open run misses Friday afternoon's news.

## 18. News cutoff missing Friday afternoon

- **What broke:** a flat 18-hour lookback meant a Monday 7am run only reached Sunday afternoon, so anything published after Friday's close was lost.
- **How it was found:** working through why the Fed and CNBC feeds were empty on a Saturday.
- **What changed:** the cutoff is now 4pm New York on the prior business day. Friday's close on Monday, the previous day's close otherwise. It ignores exchange holidays, like the freshness check.

## 19. Replacing news feeds for public deployment

- **Why:** a public page republishes each feed's headlines and summaries of them, so a feed being reachable isn't enough. I read each publisher's terms on Oct 31, 2026. This is my reading, not legal advice.

| Feed | What the terms say | Decision |
|---|---|---|
| Federal Reserve | Website information is public domain unless otherwise indicated, and may be copied with the Board cited | Keep |
| ECB | Free use if reproduced accurately with the ECB cited as source | Add |
| EIA | US government publications are public domain; acknowledge the source and date | Add |
| BEA | No reuse statement found on the page I read; relying on the general rule that US federal government works aren't copyrighted | Add |
| CNBC | NBCUniversal terms give a personal-use license and bar other use without written agreement | Remove |
| Investing.com | Prohibits using or displaying its data without written permission | Remove |
| FT, WSJ | Subscription publishers, removed by decision; I didn't read their terms | Remove |

- **What changed:** the feeds are now Fed, ECB, BEA and EIA Today in Energy. Each returned items when checked, but the newest were 1 to 2 days old on a Saturday. BLS and USDA returned 403 to the feed parser, and Treasury's feed URL returned 404, so they aren't included.
- **Trade-off:** the brief now only covers official releases, not market news like company results, and it will often be empty. That's the cost of a public page. The empty-list message handles it honestly.
- **Attribution:** the headline list shows each source's name, publication date and link, which covers EIA's request for the date. The ECB asks for accuracy, which an LLM summary can't guarantee, so the "check sources" caption matters.

## 20. Reference series moved out of the tables

- **What was wrong:** the second-source series (FRED 10Y, 5Y and 3M, ECB EUR/USD) had their own table rows, so the page listed the same market twice with different dates and read like more instruments than it has.
- **How it was found:** reviewing the dashboard as an employer would see it.
- **What changed:** those series are marked `reference: true`. They are still fetched and checked, and reconciliation logic is unchanged, but each now appears in its main row's cross-check cell, e.g. "✓ FRED 4.980 (Thu 10-29)". The value and date are the ones reconciliation compares: the last date both sources share. The date is shown in full because a weekday alone would be misleading once a reference is more than a week old.
- **Knock-on fix:** with no row of its own, a reference series' warning would have appeared in the banner with no flagged row. `worst_by_ticker` now rolls those problems up to the main row.

## 21. More FRED cross-checks, and "single source"

- **What was missing:** most instruments had no second source, including ones where a free official series exists.
- **How it was found:** the count of unverified rows on the page, 17 of 25.
- **What changed:** added VIX vs `VIXCLS`, USD/JPY vs `DEXJPUS`, GBP/USD vs `DEXUSUK` and WTI vs `DCOILWTICO`. "unverified" is now "single source", because a single-source value isn't known to be wrong, only unchecked. The footer now reads 13 of 21 and carries the FRED and CBOE citation. Stock index futures aren't compared to cash indices, because basis and hours would make any gap meaningless as a data check.
- **Measured gaps** (Yahoo vs FRED, about 490 to 500 shared days to Oct 2026). Warn sits just above the largest gap, and fail at 3x warn, except for VIX.

| Pair | Median gap | 95th pct | Max | Warn | Fail |
|---|---|---|---|---|---|
| `^VIX` vs `VIXCLS` | 0.00 | 0.00 | 2.61 | 0.05 | 0.50 |
| `USDJPY=X` vs `DEXJPUS` | 0.41 | 1.56 | 3.83 | 4.0 | 12.0 |
| `GBPUSD=X` vs `DEXUSUK` | 0.0034 | 0.0099 | 0.0182 | 0.02 | 0.06 |
| `CL=F` vs `DCOILWTICO` | 0.78 | 3.82 | 7.18 | 8.0 | 24.0 |

- **A real disagreement in the history:** VIX matches exactly on every other shared day, but on Feb 6, 2026 Yahoo says 20.37 and FRED says 17.76, with 17.36 the next session. So I set the VIX tolerance from the normal zero gap, not the outlier, and this check would have failed that day. I can't tell from these two sources alone which is right.
- **Conventions and timing:** FRED's H.10 FX rates are noon New York buying rates, while Yahoo's row closes later, so the gap is mostly timing. Quoting matches: yen per dollar and dollars per pound. FX references publish weekly and WTI spot weekly, so they get `lag_bdays`, and a comparison can be about a week old; the cell shows its date.
- **Weak check:** WTI compares a front-month future with Cushing spot. Yahoo averaged $2.63 below spot over the last 120 sessions and differed by up to $7.18, so this catches gross errors like a wrong unit or symbol, not ordinary bad prints.
- **Nikkei left out on purpose:** the `^N225` vs `NIKKEI225` gap never exceeded 0.004, so it would be an excellent check. But FRED's notes say redistributing that data needs permission from Nikkei, and this project publishes both the value and its database. It stays single source unless Nikkei agrees.
- **VIX is a judgment call:** `VIXCLS` is tagged "Copyrighted: Citation Required". FRED's FAQ says copyrighted series need the owner's permission beyond your own personal use, while allowing use on personal blogs with citation and the notice. I treated this non-commercial portfolio page as personal use and included both. Removing the pair is a small config change if that's wrong.
- **FRED access:** the terms ban scraping and extraction and describe apps as using the API. This project downloads a small subset as CSV, and moving to the API with a free key would be cleaner before anything commercial.
- **Stooq rejected:** its terms (section 5.3) don't allow redistribution without consent, so it isn't an option for a public page without written permission.

## 22. Holiday calendars in the freshness and gap checks

- **What broke:** both checks assumed every weekday was a session. Nikkei always showed 5 "missing" days, all Japanese holidays, and a WARN that lingered for about 12 weeks. Any holiday could also make a market look stale.
- **How it was found:** the Nikkei gap warning on every live run, compared against the exchange's calendar.
- **What changed:** new `calendars.py`, using `exchange_calendars` plus three custom calendars. Each market session in the config names a calendar, and a series can override it. Freshness and gaps now count sessions, not weekdays.
- **How the calendars were chosen:** by comparing about two years of each source's real dates against candidates, because the right calendar is the one the source follows, not the one that sounds right.

| Series | Calendar | Expected dates missing in 2 years |
|---|---|---|
| Nikkei, Hang Seng | `XTKS`, `XHKG` | 0 |
| Yahoo yields, VIX, futures, Dollar index | `XNYS` | 0 |
| `DEXJPUS`, `DEXUSUK`, `ECB_EURUSD` | `USFED`, `USFED`, `TARGET` | 0 |
| `DGS10`, `DGS5`, `DTB3` | `USFED` | 1 (Good Friday 2025) |
| `DCOILWTICO` | `XNYS` | 3 |
| EUR/USD, USD/JPY, GBP/USD on Yahoo | `FX` | 2 (Good Friday and Easter Monday 2025) |
| Euro Stoxx 50 | `XETR` | 7 |

- **Futures and FX:** CME futures trade through most US holidays, yet Yahoo's futures had no row on them. `CMES` would have flagged 13 false misses in two years, while `XNYS` gave none, so futures follow `XNYS`. It describes Yahoo's data, not CME's actual hours. No exchange covers FX, so `FX` is weekdays minus Jan 1 and Dec 25, the two recurring days Yahoo had no row.
- **Remaining limits:** Euro Stoxx has no exact calendar. Its 7 misses include dates like May 14 and 25, 2026, and I couldn't confirm why Yahoo skipped them. They stay under the gap threshold of 3 unless they cluster. The `exchange_calendars` holidays are maintained by that project, so a late-announced closure could be wrong until it updates.
- **Result on real data:** with the stored database, the checks went from one Nikkei WARN to all passing. `exchange_calendars` itself triggers pandas deprecation warnings, like yfinance, which are harmless for now. That also made one README sentence false, "Next I'd add exchange holiday calendars", so it came out.

## 23. Stale-page banner

- **What was wrong:** the checks only see what's in the database. If the scheduled refresh stopped, freshness would eventually flag each ticker, but nothing said plainly that the page itself hadn't been updated.
- **How it was found:** reviewing what a visitor would see if GitHub Actions stopped running.
- **What changed:** a red banner appears above the status banner when the last fetch is more than one weekday old, whatever the other checks say, with the time it was last updated. It uses New York dates and plain weekdays rather than a market calendar, because the schedule runs on weekdays, holidays included. A Friday fetch is fine on Monday and stale on Tuesday.

## 24. GitHub issue on FAIL

- **What was missing:** a FAIL turned the Actions run red and showed on the page, but nobody was told unless they went looking.
- **How it was found:** asking what would happen to a failure on a day no one opened the page.
- **What changed:** `refresh.py` writes its FAILs to `data/check_report.json` (not committed). A new workflow step, `scripts/alert.py`, then keeps one issue titled "Data checks failing" in sync. It opens the issue on a FAIL, updates it with a comment if the list changes, leaves it alone if nothing changed, and closes it on the next run with no FAILs. WARNs don't count.
- **Decisions:** the step runs even if an earlier one failed. A missing report counts as a failure, so a crash can't look like a clean run or quietly close an open issue. Duplicates are prevented by checking open issues for that exact title, so renaming or retitling the issue by hand would create a new one.
- **Not tested on GitHub yet:** the tests use a fake `gh` and parse the workflow file, so the first real proof is a run on GitHub.

## 25. "Try to break it" demo

- **Why:** the project's claim is that the page catches its own bad data, and a visitor can now test that directly instead of taking my word for it.
- **What changed:** new `demo.py` applies a fault (a +50% or +2% bad print, a frozen feed, a stale ticker, or a yield scaled ×10) to a copy of the prices and runs the real `run_all` on it. The panel shows which check caught it, what it measured against what threshold, and how the banner and that row would change. To share logic rather than copy it, `banner_message` and `build_row` moved from `app.py` to `moves.py`, and `latest_move_z` from `check_sanity` to its own function.
- **Safety:** the demo never receives the database connection and doesn't import `storage`. Tests compare the database rows, `check_runs` and the file's hash before and after a simulation on the real page, and confirm the real banner doesn't change. Every result line says "Simulated".
- **Honest misses:** the +2% print exists to show a fault that gets through. When nothing trips, the page says so and gives the measurement. A ×10 yield is applied to the whole feed, because that's how a unit error behaves, so sanity doesn't notice and only reconciliation catches it, which is a good argument for having a second source.

## 26. "How unusual is today?" ranking

- **Why:** a −3.3% move in gold and a +12.9% move in VIX can't be compared as percentages. Measuring each against its own recent volatility answers the question a trader asks first: what's actually abnormal?
- **What changed:** new `ranking.py` builds a horizontal bar chart of main instruments, most unusual first, with each bar labeled like "Gold −3.29%, 3.7σ" and dashed lines at the WARN and FAIL thresholds. The value comes from `latest_move_z`, the same function the sanity check uses, and a test confirms the two agree. The chart's scale always keeps the FAIL line visible on a quiet day.
- **Limit:** the moves cover different periods by market, so a live overnight move can rank next to a completed session. The caption says so. Instruments with too little history are named, not silently dropped.
- **Requirement change:** `st.altair_chart` first accepts `width` in Streamlit 1.51, so the minimum went from 1.49 to 1.51. The full suite ran on 1.51.0.
- **Layout:** checked at 1024px and 1440px, with no clipped labels. Checking also showed the demo's invitation was below the fold, under the tiles, so it moved up to directly below the banner.

## 27. "What's scheduled today" panel

- **Why:** a pre-open page should say what's coming, and the project's standard applies here too: official sources, no guessed values, and a clear difference between "nothing is scheduled" and "I couldn't find out".
- **Sources, tested live Nov 1, 2026** (three straight fetches, about 1.4 seconds in all). I couldn't test from GitHub's servers, so those runs are the first real proof there.

| Source | What it gives | Times published? | Reuse terms | Result |
|---|---|---|---|---|
| BEA release schedule | News releases | Yes | No statement found on the pages I read; relying on the general rule that US federal works aren't copyrighted | Used |
| Census indicator calendar | Indicators and period | Yes | Same general rule. The terms page I found covers its API, not this page, and bars implying endorsement | Used |
| FOMC calendar | Meeting dates | No | Federal Reserve Board: public domain unless otherwise indicated, cite the Board | Used |
| ECB meeting calendar | Monetary policy meetings only | No | Free use if accurate and cited | Used |
| TreasuryDirect upcoming auctions | Auctions | Only once announced in full | Same general rule; its legal pages returned 404 to me | Used |
| BLS release schedule | CPI, jobs | n/a | Not reached | **Not used: returns 403** |
| Treasury Fiscal Data upcoming auctions | Auctions | No | n/a | Not used: oldest records come first and it adds no times |

- **The BLS gap matters:** CPI and jobs reports are among the biggest scheduled events, and BLS refused requests even with a clear user agent, so I didn't try to get around it. The panel always says BLS isn't covered and links to its schedule, because "no events today" could otherwise be badly misleading on a CPI morning.
- **What changed:** new `schedules.py` fetches during `refresh.py`, never on page load, and stores results in two new tables: `schedule_events` (event, date, time, source, link) and `schedule_status` (last attempt, last success, error). The page shows today in New York time, sorted by time, each with its source link, and the next 5 business days in a collapsed section.
- **Data-quality rules:**
  - A failed or redesigned source records an error and keeps its previous events. A page we can't parse raises, so a redesign can't look like an empty calendar.
  - Each source gets a `schedule` check, shown in check details and saved in `check_runs`: WARN if it failed, never loaded, is more than one business day old, or shows no event within its expected horizon. They're WARNs because market data isn't affected, so they don't open a GitHub issue.
  - The panel separates "No events scheduled today", "Couldn't load the latest calendar from X" and "Couldn't load the calendar".
  - Times are only what the source printed, otherwise "time not published". That's common: FOMC and ECB publish none here, and Treasury only fills in the time once an auction is announced.
- **Decisions:** BEA and Census publish the same trade release, so it's one row with both links. Times from BEA and Census are labeled ET because they're US agencies and their pages don't name a zone, which is an assumption. Next business days are plain weekdays, not holiday-adjusted. ECB dates are its own calendar dates. Tests use trimmed copies of real responses in `tests/fixtures/schedules/`.
- **A bug this exposed:** a test added with the ranking chart opened the page against the real `data/brief.db`, and page load adds any new empty tables, so running tests changed a committed file. That test now uses a temporary database, and `tests/conftest.py` fails the whole run if any test changes a file in `data/`.

## 28. Moved the refresh off the top of the hour

- **What happened:** the first scheduled slot, Monday Nov 2 at 11:00 UTC, produced no run. Five hours later GitHub still showed no scheduled runs at all. The cron and YAML were valid, the workflow was active, GitHub listed no Actions incident, and a manual run of the same file passed.
- **Likely cause, not confirmed:** GitHub says scheduled runs can be delayed during heavy load, especially at the top of the hour, and may be dropped. Its scheduler logs aren't visible, and this is one miss.
- **What changed:** the cron is now `17 11 * * 1-5`. The stale-page banner compares New York dates, so it doesn't depend on the exact time.
- **Still open:** this hasn't been proven until a scheduled run appears. A run that never starts also can't open a GitHub issue, because `alert.py` runs inside the workflow, so the stale-page banner is the only sign.

## 29. Scheduled runs need a commit from a GitHub account

- **What happened:** Tuesday Nov 3 also produced no scheduled run, even at 11:17 UTC. Manual runs still worked, and GitHub listed no Actions incident.
- **Likely cause, not confirmed:** every commit that changed the cron was made as an email that isn't on any GitHub account, so GitHub linked no author. GitHub ties a schedule to whoever last changed the cron, and reports say schedules don't start when that person isn't a GitHub user.
- **What changed:** this repo now commits as the email on my GitHub account. The cron moved to `21 11 * * 1-5` so the commit changes the cron line itself and re-registers the schedule under my account.
- **Still open:** proven only when a run with the `schedule` event appears.

## 30. Testing the minimum Streamlit in CI, and pinning the refresh

- **What was missing:** `requirements.txt` promises Streamlit 1.51 or later, but CI only ever installed the newest release, so the floor was checked by hand when I remembered. The scheduled refresh also installed whatever was newest that morning, so a new release of yfinance or pandas could change or break a run with no code change.
- **How it was found:** reviewing the repo as an engineer would, and noticing that only `>=` bounds stood between a dependency release and the 6am run.
- **What changed:** `ci.yml` runs the suite twice, on the latest versions and with `constraints-min.txt` (Streamlit 1.51.0), and once a week even without a push, so a breaking release shows up in CI before it reaches the app. The refresh installs `requirements-lock.txt`, exact versions frozen from a passing Python 3.12 environment. New tests check that the lock covers every requirement at or above its floor, that the minimum constraint matches the floor, and that both workflows use the right file.
- **Trade-off:** the lock goes stale and has to be regenerated on purpose (the command is in its header). Streamlit Cloud still installs from `requirements.txt`, so the deployed page can pick up a new release when it restarts; the weekly CI run is the early warning for that.

## 31. A scheduled refresh that can't silently miss the morning

- **What happened:** the first run with the `schedule` event finally appeared on Wed Nov 4, created at 18:41 UTC for the 11:21 slot: 7h20m late, after GitHub Actions was degraded from 09:50 to 11:43 UTC. That fits entry 29 (the cron now registered under a linked account), but one run can't separate "fixed" from "a backlog cleared after the incident". Either way, a run at 1:41pm New York is useless for a pre-open page, and GitHub documents that scheduled runs can be delayed or dropped.
- **How it was found:** listing the workflow's runs by event through the GitHub API. Runs 1 to 4 were all `workflow_dispatch`, and every one of them started within seconds.
- **What changed:**
  - **Main trigger outside GitHub's scheduler:** a Cloudflare Worker (`ops/scheduler`) calls `workflow_dispatch` at 11:05 and 11:35 UTC, the event that has never failed to start here. GitHub's cron stays at 11:21 as a backup, with its line left untouched so it doesn't re-register.
  - **One refresh a day:** the new first step, `scripts/should_refresh.py`, lets the first automatic run of the New York day refresh, and stops later ones before they fetch anything. Manual runs always refresh. Every later step is gated on it, because a skipped run has no check report, and `alert.py` treats a missing report as a failure. `concurrency: refresh` queues a second trigger instead of racing the first one's `git push`. Checkout uses the branch as it is when the run starts, so a queued run sees the first one's data.
  - **Run log:** a new `refresh_runs` table records each run's time, trigger (`scheduler`, `github-cron`, `manual` or `local`) and GitHub run id. The guard and the page read it.
  - **Dead-man's switch:** the workflow pings Healthchecks.io after a refresh, or pings `/fail` if the check report or the commit is missing. Healthchecks emails if no ping arrives by about 12:20 UTC, so a run that never starts is noticed the same morning, which `alert.py` can't do from inside the run.
- **Token:** the Worker uses a fine-grained token for this one repository with only Actions read and write, a 90-day expiry, stored as an encrypted Cloudflare secret. When it expires the Worker fails, the GitHub cron still runs, and if both miss, Healthchecks emails.
- **Tests:** the guard's decisions, including that "today" is the New York date; that the guard only reads the database; that every step after the guard is gated on it; that the cron line hasn't changed; and the Worker's own Node tests (dispatch body, retry on 5xx, stop at once on a bad token), which pytest runs when Node is installed.
- **Still on me:** creating the token, deploying the Worker and the Healthchecks check. Steps are in `ops/scheduler/README.md`.

## 32. Saying when the data was taken, relative to the open

- **What was wrong:** the header said "Cross-asset moves before the US open" above data fetched at 1:42pm New York on Nov 4, with futures labeled "live". The only timing alarm was the stale banner, which waits until more than a full weekday has passed, so a missed morning looked normal all day.
- **How it was found:** reviewing the page as a visitor would, the day the scheduled run arrived 7h20m late.
- **What changed:** the header now reads "Data as of Wed Nov 04, 1:42 PM ET, after the US open" (or "pre-open", or "weekend"). New `runs.refresh_timing` adds a yellow banner once a weekday passes 8:00am New York with no refresh that day, naming the data's actual time, and an info note when today's refresh ran after 9:30am, saying moves marked live are mid-session. The red stale banner is unchanged and takes priority.
- **Decisions:** times are New York, because that's the market the page is for, and the tests cover both standard and daylight time. 8:00am leaves about 75 minutes after the latest trigger (11:35 UTC is 6:35am in winter) and 90 minutes before the open. Weekdays include holidays, matching the schedule. A refresh on a holiday is harmless, and treating one as missed would be wrong.
- **Knock-on fix:** three page tests compared the full list of info boxes, so they would have passed or failed depending on the time of day they ran. They now ignore the timing note.

## 33. A top of the page that says what the page is for

- **What was wrong:** reviewing the page as a visitor with 30 seconds, the self-checking that makes this project different was one green sentence, "All data checks passed", with no sign of what had been checked. The demo was about 1,400px down. On a phone, six half-width tiles stacked one per row came before any table, and the tables cut off after the trend column, so Flag and Cross-check, the trust columns, needed a sideways scroll. The ranking chart ran to 11σ on every quiet day, so about 70% of it was empty.
- **How it was found:** screenshots at 1440px and 390px of the page rendered from the committed database.
- **What changed:**
  - A coverage line under the banner: "129 checks this load · 21 instruments · 8 cross-checked against FRED or the ECB · 13 single source", counted from the results the banner uses.
  - One headline sentence from new `ranking.headline`: "Most unusual move: Gold +3.44%, 3.2σ against its own recent volatility. Nothing reaches the 4σ WARN line." It uses the same number as the sanity check, so it can't disagree with the flags, and it's built from a template, not an LLM.
  - The demo moved into an expander directly under the banner, so it's one click from the top without pushing the market tables down.
  - Tiles are 170px, so two fit across a phone, and a small CSS rule shrinks the tile value on narrow screens so "101.5430" stays whole. The table columns are now Instrument (pinned), Last, Change, Flag, Cross-check, then the rest, so a phone shows the flag and the start of the cross-check without scrolling.
  - The chart scales to the data with the WARN line in view. When FAIL is off the scale, it's named at the right edge ("FAIL 10σ →") instead of drawn. This reverses the choice in entry 26 to always draw FAIL, which cost most of the chart on a normal day. The caption now states both thresholds.
- **Tests:** the headline for a quiet day, a WARN-level move and a FAIL-level move; the chart's scale and its FAIL marker in both cases; the coverage line's counts on the page; and the demo sitting directly under the banner. `pinned` and `column_order` work on Streamlit 1.51, and the suite passes there.

## 34. A real disagreement to replay, and the page's own track record

- **Why:** the demo shows the checks catching faults I made up. A trader trusts a check that caught something real, and a page that shows its own history, gaps included.
- **Real incident:** entry 21 found one day when Yahoo's VIX close (20.37) and FRED's VIXCLS (17.76) disagreed, on Fri Feb 6, 2026. New `incidents.py` downloads a week either side from both sources once, with the same fetchers the refresh uses, and saves it to `data/incidents/vix-2026-02-06.csv`. The demo expander now opens with that replay: each shared day's two closes and gap, and the status the real `check_reconciliation` returns on the data up to that day. The sentence above the table is written from the file and the check's actual result. If Yahoo has since corrected its history and the gap is gone, the page says the check returns OK and would not have caught it, rather than claiming a catch. A fetch missing either source saves nothing, and until the file exists the page says it hasn't been downloaded.
- **Why the refresh fetches it:** this environment can't reach Yahoo or FRED, and I wasn't going to type the values in from the build notes. `refresh.py` calls `incidents.ensure()`, which does nothing once the file exists. The workflow now runs `git add data`, so the new folder is committed with the rest of the data.
- **Track record:** new `history.py` reads `check_runs` and `refresh_runs`. A new section near the bottom shows: refreshes since the first one, checks logged, WARN and FAIL counts, and how many refreshes ran pre-open on a weekday. One table merges each WARN or FAIL across runs (first seen, last seen, runs, latest detail); another lists every refresh with its New York time, trigger and timing. On the current database that reads "12 refreshes, 1,393 checks logged, 7 WARN and 0 FAIL results. 0 of 12 refreshes ran pre-open on a weekday." That's true, and it's exactly the problem in entry 31. Runs from before triggers were logged say "not recorded". I didn't backfill them from the GitHub API, because changing `brief.db` on a branch would conflict with the bot's daily data commits.
- **Bug this exposed:** pandas stores an `IntEnum` in a DataFrame as a plain int, so the replay table's `.name` failed until it was converted back with `Status(s)`. A page test caught it.
- **Test guard widened:** `conftest.py` only hashed files directly in `data/`, so a test writing to `data/incidents/` would have gone unnoticed. It now hashes the whole folder. The refresh test stubs `incidents.ensure`, since otherwise it would fetch from the network and write a real file.

## 35. Keeping the database in git, on purpose

- **The question:** the bot commits `data/brief.db` after every refresh, and a reviewer may ask whether a binary database belongs in git history.
- **Measured:** the database is 528 KB, and about 89 KB gzipped, which is roughly what git stores per version. At one refresh per weekday that's about 23 MB a year. My first estimate, 0.5 MB a run, ignored compression and was about 6x too high.
- **Decision:** keep it for now. Streamlit Cloud serves the repo as checked out, so committing the data is the simplest way to deploy it, with no storage service, credentials or extra failure point on page load. The alternatives (a `data` branch, a release asset, or object storage) each add a fetch that can fail when someone opens the page. I'll revisit if the repo passes about 100 MB, or if the lookback grows enough to make each version much larger.
- **No code change.**

## 36. README rewritten for a visitor

- **What was wrong:** the README opened with a feature list, explained the reliability work nowhere, and had no picture of the checks in action. One sentence, "Most bugs only appeared on real data", contradicted these notes, where most bugs were found by testing with production-shaped inputs or by reading the code.
- **What changed:** the README now opens with what the page is for, a GIF of the demo catching a +50% bad print, and why I built it. Then come what a visitor sees, the checks, a Mermaid diagram of the triggers, pipeline and alerts, a reliability section that says what still needs setup, and limitations, now including BLS and the single-source count. The contradictory sentence now says some bugs only appeared on live data and most were found by testing with production-shaped inputs or reviewing the code. The screenshot and GIF come from `docs/media/record.cjs` run against the committed data, so they show real numbers. A "Judgment calls at a glance" table at the top of this file indexes the decisions.
- **VIX notice:** the footer printed the copyright line FRED requires for VIXCLS, ending "Reprinted with permission", which read as if I'd asked CBOE. It now says that this is the notice FRED requires to be shown, with the notice itself unchanged.

## 37. A copy-ready morning note

- **Why:** a trader with a Bloomberg terminal already has every number here. What a desk does with a morning dashboard is pass it on: sales traders paste a few lines of morning color into chat or an email to clients. A page that's only a page leaves that step to retyping, which is where a wrong number or a dropped caveat gets in.
- **What changed:** new `note.py` builds a plain-text note from the page's own numbers: the as-of time and whether it's pre-open, the check banner and how many checks ran, any flagged rows first ("don't rely on"), the five most unusual moves in σ, US rates, today's scheduled events, and the page's caveats (different periods by market, what "live" means, BLS not covered, not production data). It sits in an expander under the ranking chart in a code block, which has a copy button.
- **Decisions:** no LLM, so it can't say anything the page doesn't. Caveats travel with the numbers, so a pasted note can't look more certain than the page. Failures go above the moves, because that's what the reader most needs to know. Rates show only when there's a value.
- **Bug avoided:** the ranking caption already used a local variable named `note`, which would have shadowed the new module and crashed the page. It's now `explain`.
- **Tests:** the note's content for a clean run, a FAIL, a calendar that didn't load and a rate with no value, and that the page renders it.

## 38. Streamlit app moved to its own folder

- **Why:** the main deployment is moving to a static site on GitHub Pages (entry 39), because a free Streamlit app sleeps after about 12 hours without visitors, and a recruiter opening the link sees a wake-up screen instead of the page. The Streamlit version stays for local use.
- **What changed:** `app.py` moved to `streamlit_app/app.py`, with its import path adjusted and a footer link to the Pages site. A three-line `app.py` at the root runs it, so the existing Streamlit Cloud deployment, which is configured to run `app.py`, keeps working with no settings change, and links already sent out don't break. Tests now open the moved file, and a new one checks that the root entry point still renders the page.

## 39. A static site on GitHub Pages

- **Why:** a free Streamlit app sleeps after about 12 hours without visitors, so a recruiter opening the link often sees a wake-up screen and waits, or leaves. Nothing on this page has to be computed when someone opens it: it changes once each weekday morning.
- **What changed:**
  - **A day's brief as data:** new `brief.py` collects everything the page shows (banner, check problems, coverage, headline, tiles, tables with trends, ranking, schedule, news, morning note) from the same modules the Streamlit app uses. The refresh saves it as `data/briefs/YYYY-MM-DD.json`, one file per New York date, about 20 KB. A second refresh the same day replaces that day's file, so a day keeps its latest data.
  - **The generator:** new `sitegen.py` and `scripts/build_site.py` render Jinja2 templates in `web/` into `public/`: `index.html` (the latest brief), `briefs/<date>.html` for every saved day, `archive.html`, `latest.json` for anyone who wants the data, and a 404 page. Rebuilding every day's page from its saved brief on each deploy means the archive survives redeploys and template changes.
  - **Done once at build time, in Python:** the demo's 87 instrument × fault combinations (about 90 seconds), so the browser only switches between results the real checks produced; the VIX incident replay; the track record; and four months of closes for the history chart. These appear on the latest page only. Archived pages are the brief as it stood.
  - **Done in the browser:** whether the data is stale, missing today's refresh, or from after the open depends on when someone reads the page, not when it was built. `web/static/timing.js` ports `runs.refresh_timing` and `moves.is_fetch_stale` to JavaScript in New York time, and `web/test/timing.test.js` runs the same cases as the Python tests, including daylight time, which pytest runs when Node is installed. Without JavaScript, a `<noscript>` note says the page can't check its own freshness.
  - **Charts:** Chart.js 4.4.1, vendored from npm into `web/static/vendor/` with its MIT license, so the page doesn't depend on a CDN being reachable. The ranking chart keeps the scaling rule from entry 33 and draws the WARN and FAIL lines with a small inline plugin; each chart also has a plain table. Sparklines are inline SVG drawn in Python.
- **Safety:** the build opens the database read-only, through an in-memory copy, so it can add missing tables without touching the committed file. A test checks the file's bytes don't change. Text from sources is HTML-escaped; the page's own markdown allows only bold and http(s) links; the JSON embedded in the page can't close its own `<script>` tag. Tests cover all three.
- **Decisions:** Chart.js rather than Plotly, because it's about 200 KB instead of about 3.5 MB, and these are two simple charts. The archive begins the day the site is first published. I didn't rebuild earlier days, because their check results and news weren't saved as they were shown. "Scheduled for <date>" replaces "today", since a page is read on other days than it was built.

## 40. Publishing to GitHub Pages after every refresh

- **What changed:** new `.github/workflows/pages.yml` checks out `main`, builds the site with the pinned dependencies, and deploys it with GitHub's official Pages actions. It runs on any push to `main` (code changes), by hand, and as a second job of the refresh. It can't rely on the refresh's push: a push made with the workflow's own `GITHUB_TOKEN` doesn't start other workflows, so the data commit alone would never redeploy the site. The refresh job now exposes the guard's decision as an output. The `publish` job runs when the guard let the refresh run, even if a check failed, because the site should show the failure. It's skipped when the guard skipped, so the site isn't rebuilt three times each morning.
- **Decisions:** the built site isn't committed (`public/` is gitignored); Pages serves the uploaded artifact. Only one deploy runs at a time, and a newer one waits rather than cancelling a deploy in progress. The build checks out `main` explicitly rather than the commit that started the refresh, so it includes the data commit made moments earlier.
- **Needs me once:** in the repository settings, Pages → Source must be set to "GitHub Actions". A workflow's token can't turn Pages on.
- **Not verified on GitHub yet:** I couldn't run actionlint here (the sandbox wouldn't let me run a downloaded binary), and Pages only deploys from `main`. Tests parse both workflows and check the wiring, but the first real proof is the first deploy after merging.

## 41. README and media for the static site

- **What changed:** the README now leads with the GitHub Pages address, the archive and a link back to kechunwu.github.io. It explains why the site is static and the three trade-offs that came with it (freshness judged in the browser, the demo precomputed, one build per refresh). The diagram adds the build and deploy steps, the file table lists the new modules and `web/`, and the local instructions build and serve the site. `docs/media/record.cjs` now records from a local build of the static site; `docs/screenshot.png` and `docs/demo.gif` were re-recorded from it with the committed data, so they show real numbers. The GIF injects a +50% bad print and then a frozen feed.
