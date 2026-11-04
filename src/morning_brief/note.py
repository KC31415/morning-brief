"""A plain-text morning note built from the page's own numbers, ready to paste into chat or email.

No LLM: every figure is the same one the page shows, and every caveat the page shows
travels with it, so a pasted note can't look more certain than the page did.
"""
import pandas as pd

from morning_brief import moves, runs

TOP_MOVES = 5
RATES = ["^IRX", "^FVX", "^TNX"]


def build(table: pd.DataFrame, ranked: pd.DataFrame, results: list, last_fetch, view, n_cross: int,
          cfg: dict, url: str = "https://kechunwu.github.io/morning-brief/") -> str:
    _, banner = moves.banner_message(results)
    lines = [f"Morning Brief, data as of {runs.as_of_label(last_fetch)}",
             f"Data checks: {banner} ({moves.count_label(len(results), "check", "checks")}; {n_cross} of {len(table)} instruments cross-checked)"]

    flagged = table[table["flag"] != ""]
    if not flagged.empty:
        lines.append("Flagged, don't rely on: " + ", ".join(f"{r['name']} {r['flag']}" for _, r in flagged.iterrows()))

    if not ranked.empty:
        warn = cfg["checks"]["move_warn_z"]
        lines.append(f"\nBiggest moves against their own volatility (WARN at {warn:g}σ):")
        for _, r in ranked.head(TOP_MOVES).iterrows():
            lines.append(f"  {r['name']} {r['change']} ({r['z']:.1f}σ)")

    by = table.set_index("ticker")
    rates = [f"{by.loc[t, 'name'].replace('US ', '')} {by.loc[t, 'last']} ({by.loc[t, 'Change']})"
             for t in RATES if t in by.index and pd.notna(by.loc[t, "last"])]
    if rates:
        lines.append("\nUS rates: " + ", ".join(rates))

    lines.append("\nScheduled today:")
    if view.state == "not_loaded":
        lines.append("  Calendar couldn't be loaded, so this says nothing about today's events.")
    else:
        for row in view.today:
            names = "/".join(name for name, _ in row["sources"])
            lines.append(f"  {row['time']} {row['event']} ({names})")
        if not view.today:
            lines.append("  Nothing listed in the calendars that loaded.")
        if view.failed:
            lines.append(f"  Couldn't load: {', '.join(view.failed)}.")
    lines.append("  Not covered: BLS (CPI, jobs). Check bls.gov.")

    lines.append(f"\nChanges cover different periods by market; 'live' means the session was open when fetched, "
                 f"not a real-time price. Free public data, not production market data. {url}")
    return "\n".join(lines)
