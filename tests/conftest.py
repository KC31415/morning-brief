"""Fail the run if any test changed the real data files."""
import hashlib
from pathlib import Path

import pytest

DATA = Path(__file__).resolve().parents[1] / "data"


def _digest():
    return {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(DATA.glob("*")) if p.is_file()}


@pytest.fixture(scope="session", autouse=True)
def real_data_untouched():
    before = _digest()
    yield
    assert _digest() == before, "a test changed a file in data/"
