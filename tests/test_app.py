"""Run the real Streamlit page against a temporary database."""
import json
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
from streamlit.testing.v1 import AppTest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from morning_brief import checks, config, storage  # noqa: E402


def yield_series(ticker, end, offset=0.0, source="yfinance"):
    rng = np.random.default_rng(0)
    dates = pd.bdate_range(end=end, periods=80)
    closes = 4.2 + offset + np.cumsum(rng.normal(0, 0.03, 80))
    return pd.DataFrame({"date": dates, "ticker": ticker, "close": closes, "source": source, "fetched_at": "2026-01-01"})


def test_reconciliation_failure_flags_both_tickers(tmp_path, monkeypatch):
    db = tmp_path / "brief.db"
    conn = sqlite3.connect(db)
    conn.executescript(storage.SCHEMA)
    end = checks.expected_session(datetime.now(timezone.utc))
    storage.upsert_prices(conn, yield_series("^TNX", end))
    storage.upsert_prices(conn, yield_series("DGS10", end, offset=1.0, source="fred"))  # 100bp apart
    conn.close()
    monkeypatch.setattr(config, "DB_PATH", db)
    monkeypatch.setattr(config, "SUMMARY_PATH", tmp_path / "summary.json")

    at = AppTest.from_file(str(ROOT / "app.py"), default_timeout=30).run()

    assert not at.exception
    rows = pd.concat([d.value for d in at.dataframe])
    flags = dict(zip(rows["name"], rows["flag"]))
    assert flags["US 10Y yield"] == "❌"
    assert flags["US 10Y yield (FRED)"] == "❌"
    marks = dict(zip(rows["name"], rows["cross-check"]))
    assert marks["US 10Y yield"] == "✗ FRED"  # a failed check must not show a tick


def test_table_shows_change_span_and_basis(tmp_path, monkeypatch):
    db = tmp_path / "brief.db"
    conn = sqlite3.connect(db)
    conn.executescript(storage.SCHEMA)
    end = checks.expected_session(datetime.now(timezone.utc))
    storage.upsert_prices(conn, yield_series("^TNX", end).assign(fetched_at=datetime.now(timezone.utc).isoformat()))
    conn.close()
    monkeypatch.setattr(config, "DB_PATH", db)
    monkeypatch.setattr(config, "SUMMARY_PATH", tmp_path / "summary.json")

    at = AppTest.from_file(str(ROOT / "app.py"), default_timeout=30).run()

    rows = pd.concat([d.value for d in at.dataframe])
    tnx = rows[rows["name"] == "US 10Y yield"].iloc[0]
    assert "bp" in tnx["Change"] and "→" in tnx["from → to"]
    assert tnx["basis"] == "prior US session"


def test_short_history_flag_matches_banner(tmp_path, monkeypatch):
    # One row is a WARN, so the row must not show the FAIL mark under a yellow banner.
    db = tmp_path / "brief.db"
    conn = sqlite3.connect(db)
    conn.executescript(storage.SCHEMA)
    end = checks.expected_session(datetime.now(timezone.utc))
    storage.upsert_prices(conn, yield_series("^TNX", end).tail(1))
    conn.close()
    cfg = config.load_config()
    cfg.update(instruments=[i for i in cfg["instruments"] if i["ticker"] == "^TNX"], reconcile=[])
    monkeypatch.setattr(config, "DB_PATH", db)
    monkeypatch.setattr(config, "SUMMARY_PATH", tmp_path / "summary.json")
    monkeypatch.setattr(config, "load_config", lambda: cfg)

    at = AppTest.from_file(str(ROOT / "app.py"), default_timeout=30).run()

    assert not at.exception
    assert at.warning and not at.error
    rows = pd.concat([d.value for d in at.dataframe])
    assert rows[rows["name"] == "US 10Y yield"].iloc[0]["flag"] == "⚠️"


def test_table_shows_source_and_marks_single_source_unverified(tmp_path, monkeypatch):
    db = tmp_path / "brief.db"
    conn = sqlite3.connect(db)
    conn.executescript(storage.SCHEMA)
    end = checks.expected_session(datetime.now(timezone.utc))
    for ticker, source in [("^TNX", "yfinance"), ("DGS10", "fred"), ("GC=F", "yfinance")]:
        storage.upsert_prices(conn, yield_series(ticker, end, source=source))
    conn.close()
    monkeypatch.setattr(config, "DB_PATH", db)
    monkeypatch.setattr(config, "SUMMARY_PATH", tmp_path / "summary.json")

    at = AppTest.from_file(str(ROOT / "app.py"), default_timeout=30).run()

    rows = pd.concat([d.value for d in at.dataframe]).set_index("name")
    assert rows.loc["US 10Y yield", "source"] == "yfinance"
    assert rows.loc["US 10Y yield", "cross-check"] == "✓ FRED"
    assert rows.loc["US 10Y yield (FRED)", "cross-check"] == "✓ Yahoo"
    assert rows.loc["Gold", "cross-check"] == "unverified"
    assert any("single-source" in c.value for c in at.caption)


def run_page_with_summary(tmp_path, monkeypatch, summary):
    db = tmp_path / "brief.db"
    conn = sqlite3.connect(db)
    conn.executescript(storage.SCHEMA)
    end = checks.expected_session(datetime.now(timezone.utc))
    storage.upsert_prices(conn, yield_series("^TNX", end))
    conn.close()
    path = tmp_path / "summary.json"
    path.write_text(json.dumps(summary))
    monkeypatch.setattr(config, "DB_PATH", db)
    monkeypatch.setattr(config, "SUMMARY_PATH", path)
    return AppTest.from_file(str(ROOT / "app.py"), default_timeout=30).run()


def test_empty_brief_says_no_market_moving_headlines(tmp_path, monkeypatch):
    at = run_page_with_summary(tmp_path, monkeypatch, {"model": "m", "bullets": [], "error": None, "headlines": []})
    assert [i.value for i in at.info] == ["No market-moving headlines overnight"]


def test_failed_summary_shows_its_error_not_the_empty_message(tmp_path, monkeypatch):
    error = "summary failed: every bullet had invalid citations"
    at = run_page_with_summary(tmp_path, monkeypatch, {"model": "m", "bullets": [], "error": error, "headlines": []})
    assert [i.value for i in at.info] == [error]


def test_dollar_amounts_do_not_render_as_math(tmp_path, monkeypatch):
    headline = {"id": 1, "source": "F", "title": "Deal worth $5bn or $6bn", "link": "https://x"}
    bullet = {"bullet": "From $10bn to about $20bn.", "sources": [1]}
    at = run_page_with_summary(tmp_path, monkeypatch, {"model": "m", "bullets": [bullet], "error": None, "headlines": [headline]})
    text = [m.value for m in at.markdown]
    assert any(r"From \$10bn to about \$20bn." in t for t in text)
    assert any(r"Deal worth \$5bn or \$6bn" in t for t in text)
