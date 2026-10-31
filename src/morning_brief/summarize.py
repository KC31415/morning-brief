"""Turn overnight headlines into a few cited bullets with an LLM.

Guardrails, because a wrong summary is worse than none:
  * the model only sees the headlines we pass in and is told to use nothing else
  * every bullet must cite headline ids; bullets citing ids we never sent are dropped
  * the raw prompt and response are saved so summaries can be reviewed later
  * with no API key, or on any error, the dashboard falls back to raw headlines
"""
import json
import logging
import os

log = logging.getLogger(__name__)

MODEL = os.getenv("SUMMARY_MODEL", "claude-haiku-5-5")

PROMPT = """You are preparing a pre-open market brief for a trading desk.
Using ONLY the headlines below, write 3 to 5 bullets on what matters for today's open.
Do not add facts, numbers or context that are not in the headlines.
Each bullet must cite the ids of the headlines it is based on.

Respond with JSON only, in this form:
[{{"bullet": "...", "sources": [1, 4]}}]

Headlines:
{headlines}
"""


def build_prompt(items: list[dict]) -> str:
    lines = [f"[{i['id']}] ({i['source']}) {i['title']} - {i['summary'][:200]}" for i in items]
    return PROMPT.format(headlines="\n".join(lines))


def validate(raw: str, items: list[dict]) -> list[dict]:
    """Parse the model output and keep only bullets whose citations are real."""
    valid_ids = {i["id"] for i in items}
    text = raw.strip()
    if text.startswith("```"):
        text = text.strip("`").removeprefix("json").strip()
    bullets = json.loads(text)
    kept = []
    for b in bullets:
        cited = [s for s in b.get("sources", []) if s in valid_ids]
        if b.get("bullet") and cited and len(cited) == len(b["sources"]):
            kept.append({"bullet": b["bullet"].strip(), "sources": cited})
        else:
            log.warning("dropped bullet with missing or invalid citations: %s", b)
    return kept


def summarize(items: list[dict]) -> dict:
    result = {"model": MODEL, "bullets": [], "prompt": None, "raw_response": None, "error": None}
    if not items:
        result["error"] = "no headlines"
        return result
    if not os.getenv("ANTHROPIC_API_KEY"):
        result["error"] = "no API key set; showing headlines only"
        return result
    try:
        import anthropic

        # Save each piece as soon as we have it: failed runs are the ones worth reviewing
        result["prompt"] = build_prompt(items)
        msg = anthropic.Anthropic().messages.create(
            model=MODEL, max_tokens=2000, messages=[{"role": "user", "content": result["prompt"]}]
        )
        # The response can start with a thinking block, which has no .text
        raw = next((b.text for b in msg.content if b.type == "text"), None)
        if raw is None:
            result["error"] = "summary failed: response had no text block"
            return result
        result["raw_response"] = raw
        result["bullets"] = validate(raw, items)
    except Exception as exc:
        log.exception("summary failed")
        result["error"] = f"summary failed: {exc}"
    return result
