"""The static site: daily snapshots, the pages built from them, and the archive.
Prices here are made up for the tests; the site only ever shows the refreshed database."""
import json
import os
import re
import shutil
import sqlite3
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from morning_brief import brief, checks, config, sitegen, storage  # noqa: E402

NOW = datetime(2026, 11, 5, 11, 10, tzinfo=timezone.utc)   # Thu 6:10am New York
SUMMARY = {"model": "m", "bullets": [{"bullet": "Fed <b>says</b> $10bn", "sources": [1]}], "error": None,
           "headlines": [{"id": 1, "source": "Fed", "title": "A headline", "link": "https://www.federalreserve.gov/x",
                          "published": "2026-11-04T20:00:00+00:00"}]}


def database(path: Path, fetched="2026-11-05T11:06:00+00:00") -> sqlite3.Connection:
    conn = storage.connect(path)
    end = checks.expected_session(NOW)
    rng = np.random.default_rng(1)
    for ticker, start in [("GC=F", 4000.0), ("^TNX", 4.2), ("ES=F", 7700.0)]:
        dates = pd.bdate_range(end=end, periods=80)
        closes = start * np.exp(np.cumsum(rng.normal(0, 0.01, 80))) if start > 10 else start + np.cumsum(rng.normal(0, 0.03, 80))
        storage.upsert_prices(conn, pd.DataFrame({"date": dates, "ticker": ticker, "close": closes,
                                                  "source": "yfinance", "fetched_at": fetched}))
    storage.log_refresh(conn, fetched, "scheduler", "1")
    return conn


@pytest.fixture
def cfg():
    c = config.load_config()
    c["instruments"] = [i for i in c["instruments"] if i["ticker"] in ("GC=F", "^TNX", "ES=F")]
    c.update(reconcile=[], schedules=[])
    return c


@pytest.fixture
def site(tmp_path, cfg, monkeypatch):
    monkeypatch.setattr(brief, "SNAPSHOT_DIR", tmp_path / "briefs")
    conn = database(tmp_path / "brief.db")
    older = brief.build(conn, cfg, pd.Timestamp(NOW) - pd.Timedelta(days=1), SUMMARY)
    brief.save(older)
    brief.save(brief.build(conn, cfg, NOW, SUMMARY))
    gold = [i for i in cfg["instruments"] if i["ticker"] == "GC=F"]  # one instrument keeps the demo fast
    out = tmp_path / "public"
    pages = sitegen.build(out, conn, cfg, SUMMARY, NOW, demo_instruments=gold)
    return out, pages


def page_data(html):
    return json.loads(re.search(r'<script id="page-data" type="application/json">(.*?)</script>', html, re.S).group(1))


def test_snapshot_is_one_file_per_new_york_day_and_later_runs_replace_it(tmp_path, cfg):
    conn = database(tmp_path / "brief.db")
    folder = tmp_path / "briefs"
    first = brief.save(brief.build(conn, cfg, NOW, SUMMARY), folder)
    again = brief.save(brief.build(conn, cfg, NOW + pd.Timedelta(hours=3), SUMMARY), folder)
    assert first == again and first.name == "2026-11-05.json"
    # 03:00 UTC on Nov 6 is still Nov 5 in New York
    late = brief.save(brief.build(conn, cfg, datetime(2026, 11, 6, 3, 0, tzinfo=timezone.utc), SUMMARY), folder)
    assert late.name == "2026-11-05.json"
    assert [s["date"] for s in brief.load_all(folder)] == ["2026-11-05"]


def test_snapshot_holds_what_the_page_shows(tmp_path, cfg):
    s = brief.build(database(tmp_path / "brief.db"), cfg, NOW, SUMMARY)
    assert s["as_of"] == "Thu Nov 05, 6:06 AM ET, pre-open"
    assert s["coverage"]["instruments"] == 3 and s["status"] in ("OK", "WARN", "FAIL")
    assert {r["ticker"] for g in s["groups"] for r in g["rows"]} == {"GC=F", "^TNX", "ES=F"}
    assert s["tiles"] == ["ES=F", "^TNX", "GC=F"]  # the page's tile order
    assert s["note"].startswith("Morning Brief, data as of Thu Nov 05, 6:06 AM ET, pre-open")
    json.dumps(s)  # plain JSON all the way down


def test_site_has_latest_archive_and_one_page_per_day(site):
    out, pages = site
    assert {p.name for p in pages} == {"index.html", "2026-11-04.html", "2026-11-05.html", "archive.html", "404.html"}
    for f in ["assets/style.css", "assets/page.js", "assets/timing.js", "assets/vendor/chart.umd.js", ".nojekyll", "latest.json"]:
        assert (out / f).exists(), f
    archive = (out / "archive.html").read_text()
    assert archive.index("briefs/2026-11-05.html") < archive.index("briefs/2026-11-04.html")  # newest first
    assert json.loads((out / "latest.json").read_text())["date"] == "2026-11-05"


def test_latest_page_shows_last_updated_and_links_home(site):
    html = (site[0] / "index.html").read_text()
    assert "Last updated: <strong>Thu Nov 05, 6:06 AM ET, pre-open</strong>" in html
    assert 'href="https://kc31415.github.io"' in html
    assert 'id="timing"' in html  # the browser judges staleness when the page is read
    data = page_data(html)
    assert data["mode"] == "latest" and data["last_fetch"] == "2026-11-05T11:06:00+00:00"
    assert "Gold" in data["demo"] and "+50% bad print" in data["demo"]["Gold"]
    assert data["demo"]["Gold"]["+50% bad print"]["status"] == "FAIL"
    assert set(data["history"]) == {"Gold", "US 10Y yield", "S&P 500 futures"}


def test_archived_page_is_marked_and_has_no_live_parts(site):
    html = (site[0] / "briefs" / "2026-11-04.html").read_text()
    assert "Archived brief for Wed Nov 04, 2026." in html and 'href="../index.html"' in html
    assert 'id="timing"' not in html and "Try to break it" not in html and "Track record" not in html
    assert 'href="../assets/style.css"' in html
    assert page_data(html)["mode"] == "archive"


def test_text_from_sources_is_escaped(site):
    html = (site[0] / "index.html").read_text()
    assert "Fed &lt;b&gt;says&lt;/b&gt; $10bn" in html and "<b>says</b>" not in html


def test_md_escapes_then_formats():
    assert str(sitegen.md("**Gold** <script>x</script> [FRED](https://fred.stlouisfed.org)")) == (
        '<strong>Gold</strong> &lt;script&gt;x&lt;/script&gt; <a href="https://fred.stlouisfed.org">FRED</a>')
    assert str(sitegen.md("[bad](javascript:alert(1))")) == "[bad](javascript:alert(1))"


def test_json_in_the_page_cannot_close_its_script_tag():
    assert "</script" not in str(sitegen.env().filters["tojson_safe"]({"x": "</script><script>alert(1)"}))


def test_sparkline_scales_into_the_box():
    svg = str(sitegen.sparkline([1, 2, 3], width=100, height=20))
    assert svg.startswith("<svg") and 'points="1.0,18.0 50.0,10.0 99.0,2.0"' in svg
    assert str(sitegen.sparkline([1])) == ""


def test_first_deploy_without_snapshots_builds_from_the_database(tmp_path, cfg, monkeypatch):
    monkeypatch.setattr(brief, "SNAPSHOT_DIR", tmp_path / "none")
    conn = database(tmp_path / "brief.db")
    pages = sitegen.build(tmp_path / "public", conn, cfg, None, NOW, demo_instruments=[])
    assert (tmp_path / "public" / "index.html").exists() and len(pages) == 4
    assert not (tmp_path / "none").exists()  # nothing saved by the build


def test_build_script_only_reads_the_database(tmp_path, monkeypatch):
    db = tmp_path / "brief.db"
    database(db).close()
    sqlite3.connect(db).execute("DROP TABLE refresh_runs").connection.commit()  # a database from before the run log
    before = db.read_bytes()
    conn = storage.connect_readonly(db)
    assert storage.load_refresh_runs(conn).empty  # the missing table exists in the in-memory copy
    conn.execute("INSERT INTO check_runs VALUES ('x', 'c', 't', 'OK', '')")
    assert db.read_bytes() == before


@pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")
def test_browser_timing_matches_python():
    r = subprocess.run(["node", "--test", "web/test/timing.test.js"], cwd=ROOT, capture_output=True, text=True,
                       env={**os.environ, "NODE_NO_WARNINGS": "1"})
    assert r.returncode == 0, r.stdout + r.stderr


def _yaml(name):
    import yaml
    return yaml.safe_load((ROOT / ".github" / "workflows" / name).read_text())


def test_pages_workflow_builds_from_main_and_deploys():
    flow = _yaml("pages.yml")
    on = flow[True]  # PyYAML reads `on` as True
    assert on["push"] == {"branches": ["main"]} and "workflow_call" in on and "workflow_dispatch" in on
    assert flow["permissions"] == {"contents": "read", "pages": "write", "id-token": "write"}
    build = flow["jobs"]["build"]["steps"]
    assert build[0]["with"]["ref"] == "main"
    assert any(s.get("run") == "python scripts/build_site.py --out public" for s in build)
    assert any(s.get("uses", "").startswith("actions/upload-pages-artifact") and s["with"]["path"] == "public" for s in build)
    deploy = flow["jobs"]["deploy"]
    assert deploy["environment"]["name"] == "github-pages" and deploy["concurrency"]["group"] == "pages"


def test_refresh_publishes_the_site_after_it_ran():
    flow = _yaml("refresh.yml")
    assert flow["jobs"]["refresh"]["outputs"]["ran"] == "${{ steps.guard.outputs.run }}"
    publish = flow["jobs"]["publish"]
    assert publish["needs"] == "refresh" and publish["uses"] == "./.github/workflows/pages.yml"
    assert publish["if"] == "always() && needs.refresh.outputs.ran == 'true'"
    assert publish["permissions"] == {"contents": "read", "pages": "write", "id-token": "write"}


def test_built_site_is_not_committed():
    assert "public/" in (ROOT / ".gitignore").read_text().splitlines()
