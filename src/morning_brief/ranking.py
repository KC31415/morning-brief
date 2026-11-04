"""Rank instruments by how unusual the latest move is, using the sanity check's own number."""
import altair as alt
import pandas as pd

from morning_brief import checks, moves

BAR = "#2a78d6"
INK = "#52514e"


def unusual_moves(prices: pd.DataFrame, config: dict) -> tuple[pd.DataFrame, list[str]]:
    """Main instruments, most unusual first, and the names of any with too little history to judge."""
    rows, skipped = [], []
    for inst in config["instruments"]:
        if inst.get("reference"):
            continue
        z = checks.latest_move_z(prices, inst, config["checks"])
        if z is None:
            skipped.append(inst["name"])
            continue
        g = prices[prices["ticker"] == inst["ticker"]].sort_values("date")
        change = moves.change_text(g["close"].iloc[-1], g["close"].iloc[-2], inst["kind"]).replace("-", "−")
        rows.append({"ticker": inst["ticker"], "name": inst["name"], "change": change, "z": z,
                     "label": f"{inst['name']} {change}, {z:.1f}σ"})
    table = pd.DataFrame(rows, columns=["ticker", "name", "change", "z", "label"])
    return table.sort_values("z", ascending=False, ignore_index=True), skipped


def headline(table: pd.DataFrame, cfg: dict) -> str | None:
    """One sentence for the top of the page: the most unusual move, and whether it reaches a threshold.

    Computed from the same number as the sanity check, so it can't disagree with the flags.
    """
    if table.empty:
        return None
    top = table.iloc[0]
    warn, fail = cfg["move_warn_z"], cfg["move_fail_z"]
    lead = f"Most unusual move: **{top['name']} {top['change']}**, {top['z']:.1f}σ against its own recent volatility."
    if top["z"] >= fail:
        return lead + f" That's past the {fail:g}σ FAIL line, so treat it as a likely bad print until confirmed."
    if top["z"] >= warn:
        return lead + f" That's past the {warn:g}σ WARN line: unusual, worth checking against the news."
    return lead + f" Nothing reaches the {warn:g}σ WARN line."


def chart(table: pd.DataFrame, cfg: dict) -> alt.LayerChart:
    warn, fail = cfg["move_warn_z"], cfg["move_fail_z"]
    # Scale to the data with the WARN line in view. On a normal day the FAIL line would
    # leave most of the chart empty, so it's named at the right edge instead of drawn.
    top = max(warn * 1.25, table["z"].max() * 1.1)
    fail_in_view = fail <= top
    if fail_in_view:
        top = max(top, fail * 1.05)
    domain = [0, top]
    bars = alt.Chart(table).mark_bar(color=BAR, size=14, cornerRadiusEnd=4).encode(
        x=alt.X("z:Q", title="Latest move ÷ its own robust volatility (σ)", scale=alt.Scale(domain=domain),
                axis=alt.Axis(grid=False, labelColor=INK, titleColor=INK)),
        y=alt.Y("label:N", sort=None, title=None, axis=alt.Axis(labelLimit=320, labelColor="#0b0b0b", ticks=False, domain=False)),
        tooltip=[alt.Tooltip("name:N", title="Instrument"), alt.Tooltip("change:N", title="Move"),
                 alt.Tooltip("z:Q", title="Robust σ", format=".1f")],
    )
    drawn = [(warn, f"WARN {warn:g}σ")] + ([(fail, f"FAIL {fail:g}σ")] if fail_in_view else [])
    lines = pd.DataFrame({"z": [z for z, _ in drawn], "text": [t for _, t in drawn]})
    rules = alt.Chart(lines).mark_rule(color=INK, strokeDash=[4, 4]).encode(x="z:Q")
    labels = alt.Chart(lines).mark_text(color=INK, align="left", dx=4, dy=-6, baseline="bottom", fontSize=12).encode(
        x="z:Q", y=alt.value(0), text="text:N")
    layers = [bars, rules, labels]
    if not fail_in_view:
        off = pd.DataFrame({"z": [top], "text": [f"FAIL {fail:g}σ →"]})
        layers.append(alt.Chart(off).mark_text(color=INK, align="right", dy=-6, baseline="bottom", fontSize=12).encode(
            x="z:Q", y=alt.value(0), text="text:N"))
    return alt.layer(*layers).properties(height=26 * len(table) + 10)
