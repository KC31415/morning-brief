"""The page's own track record: every logged refresh, when it ran, and what the checks found.

Built from check_runs and refresh_runs, which every refresh writes. Nothing here is
estimated: a run from before triggers were logged says "not recorded".
"""
import pandas as pd

from morning_brief import runs


def refreshes(check_runs: pd.DataFrame, refresh_runs: pd.DataFrame) -> pd.DataFrame:
    """One row per refresh, newest first: when it ran (New York), what started it, and pre-open or not."""
    times = sorted(set(check_runs["run_at"]) | set(refresh_runs["run_at"]), reverse=True)
    trigger = dict(zip(refresh_runs["run_at"], refresh_runs["trigger"]))
    rows = []
    for t in times:
        ny = runs.to_ny(t)
        when = "weekend" if ny.weekday() >= 5 else "pre-open" if runs.is_pre_open(t) else "after the open"
        rows.append({"ran (ET)": f"{ny:%a %b %d, %-I:%M %p}", "trigger": trigger.get(t, "not recorded"), "timing": when})
    return pd.DataFrame(rows, columns=["ran (ET)", "trigger", "timing"])


def findings(check_runs: pd.DataFrame) -> pd.DataFrame:
    """Each WARN or FAIL the checks raised, merged across runs: first and last seen, and how many runs had it."""
    bad = check_runs[check_runs["status"] != "OK"]
    if bad.empty:
        return pd.DataFrame(columns=["status", "check", "series", "first seen", "last seen", "runs", "latest detail"])
    g = bad.sort_values("run_at").groupby(["status", "check_name", "ticker"], dropna=False)
    out = g.agg(first=("run_at", "min"), last=("run_at", "max"), runs=("run_at", "nunique"), detail=("detail", "last"))
    out = out.reset_index().sort_values("last", ascending=False)
    fmt = lambda t: f"{runs.to_ny(t):%a %b %d}"  # noqa: E731
    return pd.DataFrame({"status": out["status"], "check": out["check_name"], "series": out["ticker"].fillna(""),
                         "first seen": out["first"].map(fmt), "last seen": out["last"].map(fmt),
                         "runs": out["runs"], "latest detail": out["detail"]}).reset_index(drop=True)


def headline(check_runs: pd.DataFrame, refresh_runs: pd.DataFrame) -> str:
    if check_runs.empty:
        return "No refreshes logged yet."
    n_runs = check_runs["run_at"].nunique()
    first = runs.to_ny(check_runs["run_at"].min())
    counts = check_runs["status"].value_counts()
    timing = refreshes(check_runs, refresh_runs)["timing"]
    return (f"Since {first:%a %b %d, %Y}: {n_runs} refreshes, {len(check_runs):,} checks logged, "
            f"{counts.get('WARN', 0)} WARN and {counts.get('FAIL', 0)} FAIL results. "
            f"{(timing == 'pre-open').sum()} of {n_runs} refreshes ran pre-open on a weekday.")
