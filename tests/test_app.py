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
    return pd.DataFrame({"date": dates, "ticker": ticker, "close": closes, "source": source,
                         "fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds")})


def test_reconciliation_failure_flags_the_main_row(tmp_path, monkeypatch):
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
    marks = dict(zip(rows["name"], rows["cross-check"]))
    assert marks["US 10Y yield"].startswith("✗ FRED ")  # a failed check must not show a tick


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
    cfg.update(instruments=[i for i in cfg["instruments"] if i["ticker"] == "^TNX"], reconcile=[], schedules=[])
    monkeypatch.setattr(config, "DB_PATH", db)
    monkeypatch.setattr(config, "SUMMARY_PATH", tmp_path / "summary.json")
    monkeypatch.setattr(config, "load_config", lambda: cfg)

    at = AppTest.from_file(str(ROOT / "app.py"), default_timeout=30).run()

    assert not at.exception
    assert at.warning and not at.error
    rows = pd.concat([d.value for d in at.dataframe])
    assert rows[rows["name"] == "US 10Y yield"].iloc[0]["flag"] == "⚠️"


def test_table_shows_source_and_marks_single_source_rows(tmp_path, monkeypatch):
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
    assert rows.loc["US 10Y yield", "source"] == "Yahoo"
    fred = yield_series("DGS10", end).iloc[-1]
    assert rows.loc["US 10Y yield", "cross-check"] == f"✓ FRED {fred['close']:.3f} ({fred['date']:%a %m-%d})"
    assert "US 10Y yield (FRED)" not in rows.index
    assert rows.loc["Gold", "cross-check"] == "single source"
    assert any("13 of 21 instruments are single source" in c.value for c in at.caption)
    assert any("Chicago Board Options Exchange" in c.value for c in at.caption)
    assert any("Data as of " in c.value and " ET, " in c.value for c in at.caption)


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


def news_notes(at):
    """Info boxes other than the refresh-timing note, which depends on when the test runs."""
    return [i.value for i in at.info if not i.value.startswith("Today's refresh")]


def test_empty_brief_says_no_market_moving_headlines(tmp_path, monkeypatch):
    at = run_page_with_summary(tmp_path, monkeypatch, {"model": "m", "bullets": [], "error": None, "headlines": []})
    assert news_notes(at) == ["No market-moving headlines overnight"]


def test_failed_summary_shows_its_error_not_the_empty_message(tmp_path, monkeypatch):
    error = "summary failed: every bullet had invalid citations"
    at = run_page_with_summary(tmp_path, monkeypatch, {"model": "m", "bullets": [], "error": error, "headlines": []})
    assert news_notes(at) == [error]


def test_dollar_amounts_do_not_render_as_math(tmp_path, monkeypatch):
    headline = {"id": 1, "source": "F", "title": "Deal worth $5bn or $6bn", "link": "https://x"}
    bullet = {"bullet": "From $10bn to about $20bn.", "sources": [1]}
    at = run_page_with_summary(tmp_path, monkeypatch, {"model": "m", "bullets": [bullet], "error": None, "headlines": [headline]})
    text = [m.value for m in at.markdown]
    assert any(r"From \$10bn to about \$20bn." in t for t in text)
    assert any(r"Deal worth \$5bn or \$6bn" in t for t in text)


def test_headlines_show_publication_date_next_to_source(tmp_path, monkeypatch):
    dated = {"id": 1, "source": "EIA", "title": "Dated", "link": "https://x", "published": "2026-10-30T14:00:00+00:00"}
    undated = {"id": 2, "source": "ECB", "title": "Undated", "link": "https://y", "published": None}
    at = run_page_with_summary(tmp_path, monkeypatch, {"model": "m", "bullets": [], "error": None, "headlines": [dated, undated]})
    text = [m.value for m in at.markdown]
    assert any("**EIA** (2026-10-30):" in t for t in text)
    assert any("**ECB**:" in t for t in text)


def test_single_warning_banner_is_singular(tmp_path, monkeypatch):
    db = tmp_path / "brief.db"
    conn = sqlite3.connect(db)
    conn.executescript(storage.SCHEMA)
    end = checks.expected_session(datetime.now(timezone.utc)) - pd.offsets.BDay(1)  # one session stale
    storage.upsert_prices(conn, yield_series("^TNX", end))
    conn.close()
    cfg = config.load_config()
    cfg.update(instruments=[i for i in cfg["instruments"] if i["ticker"] == "^TNX"], reconcile=[], schedules=[])
    monkeypatch.setattr(config, "DB_PATH", db)
    monkeypatch.setattr(config, "SUMMARY_PATH", tmp_path / "summary.json")
    monkeypatch.setattr(config, "load_config", lambda: cfg)

    at = AppTest.from_file(str(ROOT / "app.py"), default_timeout=30).run()

    assert at.warning[0].value.startswith("1 data warning.")


def test_table_has_no_as_of_column_and_keeps_cross_check(tmp_path, monkeypatch):
    at = run_page_with_summary(tmp_path, monkeypatch, {"model": "m", "bullets": [], "error": None, "headlines": []})
    tables = [d.value for d in at.dataframe if "name" in d.value.columns]
    assert tables and all("as of" not in t.columns and "cross-check" in t.columns for t in tables)
    assert not any(c.dataframe for c in at.columns)  # side-by-side tables clip the cross-check column


def test_showcase_page_has_key_market_tiles_and_trend_column(tmp_path, monkeypatch):
    at = run_page_with_summary(tmp_path, monkeypatch, {"model": "m", "bullets": [], "error": None, "headlines": []})
    assert not at.exception
    assert [m.label for m in at.metric] == ["US 10Y yield ❌"]
    tables = [d.value for d in at.dataframe if "name" in d.value.columns]
    row = pd.concat(tables).set_index("name").loc["US 10Y yield"]
    assert len(row["trend"]) == 20


def test_no_headlines_reads_as_a_sentence(tmp_path, monkeypatch):
    at = run_page_with_summary(tmp_path, monkeypatch, {"model": "m", "bullets": [], "error": "no headlines", "headlines": []})
    assert news_notes(at) == ["No new official releases since the previous US close."]


def test_tile_for_flagged_market_shows_its_flag(tmp_path, monkeypatch):
    # The 10Y series is alone here: its missing reference is a FAIL, which rolls up to this row.
    at = run_page_with_summary(tmp_path, monkeypatch, {"model": "m", "bullets": [], "error": None, "headlines": []})
    assert [m.label for m in at.metric] == ["US 10Y yield ❌"]


def only_tnx_config(monkeypatch):
    cfg = config.load_config()
    cfg.update(instruments=[i for i in cfg["instruments"] if i["ticker"] == "^TNX"], reconcile=[], schedules=[])
    monkeypatch.setattr(config, "load_config", lambda: cfg)


def page_fetched_at(tmp_path, monkeypatch, fetched_at):
    db = tmp_path / "brief.db"
    conn = sqlite3.connect(db)
    conn.executescript(storage.SCHEMA)
    end = checks.expected_session(datetime.now(timezone.utc), "XNYS")
    storage.upsert_prices(conn, yield_series("^TNX", end).assign(fetched_at=fetched_at))
    conn.close()
    monkeypatch.setattr(config, "DB_PATH", db)
    monkeypatch.setattr(config, "SUMMARY_PATH", tmp_path / "summary.json")
    only_tnx_config(monkeypatch)
    return AppTest.from_file(str(ROOT / "app.py"), default_timeout=30).run()


def test_old_fetch_shows_red_stale_banner_even_when_checks_pass(tmp_path, monkeypatch):
    fetched = (pd.Timestamp.now(tz="UTC") - pd.Timedelta(days=7)).isoformat(timespec="seconds")
    at = page_fetched_at(tmp_path, monkeypatch, fetched)
    assert any(s.value == "All data checks passed." for s in at.success)
    assert at.error[0].value.startswith("Data is stale: last updated ")


def test_recent_fetch_has_no_stale_banner(tmp_path, monkeypatch):
    at = page_fetched_at(tmp_path, monkeypatch, pd.Timestamp.now(tz="UTC").isoformat(timespec="seconds"))
    assert not at.error
