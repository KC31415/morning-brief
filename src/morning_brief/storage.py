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
CREATE TABLE IF NOT EXISTS refresh_runs (
    run_at      TEXT PRIMARY KEY,
    trigger     TEXT NOT NULL,
    github_run  TEXT
);
CREATE TABLE IF NOT EXISTS schedule_events (
    source      TEXT NOT NULL,
    event       TEXT NOT NULL,
    event_date  TEXT NOT NULL,
    event_time  TEXT,
    link        TEXT NOT NULL,
    fetched_at  TEXT NOT NULL,
    PRIMARY KEY (source, event, event_date)
);
CREATE TABLE IF NOT EXISTS schedule_status (
    source        TEXT PRIMARY KEY,
    last_attempt  TEXT NOT NULL,
    last_success  TEXT,
    error         TEXT
);
"""


def connect(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.executescript(SCHEMA)
    return conn


def connect_readonly(path: Path) -> sqlite3.Connection:
    """For readers like the site build: no schema changes, no writes. Tables added since the
    database was saved (such as refresh_runs) are created in a temporary in-memory copy instead."""
    disk = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    conn = sqlite3.connect(":memory:")
    disk.backup(conn)
    disk.close()
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


def save_schedules(conn: sqlite3.Connection, events, status: dict, fetched_at: str) -> None:
    """A good fetch replaces that source's events, so cancellations disappear. A failed one keeps the old ones."""
    for source, error in status.items():
        if error is None:
            conn.execute("DELETE FROM schedule_events WHERE source = ?", (source,))
        conn.execute(
            "INSERT INTO schedule_status (source, last_attempt, last_success, error) VALUES (?, ?, ?, ?) "
            "ON CONFLICT(source) DO UPDATE SET last_attempt = excluded.last_attempt, error = excluded.error, "
            "last_success = COALESCE(excluded.last_success, schedule_status.last_success)",
            (source, fetched_at, fetched_at if error is None else None, error),
        )
    conn.executemany(
        "INSERT OR REPLACE INTO schedule_events (source, event, event_date, event_time, link, fetched_at) VALUES (?, ?, ?, ?, ?, ?)",
        [(e.source, e.event, e.date, e.time, e.link, fetched_at) for e in events],
    )
    conn.commit()


def load_schedule_events(conn: sqlite3.Connection) -> pd.DataFrame:
    return pd.read_sql_query("SELECT source, event, event_date, event_time, link, fetched_at FROM schedule_events", conn)


def load_schedule_status(conn: sqlite3.Connection) -> pd.DataFrame:
    return pd.read_sql_query("SELECT source, last_attempt, last_success, error FROM schedule_status", conn)


def log_refresh(conn: sqlite3.Connection, run_at: str, trigger: str, github_run: str | None = None) -> None:
    """What started this refresh: scheduler, github-cron, manual or local."""
    conn.execute("INSERT OR REPLACE INTO refresh_runs VALUES (?, ?, ?)", (run_at, trigger, github_run))
    conn.commit()


def load_refresh_runs(conn: sqlite3.Connection) -> pd.DataFrame:
    return pd.read_sql_query("SELECT run_at, trigger, github_run FROM refresh_runs ORDER BY run_at", conn)


def load_check_runs(conn: sqlite3.Connection) -> pd.DataFrame:
    return pd.read_sql_query("SELECT run_at, check_name, ticker, status, detail FROM check_runs ORDER BY run_at", conn)
