"""Keep one GitHub issue open while data checks are failing.

The refresh writes its FAILs to a report file. A later workflow step reads it and
syncs the issue, so an alert goes out even if committing the data fails.
"""
import json
from pathlib import Path

from morning_brief.checks import CheckResult, Status

TITLE = "Data checks failing"


def failures(results: list[CheckResult]) -> list[dict]:
    return [{"check": r.check, "ticker": r.ticker, "detail": r.detail} for r in results if r.status == Status.FAIL]


def write_report(path: Path, failed: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(failed, indent=2))


def read_report(path: Path) -> list[dict]:
    """No report means the refresh died before finishing its checks, which is a failure too."""
    if not path.exists():
        return [{"check": "refresh", "ticker": None, "detail": "crashed before the checks finished; see the run log"}]
    return json.loads(path.read_text())


def issue_body(failed: list[dict]) -> str:
    rows = "\n".join(f"| {f['check']} | {f['ticker'] or ''} | {f['detail']} |"
                     for f in sorted(failed, key=lambda f: (f["check"], f["ticker"] or "")))
    return f"The scheduled refresh has failing checks:\n\n| Check | Ticker | Detail |\n|---|---|---|\n{rows}\n"


def sync_issue(failed: list[dict], gh, run_url: str = "") -> None:
    """`gh` runs a GitHub CLI command given its arguments and returns its output."""
    listed = json.loads(gh("issue", "list", "--state", "open", "--limit", "100", "--json", "number,title,body"))
    existing = [i for i in listed if i["title"] == TITLE]
    if not failed:
        for i in existing:
            gh("issue", "close", str(i["number"]), "--comment", f"The latest refresh had no failing checks. {run_url}".strip())
        return
    body = issue_body(failed)
    if not existing:
        gh("issue", "create", "--title", TITLE, "--body", f"{body}\n{run_url}".strip())
    elif not existing[0]["body"].startswith(body):
        number = str(existing[0]["number"])
        gh("issue", "edit", number, "--body", f"{body}\n{run_url}".strip())
        gh("issue", "comment", number, "--body", f"The failing checks changed. {run_url}".strip())
