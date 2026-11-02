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


def chart(table: pd.DataFrame, cfg: dict) -> alt.LayerChart:
    warn, fail = cfg["move_warn_z"], cfg["move_fail_z"]
    # Keep the FAIL line on screen on a quiet day, and every bar on a wild one
    domain = [0, max(fail * 1.1, table["z"].max() * 1.05)]
    bars = alt.Chart(table).mark_bar(color=BAR, size=14, cornerRadiusEnd=4).encode(
        x=alt.X("z:Q", title="Latest move, in robust standard deviations", scale=alt.Scale(domain=domain),
                axis=alt.Axis(grid=False, labelColor=INK, titleColor=INK)),
        y=alt.Y("label:N", sort=None, title=None, axis=alt.Axis(labelLimit=320, labelColor="#0b0b0b", ticks=False, domain=False)),
        tooltip=[alt.Tooltip("name:N", title="Instrument"), alt.Tooltip("change:N", title="Move"),
                 alt.Tooltip("z:Q", title="Robust σ", format=".1f")],
    )
    lines = pd.DataFrame({"z": [warn, fail], "text": [f"WARN {warn:g}σ", f"FAIL {fail:g}σ"]})
    rules = alt.Chart(lines).mark_rule(color=INK, strokeDash=[4, 4]).encode(x="z:Q")
    labels = alt.Chart(lines).mark_text(color=INK, align="left", dx=4, dy=-6, baseline="bottom", fontSize=12).encode(
        x="z:Q", y=alt.value(0), text="text:N")
    return alt.layer(bars, rules, labels).properties(height=26 * len(table) + 10)
