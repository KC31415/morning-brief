"""A bad row from a data source must not stop the refresh."""
import sqlite3
import sys
import types
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from morning_brief import ingest, storage  # noqa: E402


def fake_yfinance(closes_by_ticker):
    class Ticker:
        def __init__(self, ticker):
            self.closes = closes_by_ticker[ticker]

        def history(self, **kwargs):
            idx = pd.date_range(end="2026-10-29", periods=len(self.closes), freq="B", tz="America/New_York", name="Date")
            return pd.DataFrame({"Close": self.closes}, index=idx)

    return types.SimpleNamespace(Ticker=Ticker)


def inst(ticker):
    return {"ticker": ticker, "source": "yfinance"}


def store(df):
    conn = sqlite3.connect(":memory:")
    conn.executescript(storage.SCHEMA)
    storage.upsert_prices(conn, df)
    return conn


def test_nan_close_is_dropped_and_other_rows_are_stored(monkeypatch):
    monkeypatch.setitem(sys.modules, "yfinance", fake_yfinance({"A": [100.0, 101.0, np.nan], "B": [50.0, 51.0, 52.0]}))
    conn = store(ingest.fetch_all([inst("A"), inst("B")]))
    counts = dict(conn.execute("SELECT ticker, COUNT(*) FROM prices GROUP BY ticker").fetchall())
    assert counts == {"A": 2, "B": 3}


def test_ticker_with_only_nan_closes_is_missing_not_fatal(monkeypatch):
    monkeypatch.setitem(sys.modules, "yfinance", fake_yfinance({"A": [np.nan, np.nan], "B": [50.0, 51.0]}))
    conn = store(ingest.fetch_all([inst("A"), inst("B")]))
    assert [t for (t,) in conn.execute("SELECT DISTINCT ticker FROM prices")] == ["B"]
