"""Each row must say what period its change covers."""
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from morning_brief import moves  # noqa: E402
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
