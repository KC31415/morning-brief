"""The refresh guard, the run log, and the workflow and scheduler that drive them."""
import os
import re
import runpy
import shutil
import sqlite3
import subprocess
import sys
import tomllib
from pathlib import Path

import pandas as pd
import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from morning_brief import runs, storage  # noqa: E402

WORKFLOW = ROOT / ".github" / "workflows" / "refresh.yml"
# Thu Nov 5 2026: 11:05 UTC is 6:05am New York (EST)
MORNING = pd.Timestamp("2026-11-05 11:05", tz="UTC")


def test_scheduler_runs_when_nothing_ran_today():
    go, _ = runs.should_run("scheduler", ["2026-11-04T18:42:00+00:00"], MORNING)
    assert go


def test_second_automatic_trigger_skips_after_the_first_refreshed():
    go, reason = runs.should_run("github-cron", ["2026-11-05T11:06:30+00:00"], MORNING + pd.Timedelta(minutes=16))
    assert not go and "06:06" in reason


def test_manual_run_always_refreshes():
    assert runs.should_run("manual", ["2026-11-05T11:06:30+00:00"], MORNING)[0]


def test_today_is_the_new_york_date_not_utc():
    # 01:00 UTC Thu is 8pm Wed in New York, so a Wednesday-evening run is "today" until NY midnight
    go, _ = runs.should_run("scheduler", ["2026-11-05T00:30:00+00:00"], pd.Timestamp("2026-11-05 04:00", tz="UTC"))
    assert not go
    go, _ = runs.should_run("scheduler", ["2026-11-05T00:30:00+00:00"], MORNING)  # 6:05am Thu NY: a new day
    assert go


def test_guard_script_reads_the_log_and_writes_the_output(tmp_path, monkeypatch):
    db = tmp_path / "brief.db"
    conn = storage.connect(db)
    storage.log_refresh(conn, pd.Timestamp.now(tz="UTC").isoformat(timespec="seconds"), "scheduler", "1")
    conn.close()
    before = db.read_bytes()
    out = tmp_path / "out.txt"
    monkeypatch.setenv("REFRESH_TRIGGER", "github-cron")
    monkeypatch.setenv("GITHUB_OUTPUT", str(out))
    from morning_brief import config
    monkeypatch.setattr(config, "DB_PATH", db)
    main = runpy.run_path(str(ROOT / "scripts" / "should_refresh.py"), run_name="guard_test")["main"]
    assert main() is False
    assert out.read_text() == "run=false\n"
    assert db.read_bytes() == before  # the guard only reads


def test_guard_runs_on_a_database_from_before_the_run_log(tmp_path, monkeypatch):
    db = tmp_path / "brief.db"
    sqlite3.connect(db).execute("CREATE TABLE prices (date TEXT)").connection.close()
    from morning_brief import config
    monkeypatch.setattr(config, "DB_PATH", db)
    monkeypatch.setenv("REFRESH_TRIGGER", "scheduler")
    monkeypatch.delenv("GITHUB_OUTPUT", raising=False)
    assert runpy.run_path(str(ROOT / "scripts" / "should_refresh.py"), run_name="guard_test")["main"]() is True


def test_refresh_logs_its_trigger(tmp_path, monkeypatch):
    conn = storage.connect(tmp_path / "b.db")
    storage.log_refresh(conn, "2026-11-05T11:06:00+00:00", "scheduler", "123")
    assert storage.load_refresh_runs(conn).to_dict("records") == [
        {"run_at": "2026-11-05T11:06:00+00:00", "trigger": "scheduler", "github_run": "123"}]


def _flow():
    return yaml.safe_load(WORKFLOW.read_text())


def test_every_step_after_the_guard_is_gated_on_it():
    # A skipped run must not commit, touch the issue (a missing report counts as a failure) or ping
    steps = _flow()["jobs"]["refresh"]["steps"]
    names = [s.get("name") for s in steps]
    guarded = steps[names.index("Skip if today's refresh already ran") + 1:-1]
    assert guarded and all("steps.guard.outputs.run == 'true'" in s["if"] for s in guarded)


def test_workflow_runs_one_at_a_time_and_labels_its_trigger():
    flow = _flow()
    assert flow["concurrency"] == {"group": "refresh", "cancel-in-progress": False}
    trig = flow["jobs"]["refresh"]["env"]["REFRESH_TRIGGER"]
    assert "'github-cron'" in trig and "inputs.trigger" in trig
    on = flow[True]  # PyYAML reads the key `on` as True
    assert on["workflow_dispatch"]["inputs"]["trigger"]["default"] == "manual"


def test_backup_cron_line_is_unchanged():
    # Editing the cron line re-registers the schedule; it should only change on purpose
    assert '- cron: "21 11 * * 1-5"' in WORKFLOW.read_text()


def test_scheduler_targets_this_workflow_with_the_automatic_trigger():
    worker = (ROOT / "ops" / "scheduler" / "src" / "worker.js").read_text()
    assert 'const WORKFLOW = "refresh.yml"' in worker and 'trigger: "scheduler"' in worker
    assert "scheduler" in runs.AUTOMATIC and "github-cron" in runs.AUTOMATIC
    toml = tomllib.loads((ROOT / "ops" / "scheduler" / "wrangler.toml").read_text())
    assert toml["vars"] == {"REPO": "KC31415/morning-brief", "BRANCH": "main"}
    for cron in toml["triggers"]["crons"]:
        assert re.fullmatch(r"\d+ 11 \* \* 1-5", cron)  # weekdays, before 7:30am New York all year


@pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")
def test_scheduler_worker_unit_tests():
    r = subprocess.run(["node", "--test", "ops/scheduler/test/worker.test.mjs"], cwd=ROOT,
                       capture_output=True, text=True, env={**os.environ, "NODE_NO_WARNINGS": "1"})
    assert r.returncode == 0, r.stdout + r.stderr


# ---- Is the page showing today's pre-open data? ----
# Nov 5 2026 is a Thursday; New York is UTC-5 after Nov 1

def ts(s):
    return pd.Timestamp(s, tz="UTC")


def test_on_time_pre_open_refresh_is_quiet():
    assert runs.refresh_timing("2026-11-05T11:06:00+00:00", ts("2026-11-05 15:00")).level == "ok"


def test_missing_refresh_warns_once_it_was_expected():
    # 8:00am New York is 13:00 UTC in winter
    before = runs.refresh_timing("2026-11-04T11:06:00+00:00", ts("2026-11-05 12:59"))
    after = runs.refresh_timing("2026-11-04T11:06:00+00:00", ts("2026-11-05 13:00"))
    assert before.level == "ok"
    assert after.level == "warn" and "hasn't run" in after.message and "Wed Nov 04, 6:06 AM ET" in after.message


def test_refresh_after_the_open_is_labeled():
    t = runs.refresh_timing("2026-11-04T18:42:00+00:00", ts("2026-11-04 19:00"))
    assert t.level == "info" and "1:42 PM ET, after the US open" in t.message


def test_weekend_is_quiet():
    assert runs.refresh_timing("2026-11-06T11:06:00+00:00", ts("2026-11-07 15:00")).level == "ok"


def test_no_refresh_ever_warns():
    assert runs.refresh_timing(None, ts("2026-11-05 15:00")).level == "warn"


def test_summer_uses_new_york_daylight_time():
    # Jul 1 2026: 8:00am New York is 12:00 UTC
    assert runs.refresh_timing("2026-06-30T11:06:00+00:00", ts("2026-07-01 12:01")).level == "warn"
    assert runs.refresh_timing("2026-07-01T11:06:00+00:00", ts("2026-07-01 12:01")).level == "ok"


def test_as_of_label_says_when_relative_to_the_open():
    assert runs.as_of_label("2026-11-05T11:06:00+00:00") == "Thu Nov 05, 6:06 AM ET, pre-open"
    assert runs.as_of_label("2026-11-04T18:42:00+00:00") == "Wed Nov 04, 1:42 PM ET, after the US open"
    assert runs.as_of_label("2026-11-07T15:00:00+00:00") == "Sat Nov 07, 10:00 AM ET, weekend"
    assert runs.as_of_label(None) == "never"
