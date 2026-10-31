"""SQLite storage so prices and check results can be queried with plain SQL."""
import sqlite3
from pathlib import Path

import pandas as pd

SCHEMA = """
CREATE TABLE IF NOT EXISTS prices (
    date        TEXT NOT NULL,
    ticker      TEXT NOT NULL,
    close       REAL NOT NULL,
    source      TEXT NOT NULL,
    fetched_at  TEXT NOT NULL,
    PRIMARY KEY (date, ticker)
);
CREATE TABLE IF NOT EXISTS check_runs (
    run_at   TEXT NOT NULL,
    check_name TEXT NOT NULL,
    ticker   TEXT,
    status   TEXT NOT NULL,
    detail   TEXT
);
"""


def connect(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.executescript(SCHEMA)
    return conn


def upsert_prices(conn: sqlite3.Connection, df: pd.DataFrame) -> None:
    rows = df.assign(date=pd.to_datetime(df["date"]).dt.strftime("%Y-%m-%d"))
    conn.executemany(
        "INSERT OR REPLACE INTO prices (date, ticker, close, source, fetched_at) VALUES (?, ?, ?, ?, ?)",
        rows[["date", "ticker", "close", "source", "fetched_at"]].itertuples(index=False, name=None),
    )
    conn.commit()


def load_prices(conn: sqlite3.Connection, lookback_days: int = 120) -> pd.DataFrame:
    df = pd.read_sql_query(
        "SELECT date, ticker, close, source, fetched_at FROM prices "
        "WHERE date >= date('now', ?) ORDER BY ticker, date",
        conn,
        params=(f"-{lookback_days} days",),
    )
    df["date"] = pd.to_datetime(df["date"])
    return df


def log_checks(conn: sqlite3.Connection, run_at: str, results) -> None:
    conn.executemany(
        "INSERT INTO check_runs VALUES (?, ?, ?, ?, ?)",
        [(run_at, r.check, r.ticker, r.status.name, r.detail) for r in results],
    )
    conn.commit()
