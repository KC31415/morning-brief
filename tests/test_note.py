"""The copy-ready morning note: the page's numbers and caveats as plain text."""
import sys
from pathlib import Path

import pandas as pd
from streamlit.testing.v1 import AppTest

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "streamlit_app" / "app.py"
sys.path.insert(0, str(ROOT / "src"))

from morning_brief import config, note, schedules  # noqa: E402
from morning_brief.checks import CheckResult, Status  # noqa: E402

CFG = {"checks": {"move_warn_z": 4.0, "move_fail_z": 10.0}}
TABLE = pd.DataFrame([
    {"ticker": "GC=F", "name": "Gold", "last": "4075.80", "Change": "+3.44%", "flag": ""},
    {"ticker": "^TNX", "name": "US 10Y yield", "last": "4.904", "Change": "-4.8 bp", "flag": "❌"},
    {"ticker": "^FVX", "name": "US 5Y yield", "last": None, "Change": "n/a", "flag": ""},
])
RANKED = pd.DataFrame([{"name": "Gold", "change": "+3.44%", "z": 3.2}])
OK = [CheckResult("freshness", "GC=F", Status.OK, "")]
FAIL = OK + [CheckResult("reconciliation", "^TNX vs DGS10", Status.FAIL, "differ by 0.2")]
VIEW = schedules.View("events", [{"time": "8:30 AM ET", "event": "Trade balance", "sources": [("BEA", "u"), ("Census", "v")]}], {}, [])


def build(results=OK, view=VIEW):
    return note.build(TABLE, RANKED, results, "2026-11-05T11:06:00+00:00", view, 1, CFG)


def test_note_carries_the_as_of_time_and_check_status():
    text = build()
    assert text.startswith("Morning Brief, data as of Thu Nov 05, 6:06 AM ET, pre-open\n")
    assert "Data checks: All data checks passed. (1 check; 1 of 3 instruments cross-checked)" in text


def test_note_puts_failures_up_front():
    text = build(FAIL)
    assert "1 data check FAILED" in text
    assert text.index("Flagged, don't rely on: US 10Y yield ❌") < text.index("Biggest moves")


def test_note_lists_moves_rates_and_schedule_with_caveats():
    text = build()
    assert "  Gold +3.44% (3.2σ)" in text and "WARN at 4σ" in text
    assert "US rates: 10Y yield 4.904 (-4.8 bp)" in text and "5Y" not in text  # no value, so not shown
    assert "  8:30 AM ET Trade balance (BEA/Census)" in text
    assert "Not covered: BLS (CPI, jobs)" in text
    assert "not a real-time price" in text and "not production market data" in text


def test_note_says_when_the_calendar_didnt_load():
    text = build(view=schedules.View("not_loaded", [], {}, ["BEA", "Census"]))
    assert "Calendar couldn't be loaded" in text and "Trade balance" not in text


def test_page_shows_the_note(tmp_path, monkeypatch):
    from test_app import yield_series  # noqa: E402
    from morning_brief import checks, storage
    from datetime import datetime, timezone
    db = tmp_path / "brief.db"
    conn = storage.connect(db)
    storage.upsert_prices(conn, yield_series("^TNX", checks.expected_session(datetime.now(timezone.utc))))
    conn.close()
    monkeypatch.setattr(config, "DB_PATH", db)
    monkeypatch.setattr(config, "SUMMARY_PATH", tmp_path / "summary.json")
    at = AppTest.from_file(str(APP), default_timeout=30).run()
    assert not at.exception
    assert any(c.value.startswith("Morning Brief, data as of ") for c in at.code)
