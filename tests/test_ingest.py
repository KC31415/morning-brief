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


def test_weekend_rows_are_dropped_and_logged(monkeypatch, caplog):
    class Ticker:
        def __init__(self, ticker):
            pass

        def history(self, **kwargs):
            idx = pd.DatetimeIndex(["2026-10-29", "2026-10-30", "2026-10-31"], tz="Europe/London", name="Date")
            return pd.DataFrame({"Close": [1.33, 1.34, 1.35]}, index=idx)

    monkeypatch.setitem(sys.modules, "yfinance", types.SimpleNamespace(Ticker=Ticker))
    df = ingest.fetch_all([inst("GBPUSD=X")])
    assert list(pd.to_datetime(df["date"]).dt.day_of_week) == [3, 4]
    assert "GBPUSD=X" in caplog.text and "weekend" in caplog.text


ECB_CSV = """KEY,TIME_PERIOD,OBS_VALUE
EXR.D.USD.EUR.SP00.A,2026-10-29,1.1130
EXR.D.USD.EUR.SP00.A,2026-10-30,1.1172
"""


def test_ecb_rates_are_parsed_into_the_common_table(monkeypatch):
    response = types.SimpleNamespace(text=ECB_CSV, raise_for_status=lambda: None)
    monkeypatch.setattr(ingest.requests, "get", lambda url, timeout: response)
    df = ingest.fetch_all([{"ticker": "ECB_EURUSD", "source": "ecb", "series": "D.USD.EUR.SP00.A"}])
    assert list(df["ticker"].unique()) == ["ECB_EURUSD"] and list(df["source"].unique()) == ["ecb"]
    assert list(df["close"]) == [1.1130, 1.1172]


def test_ecb_failure_does_not_stop_the_run(monkeypatch):
    def boom(url, timeout):
        raise OSError("down")

    monkeypatch.setattr(ingest.requests, "get", boom)
    assert ingest.fetch_all([{"ticker": "ECB_EURUSD", "source": "ecb", "series": "x"}]).empty
