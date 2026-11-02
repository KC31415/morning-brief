"""The "Try to break it" demo: real checks on a throwaway copy of the data."""
import hashlib
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from streamlit.testing.v1 import AppTest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from morning_brief import checks, config, demo, storage  # noqa: E402
from morning_brief.checks import Status  # noqa: E402

AS_OF = pd.Timestamp("2026-10-30 11:00", tz="UTC")
END = "2026-10-29"
CHECKS = {"lookback_days": 60, "stale_warn_bdays": 1, "stale_fail_bdays": 3, "gap_warn": 3, "move_warn_z": 4.0,
          "move_fail_z": 10.0, "frozen_changes": 10, "min_rows": 22}
SESSION = {"tz": "America/New_York", "close": "17:00", "complete": "last session", "calendar": "XNYS"}


def series(ticker, start=100.0, vol=0.01, source="yfinance"):
    rng = np.random.default_rng(0)
    dates = pd.bdate_range(end=END, periods=80)
    return pd.DataFrame({"date": dates, "ticker": ticker, "close": start * np.cumprod(1 + rng.normal(0, vol, 80)),
                         "source": source, "fetched_at": "2026-10-30T11:00:00+00:00"})


def inst(ticker, kind="price", source="yfinance", **extra):
    return {"ticker": ticker, "name": ticker, "group": "G", "kind": kind, "source": source, "session": "s",
            "calendar": "XNYS", **extra}


@pytest.fixture
def world():
    prices = pd.concat([series("GOLD"), series("TNX", 4.2, 0.001), series("DGS", 4.2, 0.001, "fred")], ignore_index=True)
    cfg = {"instruments": [inst("GOLD"), inst("TNX", "yield"), inst("DGS", "yield", "fred", reference=True)],
           "checks": CHECKS, "sessions": {"s": SESSION},
           "reconcile": [{"a": "TNX", "b": "DGS", "warn": 0.05, "fail": 0.15}]}
    return prices, cfg


def caught(sim):
    return {f.check for f in sim.findings}


def test_big_bad_print_fails_sanity_and_says_what_it_measured(world):
    sim = demo.simulate(*world, "GOLD", "bad_print", AS_OF)
    finding = next(f for f in sim.findings if f.check == "sanity")
    assert finding.status == Status.FAIL and "FAIL threshold is 10σ" in finding.measured
    assert sim.status_after == Status.FAIL
    assert sim.row_before["flag"] == "" and sim.row_after["flag"] == "❌"
    assert "+50.00%" in sim.row_after["Change"]


def test_small_bad_print_is_honestly_not_caught(world):
    sim = demo.simulate(*world, "GOLD", "small_print", AS_OF)
    assert sim.findings == [] and sim.status_after == sim.status_before
    assert "No check caught this" in sim.message and "WARN threshold is 4σ" in sim.message


def test_frozen_feed_fails_sanity(world):
    sim = demo.simulate(*world, "GOLD", "frozen", AS_OF)
    finding = next(f for f in sim.findings if f.check == "sanity")
    assert finding.status == Status.FAIL and "10" in finding.measured


def test_stale_ticker_fails_freshness(world):
    sim = demo.simulate(*world, "GOLD", "stale", AS_OF)
    finding = next(f for f in sim.findings if f.check == "freshness")
    assert finding.status == Status.FAIL and "FAIL threshold is 3" in finding.measured


def test_yield_scaled_by_ten_is_caught_by_reconciliation_not_sanity(world):
    # Scaling the whole feed leaves its day-to-day shape alone relative to its own history.
    sim = demo.simulate(*world, "TNX", "yield_x10", AS_OF)
    assert "reconciliation" in caught(sim) and "sanity" not in caught(sim)
    finding = next(f for f in sim.findings if f.check == "reconciliation")
    assert "FAIL threshold is 0.15" in finding.measured


def test_yield_fault_is_only_offered_for_yields(world):
    _, cfg = world
    assert "yield_x10" in demo.faults_for(cfg["instruments"][1])
    assert "yield_x10" not in demo.faults_for(cfg["instruments"][0])
    with pytest.raises(ValueError):
        demo.apply_fault(world[0], cfg["instruments"][0], "yield_x10", CHECKS, AS_OF)


def test_real_data_is_not_changed_by_any_fault(world):
    prices, cfg = world
    before = prices.copy(deep=True)
    for ticker, fault in [("GOLD", "bad_print"), ("GOLD", "small_print"), ("GOLD", "frozen"), ("GOLD", "stale"),
                          ("TNX", "yield_x10")]:
        demo.simulate(prices, cfg, ticker, fault, AS_OF)
        pd.testing.assert_frame_equal(prices, before)


def test_every_result_line_says_simulated(world):
    for fault in ["bad_print", "small_print"]:
        sim = demo.simulate(*world, "GOLD", fault, AS_OF)
        assert sim.banner.startswith("Simulated")
        assert sim.message.startswith("Simulated")
        assert all(f.text.startswith("Simulated") for f in sim.findings)
        assert sim.row_text.startswith("Simulated")


# ---------- the real page ----------
def real_banners(at):
    return [e.value for e in list(at.success) + list(at.warning) + list(at.error) if "Simulated" not in e.value]


@pytest.fixture
def page(tmp_path, monkeypatch):
    db = tmp_path / "brief.db"
    conn = sqlite3.connect(db)
    conn.executescript(storage.SCHEMA)
    end = checks.expected_session(datetime.now(timezone.utc), "XNYS")
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    for ticker, source in [("GC=F", "yfinance"), ("^TNX", "yfinance"), ("DGS10", "fred")]:
        dates = pd.bdate_range(end=end, periods=80)
        close = 4.2 + np.cumsum(np.random.default_rng(0).normal(0, 0.03, 80))
        storage.upsert_prices(conn, pd.DataFrame({"date": dates, "ticker": ticker, "close": close,
                                                  "source": source, "fetched_at": now}))
    storage.log_checks(conn, now, [checks.CheckResult("gaps", "GC=F", Status.OK, "seed")])
    conn.close()
    monkeypatch.setattr(config, "DB_PATH", db)
    monkeypatch.setattr(config, "SUMMARY_PATH", tmp_path / "summary.json")
    return db


def fingerprint(db):
    conn = sqlite3.connect(db)
    data = (conn.execute("SELECT * FROM prices ORDER BY date, ticker").fetchall(),
            conn.execute("SELECT * FROM check_runs").fetchall())
    conn.close()
    return data, hashlib.sha256(db.read_bytes()).hexdigest()


def inject(at, name, fault):
    at.selectbox(key="demo_instrument").set_value(name).run()
    at.selectbox(key="demo_fault").set_value(fault).run()
    return at.button(key="demo_inject").click().run()


def test_simulation_on_the_page_changes_no_data_or_history(page):
    at = AppTest.from_file(str(ROOT / "app.py"), default_timeout=30).run()
    before, banners = fingerprint(page), real_banners(at)
    at = inject(at, "Gold", demo.FAULTS["bad_print"])
    assert not at.exception
    assert fingerprint(page) == before
    assert real_banners(at) == banners


def test_page_labels_results_as_simulated_and_shows_the_measurement(page):
    at = AppTest.from_file(str(ROOT / "app.py"), default_timeout=30).run()
    assert not [e for e in at.error if "Simulated" in e.value]
    at = inject(at, "Gold", demo.FAULTS["bad_print"])
    text = " ".join(m.value for m in at.markdown)
    assert "Simulated" in text and "FAIL threshold is 10σ" in text
    assert any(e.value.startswith("Simulated banner") for e in at.error)


def test_page_is_honest_when_nothing_catches_the_fault(page):
    at = AppTest.from_file(str(ROOT / "app.py"), default_timeout=30).run()
    at = inject(at, "Gold", demo.FAULTS["small_print"])
    assert any("No check caught this" in i.value for i in at.info)


def test_invitation_sits_near_the_top(page):
    at = AppTest.from_file(str(ROOT / "app.py"), default_timeout=30).run()
    assert any("Try to break it" in m.value and "#try-to-break-it" in m.value for m in at.markdown)
