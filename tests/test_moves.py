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
