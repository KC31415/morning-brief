"""Run the real Streamlit page against a temporary database."""
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
