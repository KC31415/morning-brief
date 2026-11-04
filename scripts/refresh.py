"""Run the whole pipeline once: fetch -> store -> check -> summarize.

Run before the open (GitHub Actions does this on a schedule):
    python scripts/refresh.py
"""
import json
import logging
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from morning_brief import alerts, checks, ingest, news, schedules, storage, summarize  # noqa: E402
from morning_brief.config import DB_PATH, REPORT_PATH, SUMMARY_PATH, load_config  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("refresh")


def main() -> int:
    cfg = load_config()
    now = datetime.now(timezone.utc)
    run_at = now.isoformat(timespec="seconds")

    conn = storage.connect(DB_PATH)
    # REFRESH_TRIGGER is set by the workflow; a run on a laptop is "local"
    storage.log_refresh(conn, run_at, os.getenv("REFRESH_TRIGGER") or "local", os.getenv("GITHUB_RUN_ID"))
    fetched = ingest.fetch_all(cfg["instruments"])
    if not fetched.empty:
        storage.upsert_prices(conn, fetched)

    prices = storage.load_prices(conn)
    events, status = schedules.fetch_all(cfg.get("schedules", []), now)
    storage.save_schedules(conn, events, status, run_at)
    results = checks.run_all(prices, cfg, as_of=now) + schedules.check_schedules(
        storage.load_schedule_status(conn), storage.load_schedule_events(conn), cfg.get("schedules", []), now)
    storage.log_checks(conn, run_at, results)
    alerts.write_report(REPORT_PATH, alerts.failures(results))
    overall = checks.overall_status(results)
    for r in results:
        if r.status != checks.Status.OK:
            log.warning("%s %s %s: %s", r.status.name, r.check, r.ticker, r.detail)
    log.info("overall data status: %s", overall.name)

    headlines = news.fetch_headlines(cfg["news_feeds"])
    summary = summarize.summarize(headlines)
    summary.update(run_at=run_at, headlines=headlines)
    SUMMARY_PATH.write_text(json.dumps(summary, indent=2))

    # Non-zero exit on FAIL so the scheduled job shows red in GitHub Actions
    return 1 if overall == checks.Status.FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
