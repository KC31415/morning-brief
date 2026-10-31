"""The LLM output validator must drop bullets that cite headlines we never sent."""
import json
import sys
import types
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from morning_brief.summarize import build_prompt, summarize, validate  # noqa: E402

ITEMS = [{"id": 1, "source": "Fed", "title": "Fed holds rates", "summary": "", "link": "x"},
         {"id": 2, "source": "CNBC", "title": "Oil jumps 3%", "summary": "", "link": "y"}]


def test_valid_bullets_kept():
    raw = json.dumps([{"bullet": "Fed on hold.", "sources": [1]}, {"bullet": "Oil up.", "sources": [2]}])
    assert len(validate(raw, ITEMS)) == 2


def test_invented_citation_dropped():
    raw = json.dumps([{"bullet": "Made-up claim.", "sources": [9]}, {"bullet": "Oil up.", "sources": [2]}])
    out = validate(raw, ITEMS)
    assert [b["bullet"] for b in out] == ["Oil up."]


def test_uncited_bullet_dropped():
    assert validate(json.dumps([{"bullet": "No source.", "sources": []}]), ITEMS) == []


def test_code_fenced_json_is_parsed():
    raw = "```json\n" + json.dumps([{"bullet": "Fed on hold.", "sources": [1]}]) + "\n```"
    assert len(validate(raw, ITEMS)) == 1


def test_prompt_contains_ids():
    assert "[1]" in build_prompt(ITEMS) and "[2]" in build_prompt(ITEMS)


def fake_anthropic(monkeypatch, response):
    def create(**kwargs):
        if isinstance(response, Exception):
            raise response
        return types.SimpleNamespace(content=[types.SimpleNamespace(text=response)])

    client = types.SimpleNamespace(messages=types.SimpleNamespace(create=create))
    monkeypatch.setitem(sys.modules, "anthropic", types.SimpleNamespace(Anthropic=lambda: client))
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")


def test_unparseable_response_keeps_prompt_and_raw(monkeypatch):
    fake_anthropic(monkeypatch, "not json")
    out = summarize(ITEMS)
    assert out["prompt"] == build_prompt(ITEMS)
    assert out["raw_response"] == "not json"
    assert out["bullets"] == [] and "summary failed" in out["error"]


def test_api_failure_keeps_prompt(monkeypatch):
    fake_anthropic(monkeypatch, RuntimeError("api down"))
    out = summarize(ITEMS)
    assert out["prompt"] == build_prompt(ITEMS)
    assert out["raw_response"] is None and "api down" in out["error"]
