"""DebateRequest/Result v1 JSON Schema 校验。"""

import json
from pathlib import Path

import jsonschema
from core.review_runner import run_review_sync

CONTRACTS = Path(__file__).resolve().parents[1] / "contracts"


class FakeLLM:
    provider = "fake"
    model = "fake"

    async def chat(self, system_prompt, user_prompt, max_tokens=None):
        if "裁判" in system_prompt:
            return '{"summary":"s","winner":"bear","key_insights":["k"],"topic_angle":"t"}'
        return '{"thesis":"t","arguments":["a","b"],"quote":"q","confidence":0.8}'


def _load(name):
    return json.loads((CONTRACTS / name).read_text(encoding="utf-8"))


def test_request_example_validates():
    schema = _load("debate_request.v1.json")
    example = _load("examples/debate_request.v1.example.json")
    jsonschema.validate(example, schema)


def test_result_example_validates():
    schema = _load("debate_result.v1.json")
    example = _load("examples/debate_result.v1.example.json")
    jsonschema.validate(example, schema)


def test_review_result_matches_contract():
    result = run_review_sync("测试", rounds=1, debater_llm=FakeLLM(), judge_llm=FakeLLM())
    payload = result.to_dict()
    assert payload["debate_id"]
    assert payload["mode"] == "review"
    schema = _load("debate_result.v1.json")
    jsonschema.validate(payload, schema)


def test_degraded_review_result_matches_contract():
    class InvalidLLM:
        provider = "fake"
        model = "fake"

        async def chat(self, system_prompt, user_prompt, max_tokens=None):
            return "not json"

    result = run_review_sync("测试", rounds=1, debater_llm=InvalidLLM(), judge_llm=InvalidLLM())
    payload = result.to_dict()
    assert payload["status"] == "completed"
    assert payload["meta"]["degraded"] is True
    jsonschema.validate(payload, _load("debate_result.v1.json"))
