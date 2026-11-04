"""Each row must say what period its change covers."""
import sys
from urllib.parse import urlparse
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from morning_brief import moves  # noqa: E402
from morning_brief.checks import Status  # noqa: E402
from morning_brief.config import load_config  # noqa: E402

FRI = pd.Timestamp("2026-10-30")
PRE_OPEN = "2026-10-30T11:00:00+00:00"  # 7am New York
FUTURES = {"tz": "America/New_York", "close": "17:00", "complete": "last session"}
TOKYO = {"tz": "Asia/Tokyo", "close": "15:30", "complete": "last session"}
BONDS = {"tz": "America/New_York", "close": "15:30", "complete": "prior US session"}


def test_session_still_open_is_live():
    assert moves.change_basis(FRI, PRE_OPEN, FUTURES) == "live"


def test_asia_closed_by_pre_open_is_last_session():
    assert moves.change_basis(FRI, PRE_OPEN, TOKYO) == "last session"


def test_yesterdays_yield_is_prior_us_session():
    assert moves.change_basis(pd.Timestamp("2026-10-29"), PRE_OPEN, BONDS) == "prior US session"


def test_futures_are_not_live_on_a_saturday():
    assert moves.change_basis(FRI, "2026-10-31T17:00:00+00:00", FUTURES) == "last session"


def test_date_span_shows_both_ends():
    assert moves.date_span(pd.Timestamp("2026-10-29"), FRI) == "Thu 10-29 → Fri 10-30"


def test_every_instrument_has_a_known_session():
    cfg = load_config()
    assert all(i["session"] in cfg["sessions"] for i in cfg["instruments"])


def test_usd_cnh_and_cny_are_not_configured():
    tickers = {i["ticker"] for i in load_config()["instruments"]}
    assert not tickers & {"USDCNH=X", "CNH=X", "CNH=F", "USDCNY=X"}


def test_news_feeds_are_market_focused():
    urls = [f["url"] for f in load_config()["news_feeds"]]
    assert not [u for u in urls if "mw_topstories" in u]  # mostly personal finance
    assert len(urls) == len(set(urls))


def test_news_feeds_are_official_sources_with_clear_reuse_terms():
    # See build notes: each host's terms allow showing its headlines with links.
    hosts = {urlparse(f["url"]).hostname for f in load_config()["news_feeds"]}
    assert hosts == {"www.federalreserve.gov", "www.ecb.europa.eu", "apps.bea.gov", "www.eia.gov"}


def test_dollars_are_escaped_for_markdown():
    assert moves.escape_dollars("$10bn to about $20bn") == r"\$10bn to about \$20bn"


def test_decimals_depend_on_asset_type():
    assert moves.format_last(1.11834, "price", "FX") == "1.1183"
    assert moves.format_last(7614.0, "price", "Equities") == "7614.00"
    assert moves.format_last(4.9286, "yield", "Rates") == "4.929"


def test_fred_3m_row_name_matches_its_yahoo_row():
    names = {i["ticker"]: i["name"] for i in load_config()["instruments"]}
    assert names["DTB3"] == "US 3M T-bill rate (FRED)"


@pytest.mark.parametrize("status,mark", [(Status.OK, "✓"), (Status.WARN, "⚠"), (Status.FAIL, "✗")])
def test_cross_check_label_is_short_and_shows_the_result(status, mark):
    assert moves.cross_check_label("ecb", status) == f"{mark} ECB"


def test_published_date_is_shown_when_known():
    assert moves.published_date("2026-10-30T14:00:00+00:00") == "2026-10-30"
    assert moves.published_date(None) is None


def test_banner_counts_use_the_right_plural():
    assert moves.count_label(1, "data warning", "data warnings") == "1 data warning"
    assert moves.count_label(2, "data warning", "data warnings") == "2 data warnings"


def test_change_tint_follows_direction_and_leaves_flat_or_missing_plain():
    assert moves.change_tint("+1.20%") == moves.change_tint("+0.5 bp") != ""
    assert moves.change_tint("-1.20%") == moves.change_tint("-2.5 bp") != ""
    assert moves.change_tint("+1.20%") != moves.change_tint("-1.20%")
    assert moves.change_tint("+0.00%") == moves.change_tint("-0.0 bp") == moves.change_tint("n/a") == ""


def test_fetched_time_is_readable():
    assert moves.format_fetched("2026-10-31T17:57:15+00:00") == "Sat Oct 31, 17:57 UTC"
    assert moves.format_fetched(None) == "never"


def test_cross_check_label_can_show_the_compared_value_and_date():
    label = moves.cross_check_label("fred", Status.OK, "4.980", pd.Timestamp("2026-10-29"))
    assert label == "✓ FRED 4.980 (Thu 10-29)"


@pytest.mark.parametrize("fetched,now,stale", [
    ("2026-11-02T11:00:00+00:00", "2026-11-03 10:59", False),  # Mon run, just before Tue's
    ("2026-10-30T11:00:00+00:00", "2026-11-02 10:59", False),  # the weekend doesn't count
    ("2026-10-31T17:00:00+00:00", "2026-11-02 12:00", False),  # Saturday run, viewed Monday
    ("2026-10-30T11:00:00+00:00", "2026-11-03 12:00", True),   # Fri run, Mon's and Tue's missed
    ("2026-11-02T11:00:00+00:00", "2026-11-04 12:00", True),
    (None, "2026-11-04 12:00", True),
])
def test_fetch_stale_after_more_than_one_business_day(fetched, now, stale):
    assert moves.is_fetch_stale(fetched, pd.Timestamp(now, tz="UTC")) is stale


def test_coarse_cross_check_passes_with_approx_not_tick():
    label = moves.cross_check_label("fred", Status.OK, "99.64", pd.Timestamp("2026-11-03"), coarse=True)
    assert label.startswith("≈ FRED 99.64") and label.endswith(", coarse")
    assert moves.cross_check_label("fred", Status.WARN, coarse=True).startswith("⚠")


def test_coarse_tickers_reads_both_sides_of_a_pair():
    pairs = [{"a": "CL=F", "b": "DCOILWTICO", "coarse": True}, {"a": "^VIX", "b": "VIXCLS"}]
    assert moves.coarse_tickers(pairs) == {"CL=F", "DCOILWTICO"}
