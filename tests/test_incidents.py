"""The real-incident replay and the track record. Data here is made up for the tests;
the page only ever shows a file fetched from Yahoo and FRED."""
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
from streamlit.testing.v1 import AppTest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from morning_brief import checks, config, history, incidents, ingest, storage  # noqa: E402

PAIR = {"a": "^VIX", "b": "VIXCLS", "warn": 0.05, "fail": 0.50}


def incident_frame(gap_on_day=2.61):
    dates = pd.bdate_range("2026-02-02", "2026-02-10")
    a = [18.0, 18.5, 19.0, 19.5, 17.76 + gap_on_day, 17.36, 17.0]
    b = [18.0, 18.5, 19.0, 19.5, 17.76, 17.36, 17.0]
    return pd.concat([pd.DataFrame({"date": dates, "ticker": "^VIX", "close": a, "source": "yfinance"}),
                      pd.DataFrame({"date": dates, "ticker": "VIXCLS", "close": b, "source": "fred"})], ignore_index=True)


def test_replay_runs_the_real_check_day_by_day():
    days = incidents.replay(incident_frame(), PAIR).set_index("date")
    assert days.loc["2026-02-06", "status"] == checks.Status.FAIL
    assert round(days.loc["2026-02-06", "gap"], 2) == 2.61
    assert (days.drop(pd.Timestamp("2026-02-06"))["status"] == checks.Status.OK).all()


def test_summary_states_the_values_and_the_checks_verdict():
    line = incidents.summary(incident_frame(), PAIR)
    assert line == ("On Fri Feb 06, 2026, Yahoo's VIX close was 20.37 and FRED's was 17.76, a gap of 2.61. "
                    "The real reconciliation check, run on that day's data, returns FAIL (fail at ≥ 0.5).")


def test_summary_is_honest_if_the_data_no_longer_shows_the_gap():
    # If Yahoo has since corrected its history, the page must say the check would pass, not claim a catch
    line = incidents.summary(incident_frame(gap_on_day=0.0), PAIR)
    assert "returns OK" in line and "would not have caught it" in line


def test_ensure_saves_both_sources_once(tmp_path, monkeypatch):
    inc = {**incidents.VIX_FEB_2026, "path": tmp_path / "inc" / "vix.csv"}
    df = incident_frame()
    calls = []
    monkeypatch.setattr(ingest, "fetch_yfinance", lambda t, days: calls.append("y") or df[df["ticker"] == "^VIX"])
    monkeypatch.setattr(ingest, "fetch_fred", lambda s, days: calls.append("f") or df[df["ticker"] == "VIXCLS"])
    assert incidents.ensure(inc) and incidents.ensure(inc)
    assert calls == ["y", "f"]  # the second call finds the file and fetches nothing
    saved = incidents.load(inc)
    assert set(saved["ticker"]) == {"^VIX", "VIXCLS"} and "fetched_at" in saved


def test_ensure_refuses_a_one_sided_fetch(tmp_path, monkeypatch):
    inc = {**incidents.VIX_FEB_2026, "path": tmp_path / "vix.csv"}
    df = incident_frame()
    monkeypatch.setattr(ingest, "fetch_yfinance", lambda t, days: df[df["ticker"] == "^VIX"])
    monkeypatch.setattr(ingest, "fetch_fred", lambda s, days: df.iloc[0:0])
    assert not incidents.ensure(inc) and not inc["path"].exists()


# ---- track record ----

def logs():
    check_runs = pd.DataFrame([
        ("2026-10-31T17:13:44+00:00", "gaps", "^N225", "WARN", "5 missing business days in window"),
        ("2026-10-31T17:13:44+00:00", "freshness", "^TNX", "OK", ""),
        ("2026-11-02T00:20:36+00:00", "gaps", "^N225", "WARN", "5 missing business days in window"),
        ("2026-11-04T18:42:00+00:00", "gaps", "^N225", "OK", ""),
        ("2026-11-05T11:06:00+00:00", "sanity", "GC=F", "FAIL", "move is 12.0 robust sd"),
    ], columns=["run_at", "check_name", "ticker", "status", "detail"])
    refresh_runs = pd.DataFrame([("2026-11-05T11:06:00+00:00", "scheduler", "9")], columns=["run_at", "trigger", "github_run"])
    return check_runs, refresh_runs


def test_findings_merge_the_same_result_across_runs():
    f = history.findings(logs()[0])
    assert list(f["status"]) == ["FAIL", "WARN"]  # most recent first
    nikkei = f[f["series"] == "^N225"].iloc[0]
    assert nikkei["runs"] == 2 and nikkei["first seen"] == "Sat Oct 31" and nikkei["last seen"] == "Sun Nov 01"


def test_refreshes_label_trigger_and_timing_without_guessing():
    r = history.refreshes(*logs())
    assert r.iloc[0].to_dict() == {"ran (ET)": "Thu Nov 05, 6:06 AM", "trigger": "scheduler", "timing": "pre-open"}
    assert r.iloc[1].to_dict() == {"ran (ET)": "Wed Nov 04, 1:42 PM", "trigger": "not recorded", "timing": "after the open"}


def test_headline_counts():
    assert history.headline(*logs()) == ("Since Sat Oct 31, 2026: 4 refreshes, 5 checks logged, 2 WARN and 1 FAIL results. "
                                         "1 of 4 refreshes ran pre-open on a weekday.")


def test_empty_log():
    empty = pd.DataFrame(columns=["run_at", "check_name", "ticker", "status", "detail"])
    assert history.headline(empty, pd.DataFrame(columns=["run_at", "trigger", "github_run"])) == "No refreshes logged yet."
    assert history.findings(empty).empty


# ---- on the page ----

def page(tmp_path, monkeypatch, incident_path):
    db = tmp_path / "brief.db"
    conn = storage.connect(db)
    end = checks.expected_session(datetime.now(timezone.utc))
    dates = pd.bdate_range(end=end, periods=40)
    storage.upsert_prices(conn, pd.DataFrame({"date": dates, "ticker": "GC=F", "close": range(2000, 2040),
                                              "source": "yfinance", "fetched_at": "2026-11-05T11:06:00+00:00"}))
    check_runs, refresh_runs = logs()
    check_runs.to_sql("check_runs", conn, if_exists="append", index=False)
    for r in refresh_runs.itertuples():
        storage.log_refresh(conn, r.run_at, r.trigger, r.github_run)
    conn.close()
    monkeypatch.setattr(config, "DB_PATH", db)
    monkeypatch.setattr(config, "SUMMARY_PATH", tmp_path / "summary.json")
    monkeypatch.setitem(incidents.VIX_FEB_2026, "path", incident_path)
    return AppTest.from_file(str(ROOT / "app.py"), default_timeout=30).run()


def test_page_replays_the_incident_from_the_file(tmp_path, monkeypatch):
    path = tmp_path / "vix.csv"
    incident_frame().to_csv(path, index=False)
    at = page(tmp_path, monkeypatch, path)
    assert not at.exception
    text = " ".join(m.value for m in at.markdown)
    assert "a gap of 2.61" in text and "returns FAIL" in text
    replay = next(d.value for d in at.dataframe if "gap" in d.value.columns)
    assert list(replay.columns) == ["date", "Yahoo", "FRED", "gap", "status"] and "FAIL" in set(replay["status"])


def test_page_says_when_the_incident_isnt_downloaded(tmp_path, monkeypatch):
    at = page(tmp_path, monkeypatch, tmp_path / "missing.csv")
    assert any("hasn't been downloaded yet" in c.value for c in at.caption)
    assert not any("a gap of" in m.value for m in at.markdown)


def test_page_shows_the_track_record(tmp_path, monkeypatch):
    at = page(tmp_path, monkeypatch, tmp_path / "missing.csv")
    assert any(m.value.startswith("Since Sat Oct 31, 2026: 4 refreshes") for m in at.markdown)
    assert any(e.label == "What the checks found (2)" for e in at.expander)
