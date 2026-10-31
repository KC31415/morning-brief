"""Pull daily closes from yfinance and FRED into one long table.

Output columns: date, ticker, close, source, fetched_at
One bad ticker never stops the run: failures are logged and the ticker is
simply missing, which the completeness check then reports.
"""
import io
import logging
from datetime import datetime, timedelta, timezone

import pandas as pd
import requests

log = logging.getLogger(__name__)

FRED_CSV = "https://fred.stlouisfed.org/graph/fredgraph.csv?id={series}&cosd={start}"


def fetch_yfinance(tickers: list[str], days: int) -> pd.DataFrame:
    import yfinance as yf  # imported here so tests don't need it

    frames = []
    for t in tickers:
        try:
            hist = yf.Ticker(t).history(period=f"{days}d", interval="1d", auto_adjust=False)
            n_nan = int(hist["Close"].isna().sum()) if not hist.empty else 0
            if n_nan:
                log.warning("yfinance returned %d NaN closes for %s; dropping them", n_nan, t)
                hist = hist.dropna(subset=["Close"])
            if hist.empty:
                log.warning("yfinance returned no rows for %s", t)
                continue
            df = hist[["Close"]].reset_index()
            df.columns = ["date", "close"]
            # yfinance timestamps are tz-aware exchange times; keep the calendar date
            df["date"] = pd.to_datetime(df["date"]).dt.tz_localize(None).dt.normalize()
            df["ticker"] = t
            df["source"] = "yfinance"
            frames.append(df)
        except Exception:
            log.exception("yfinance failed for %s", t)
    return pd.concat(frames, ignore_index=True) if frames else _empty()


def fetch_fred(series_ids: list[str], days: int) -> pd.DataFrame:
    start = (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%d")
    frames = []
    for s in series_ids:
        try:
            resp = requests.get(FRED_CSV.format(series=s, start=start), timeout=30)
            resp.raise_for_status()
            df = pd.read_csv(io.StringIO(resp.text))
            df.columns = ["date", "close"]
            df["date"] = pd.to_datetime(df["date"])
            # FRED marks missing days with "." -> coerce to NaN and drop
            df["close"] = pd.to_numeric(df["close"], errors="coerce")
            df = df.dropna(subset=["close"])
            df["ticker"] = s
            df["source"] = "fred"
            frames.append(df)
        except Exception:
            log.exception("FRED failed for %s", s)
    return pd.concat(frames, ignore_index=True) if frames else _empty()


def fetch_all(instruments: list[dict], days: int = 120) -> pd.DataFrame:
    yf_tickers = [i["ticker"] for i in instruments if i["source"] == "yfinance"]
    fred_ids = [i["ticker"] for i in instruments if i["source"] == "fred"]
    df = pd.concat([fetch_yfinance(yf_tickers, days), fetch_fred(fred_ids, days)], ignore_index=True)
    df["fetched_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    log.info("fetched %d rows for %d tickers", len(df), df["ticker"].nunique())
    return df[["date", "ticker", "close", "source", "fetched_at"]]


def _empty() -> pd.DataFrame:
    return pd.DataFrame(columns=["date", "close", "ticker", "source"])
