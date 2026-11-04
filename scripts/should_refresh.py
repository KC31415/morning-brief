"""Decide whether this workflow run should refresh. Runs first in the refresh workflow.

    REFRESH_TRIGGER=scheduler python scripts/should_refresh.py

Several triggers fire each weekday morning so one late or dropped trigger doesn't
cost the day. The first one refreshes; the rest see today's run and stop here.
Writes run=true or run=false to $GITHUB_OUTPUT when it's set.
"""
import os
import sqlite3
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from morning_brief import runs  # noqa: E402
from morning_brief.config import DB_PATH  # noqa: E402


def run_times(path: Path) -> list[str]:
    if not path.exists():
        return []
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)  # read only: the guard must not change the database
    try:
        return [r[0] for r in conn.execute("SELECT run_at FROM refresh_runs")]
    except sqlite3.OperationalError:  # a database from before runs were logged
        return []
    finally:
        conn.close()


def main() -> bool:
    trigger = os.getenv("REFRESH_TRIGGER") or "local"
    go, reason = runs.should_run(trigger, run_times(DB_PATH), pd.Timestamp.now(tz="UTC"))
    print(f"{'Refreshing' if go else 'Skipping'}: {reason}")
    if out := os.getenv("GITHUB_OUTPUT"):
        with open(out, "a") as f:
            f.write(f"run={'true' if go else 'false'}\n")
    return go


if __name__ == "__main__":
    main()
