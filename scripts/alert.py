"""Open, update or close the GitHub issue for failing checks. Runs in the refresh workflow.

    python scripts/alert.py
"""
import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from morning_brief import alerts  # noqa: E402
from morning_brief.config import REPORT_PATH  # noqa: E402


def gh(*args: str) -> str:
    return subprocess.run(["gh", *args], check=True, capture_output=True, text=True).stdout


if __name__ == "__main__":
    server, repo, run = (os.getenv(k, "") for k in ("GITHUB_SERVER_URL", "GITHUB_REPOSITORY", "GITHUB_RUN_ID"))
    run_url = f"{server}/{repo}/actions/runs/{run}" if run else ""
    alerts.sync_issue(alerts.read_report(REPORT_PATH), gh, run_url)
