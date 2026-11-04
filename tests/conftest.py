"""Fail the run if any test changed the real data files."""
import hashlib
from pathlib import Path

import pytest

DATA = Path(__file__).resolve().parents[1] / "data"


def _digest():
    return {str(p.relative_to(DATA)): hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(DATA.rglob("*")) if p.is_file()}


@pytest.fixture(scope="session", autouse=True)
def real_data_untouched():
    before = _digest()
    yield
    assert _digest() == before, "a test changed a file in data/"
