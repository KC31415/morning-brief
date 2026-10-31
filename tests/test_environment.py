"""Tests should run on the Python version the GitHub workflows use."""
import re
import sys
from pathlib import Path

import pytest

WORKFLOWS = sorted((Path(__file__).resolve().parents[1] / ".github" / "workflows").glob("*.yml"))


@pytest.mark.parametrize("workflow", WORKFLOWS, ids=lambda p: p.name)
def test_python_matches_workflow(workflow):
    pinned = re.search(r'python-version:\s*"([\d.]+)"', workflow.read_text()).group(1)
    assert f"{sys.version_info.major}.{sys.version_info.minor}" == pinned
