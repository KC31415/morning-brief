"""The "Try to break it" demo: inject a fault into a copy of the data and rerun the real checks.

Nothing here touches the database. Every piece of text it returns says "Simulated".
"""
import re
from dataclasses import dataclass

import pandas as pd

from morning_brief import checks, moves
from morning_brief.calendars import sessions
from morning_brief.checks import Status

FAULTS = {
    "bad_print": "+50% bad print",
    "small_print": "+2% bad print",
    "frozen": "Frozen feed",
    "stale": "Stale ticker",
    "yield_x10": "Yield scaled ×10",
}


@dataclass
class Finding:
    check: str
    status: Status
    measured: str
    text: str


@dataclass
class Simulation:
    findings: list[Finding]
    status_before: Status
    status_after: Status
    banner: str
    message: str
    row_before: dict
    row_after: dict
    row_text: str


def faults_for(inst: dict) -> list[str]:
    return [f for f in FAULTS if f != "yield_x10" or inst["kind"] == "yield"]


def apply_fault(prices: pd.DataFrame, inst: dict, fault: str, cfg: dict, as_of) -> pd.DataFrame:
    """A changed copy of `prices`; the original is left alone."""
    if fault not in faults_for(inst):
        raise ValueError(f"{fault} does not apply to {inst['ticker']}")
    df = prices.copy(deep=True)
    rows = df.index[df["ticker"] == inst["ticker"]]
    rows = df.loc[rows].sort_values("date").index
    if fault in ("bad_print", "small_print"):
        # Set from the previous close, so the move is exactly the size the fault's label says
        df.loc[rows[-1], "close"] = df.loc[rows[-2], "close"] * (1.5 if fault == "bad_print" else 1.02)
    elif fault == "frozen":
        n = cfg["frozen_changes"]
        df.loc[rows[-n:], "close"] = df.loc[rows[-n - 1], "close"]
    elif fault == "yield_x10":
        df.loc[rows, "close"] *= 10  # a unit error affects the whole feed, not one day
    elif fault == "stale":
        # Keep only rows old enough to be past the FAIL threshold
        expected = checks.expected_session(as_of, inst.get("calendar"))
        recent = sessions(inst.get("calendar"), expected - pd.Timedelta(days=30), expected)
        df = df.drop(rows[df.loc[rows, "date"] >= recent[-cfg["stale_fail_bdays"]]])
    return df


def _threshold_text(status: Status, warn, fail, unit: str = "") -> str:
    if status == Status.FAIL:
        return f"FAIL threshold is {fail:g}{unit}"
    return f"WARN threshold is {warn:g}{unit}; FAIL is {fail:g}{unit}"


def _measured(r: checks.CheckResult, prices: pd.DataFrame, inst: dict, config: dict) -> str:
    cfg = config["checks"]
    if r.check == "sanity" and "frozen" in r.detail:
        return f"{r.detail}; FAIL threshold is {cfg['frozen_changes']} unchanged sessions"
    if r.check == "sanity":
        z = checks.latest_move_z(prices, inst, cfg)
        return f"move was {z:.1f}σ; {_threshold_text(r.status, cfg['move_warn_z'], cfg['move_fail_z'], 'σ')}"
    if r.check == "freshness":
        behind = re.search(r"\((\d+) sessions behind\)", r.detail).group(1)
        return f"{behind} sessions behind; {_threshold_text(r.status, cfg['stale_warn_bdays'], cfg['stale_fail_bdays'])}"
    if r.check == "reconciliation":
        pair = next(p for p in config["reconcile"] if checks.pair_name(p) == r.ticker)
        return f"sources {r.detail}; {_threshold_text(r.status, pair['warn'], pair['fail'])}"
    return r.detail


def _not_caught(prices: pd.DataFrame, inst: dict, cfg: dict, fault: str) -> str:
    text = f"Simulated: No check caught this. {FAULTS[fault]} on {inst['name']} stayed inside every threshold."
    z = checks.latest_move_z(prices, inst, cfg)
    if z is not None:
        text += f" The move was {z:.1f}σ; WARN threshold is {cfg['move_warn_z']:g}σ."
    return text + " A real error this small would get through, which is why a second source matters."


def simulate(prices: pd.DataFrame, config: dict, ticker: str, fault: str, as_of, other_results=()) -> Simulation:
    """other_results are real results the fault can't affect, so the simulated banner counts them too."""
    inst = next(i for i in config["instruments"] if i["ticker"] == ticker)
    faulty = apply_fault(prices, inst, fault, config["checks"], as_of)
    before = checks.run_all(prices, config, as_of)
    after = checks.run_all(faulty, config, as_of)
    was = {(r.check, r.ticker): r.status for r in before}
    findings = []
    for r in after:
        if r.status > was.get((r.check, r.ticker), Status.OK):
            measured = _measured(r, faulty, inst, config)
            findings.append(Finding(r.check, r.status, measured,
                                    f"Simulated: **{r.check}** caught it ({r.status.name}): {measured}."))
    findings.sort(key=lambda f: -f.status)
    status_before, status_after = checks.overall_status(before), checks.overall_status(after)
    _, banner = moves.banner_message(after + list(other_results))
    row_before = moves.build_row(inst, prices, before, config)
    row_after = moves.build_row(inst, faulty, after, config)
    message = ("Simulated: the page would flag this." if findings
               else _not_caught(faulty, inst, config["checks"], fault))
    row_text = (f"Simulated row for {inst['name']}: last {row_before['last']} → {row_after['last']}, "
                f"change {row_before['Change']} → {row_after['Change']}, "
                f"flag {row_before['flag'] or 'none'} → {row_after['flag'] or 'none'}, "
                f"cross-check {row_before['cross-check']} → {row_after['cross-check']}.")
    return Simulation(findings, status_before, status_after, f"Simulated banner: {banner}", message,
                      row_before, row_after, row_text)
