"""The "How unusual is today?" chart ranks by the sanity check's own number."""
import re
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from streamlit.testing.v1 import AppTest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from morning_brief import checks, ranking, storage  # noqa: E402
from morning_brief import config as settings  # noqa: E402

CFG = {"lookback_days": 60, "move_warn_z": 4.0, "move_fail_z": 10.0, "frozen_changes": 10}


def series(ticker, last_move=0.0, n=80, seed=0):
    closes = 100 * np.cumprod(1 + np.random.default_rng(seed).normal(0, 0.01, n))
    closes[-1] = closes[-2] * (1 + last_move)
    return pd.DataFrame({"date": pd.bdate_range(end="2026-10-29", periods=n), "ticker": ticker, "close": closes})


def inst(ticker, kind="price", **extra):
    return {"ticker": ticker, "name": ticker, "group": "G", "kind": kind, "source": "yfinance", **extra}


def config(*instruments):
    return {"instruments": list(instruments), "checks": CFG}


def world():
    prices = pd.concat([series("CALM", 0.001), series("WILD", -0.05), series("MID", 0.02), series("REF", 0.5),
                        series("NEW", 0.01, n=5)], ignore_index=True)
    return prices, config(inst("CALM"), inst("WILD"), inst("MID"), inst("REF", reference=True), inst("NEW"))


def test_ranked_most_unusual_first_and_reference_series_left_out():
    table, skipped = ranking.unusual_moves(*world())
    assert list(table["name"]) == ["WILD", "MID", "CALM"]
    assert skipped == ["NEW"]


def test_label_has_the_plain_move_and_sigma_with_a_real_minus_sign():
    table, _ = ranking.unusual_moves(*world())
    z = table.set_index("name").loc["WILD", "z"]
    assert table.set_index("name").loc["WILD", "label"] == f"WILD −5.00%, {z:.1f}σ"


def test_yields_show_basis_points():
    prices = series("Y")
    prices["close"] = 4 + np.cumsum(np.random.default_rng(1).normal(0, 0.03, 80))
    prices.loc[prices.index[-1], "close"] = prices["close"].iloc[-2] + 0.05
    table, _ = ranking.unusual_moves(prices, config(inst("Y", "yield")))
    assert "+5.0 bp" in table["label"].iloc[0]


def test_values_match_what_the_sanity_check_reports():
    prices, cfg = world()
    table, _ = ranking.unusual_moves(prices, cfg)
    sanity = {r.ticker: r.detail for r in checks.check_sanity(prices, cfg["instruments"], {**CFG, "min_rows": 22})}
    for _, row in table.iterrows():
        assert f"{row['z']:.1f}" == re.search(r"is ([\d.]+) robust", sanity[row["ticker"]]).group(1)


def test_quiet_day_draws_warn_and_names_fail_at_the_edge():
    table, _ = ranking.unusual_moves(*world())
    table = table.assign(z=[3.2, 1.5, 0.1][:len(table)])
    spec = ranking.chart(table, CFG).to_dict()
    text = str(spec)
    assert "'WARN 4σ'" in text and "'FAIL 10σ →'" in text and "'FAIL 10σ'" not in text
    domain = spec["layer"][0]["encoding"]["x"]["scale"]["domain"]
    assert domain[0] == 0 and 4 < domain[1] < 10  # scaled to the data, WARN line in view


def test_headline_names_the_top_move_and_its_threshold():
    table, _ = ranking.unusual_moves(*world())
    line = ranking.headline(table, CFG)
    top = table.iloc[0]
    assert line.startswith(f"Most unusual move: **{top['name']} {top['change']}**, {top['z']:.1f}σ")
    assert top["z"] >= 4 and "past the 4σ WARN line" in line
    quiet = table.assign(z=[3.2] + list(table["z"].iloc[1:]))
    assert "Nothing reaches the 4σ WARN line" in ranking.headline(quiet, CFG)
    fail = table.assign(z=[12.0] + list(table["z"].iloc[1:]))
    assert "past the 10σ FAIL line" in ranking.headline(fail, CFG)
    assert ranking.headline(table.iloc[0:0], CFG) is None


def test_chart_stretches_to_fit_a_move_past_the_fail_line():
    prices = series("HUGE", 0.5)
    table, _ = ranking.unusual_moves(prices, config(inst("HUGE")))
    spec = ranking.chart(table, CFG).to_dict()
    domain = spec["layer"][0]["encoding"]["x"]["scale"]["domain"]
    assert domain[1] > table["z"].max() and domain[1] > 10
    assert "'FAIL 10σ'" in str(spec)  # drawn as a line once it's in view


def test_page_shows_the_ranking(tmp_path, monkeypatch):
    # A temporary database: opening the page must never touch the real data file
    path = tmp_path / "brief.db"
    conn = storage.connect(path)
    storage.upsert_prices(conn, series("GC=F").assign(source="yfinance", fetched_at="2026-10-29T11:00:00+00:00"))
    conn.close()
    monkeypatch.setattr(settings, "DB_PATH", path)
    monkeypatch.setattr(settings, "SUMMARY_PATH", tmp_path / "summary.json")
    at = AppTest.from_file(str(ROOT / "app.py"), default_timeout=30).run()
    assert not at.exception
    assert "How unusual is today?" in [s.value for s in at.subheader]
