"""One open GitHub issue while checks are failing, closed by the next clean run."""
import json
import runpy
import sys
from pathlib import Path

import pandas as pd
import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from morning_brief import alerts, config, ingest, news, schedules  # noqa: E402
from morning_brief.checks import CheckResult, Status  # noqa: E402

FAILS = [{"check": "freshness", "ticker": "ZW=F", "detail": "3 sessions behind"}]


class FakeGh:
    """Records gh commands and answers `issue list` from its open issues."""

    def __init__(self, open_issues=()):
        self.open = list(open_issues)
        self.calls = []

    def __call__(self, *args):
        self.calls.append(args)
        return json.dumps(self.open) if args[:2] == ("issue", "list") else ""

    def verbs(self):
        return [c[1] for c in self.calls if c[:2] != ("issue", "list")]


def issue(number=7, failures=FAILS):
    return {"number": number, "title": alerts.TITLE, "body": alerts.issue_body(failures)}


def test_fail_opens_an_issue_listing_the_checks():
    gh = FakeGh()
    alerts.sync_issue(FAILS, gh)
    assert gh.verbs() == ["create"]
    body = gh.calls[-1][gh.calls[-1].index("--body") + 1]
    assert "freshness" in body and "ZW=F" in body and "3 sessions behind" in body


def test_no_duplicate_while_one_is_open():
    gh = FakeGh([issue()])
    alerts.sync_issue(FAILS, gh)
    assert gh.verbs() == []


def test_changed_failures_update_the_open_issue():
    gh = FakeGh([issue()])
    alerts.sync_issue(FAILS + [{"check": "sanity", "ticker": "GC=F", "detail": "12 std devs"}], gh)
    assert gh.verbs() == ["edit", "comment"]


def test_clean_run_closes_the_issue():
    gh = FakeGh([issue()])
    alerts.sync_issue([], gh)
    assert gh.verbs() == ["close"] and gh.calls[-1][2] == "7"


def test_clean_run_with_no_issue_does_nothing():
    gh = FakeGh()
    alerts.sync_issue([], gh)
    assert gh.verbs() == []


def test_issues_with_other_titles_are_left_alone():
    gh = FakeGh([{"number": 3, "title": "Unrelated bug", "body": ""}])
    alerts.sync_issue([], gh)
    assert gh.verbs() == []


def test_only_fails_are_reported():
    results = [CheckResult("gaps", "A", Status.WARN, "w"), CheckResult("sanity", "B", Status.FAIL, "f"),
               CheckResult("gaps", "C", Status.OK, "")]
    assert alerts.failures(results) == [{"check": "sanity", "ticker": "B", "detail": "f"}]


def test_missing_report_counts_as_a_failure(tmp_path):
    # The refresh crashed before the checks ran: a clean run must not be assumed.
    out = alerts.read_report(tmp_path / "nope.json")
    assert len(out) == 1 and out[0]["check"] == "refresh"


def test_refresh_writes_the_report_and_it_round_trips(tmp_path, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "brief.db")
    monkeypatch.setattr(config, "SUMMARY_PATH", tmp_path / "summary.json")
    monkeypatch.setattr(config, "REPORT_PATH", tmp_path / "report.json")
    monkeypatch.setattr(ingest, "fetch_all", lambda instruments: pd.DataFrame())
    monkeypatch.setattr(news, "fetch_headlines", lambda feeds: [])
    monkeypatch.setattr(schedules, "fetch_all", lambda sources, now: ([], {}))
    main = runpy.run_path(str(ROOT / "scripts" / "refresh.py"), run_name="refresh_test")["main"]
    assert main() == 1  # no data at all, so completeness fails
    reported = alerts.read_report(tmp_path / "report.json")
    assert reported and all(r["check"] == "completeness" for r in reported if r["check"] != "reconciliation")


def test_workflow_runs_the_alert_even_after_a_failure_and_can_write_issues():
    flow = yaml.safe_load((ROOT / ".github" / "workflows" / "refresh.yml").read_text())
    job = flow["jobs"]["refresh"]
    assert flow["permissions"]["issues"] == "write"
    names = [s.get("name") for s in job["steps"]]
    step = next(s for s in job["steps"] if "scripts/alert.py" in s.get("run", ""))
    assert step["if"] == "always()" and step["env"]["GH_TOKEN"] == "${{ github.token }}"
    assert names.index(step["name"]) < names.index("Fail the job if any data check failed")
