"""P1 DSH fast/deep backend tests (fake engine/adjudicator, no LLM)."""

import json
from pathlib import Path

import jsonschema
from core.dsh_backend import run_dsh_debate_sync

CONTRACTS = Path(__file__).resolve().parents[1] / "contracts"


class FakeEngine:
    async def run_fast(self, topic):
        return {
            "bull_thesis": "bull-fast",
            "bull_confidence": 0.8,
            "bear_thesis": "bear-fast",
            "bear_confidence": 0.5,
        }

    async def run_deep(self, topic, background=""):
        return {
            "topic": topic,
            "transcript": [
                {
                    "speaker": "bull",
                    "round": 1,
                    "content": {"thesis": "bull-deep", "arguments": ["a"], "confidence": 0.7},
                },
                {
                    "speaker": "bear",
                    "round": 1,
                    "content": {"thesis": "bear-deep", "arguments": ["b"], "confidence": 0.6},
                },
            ],
            "verdict": {
                "summary": "deep",
                "winner": "bull",
                "key_insights": ["k"],
                "topic_angle": "t",
            },
        }


class FakeAdjudication:
    def to_dict(self):
        return {"winner": "bull", "bull_total": 24, "bear_total": 18, "rfd": "rfd"}


class FakeAdjudicator:
    def adjudicate(self, topic, transcript, verdict):
        return FakeAdjudication()


def _schema():
    return json.loads((CONTRACTS / "debate_result.v1.json").read_text(encoding="utf-8"))


def test_fast_mode_contract():
    result = run_dsh_debate_sync(
        "fast",
        "topic",
        engine=FakeEngine(),
        adjudicator=FakeAdjudicator(),
    )
    assert result["mode"] == "fast"
    assert result["adjudication"] is None
    assert result["verdict"]["winner"] == "bull"
    jsonschema.validate(result, _schema())


def test_deep_mode_has_adjudication():
    result = run_dsh_debate_sync(
        "deep",
        "topic",
        engine=FakeEngine(),
        adjudicator=FakeAdjudicator(),
    )
    assert result["mode"] == "deep"
    assert result["adjudication"]["winner"] == "bull"
    assert len(result["transcript"]) == 2
    jsonschema.validate(result, _schema())


def test_invalid_mode_raises():
    try:
        run_dsh_debate_sync("review", "topic", engine=FakeEngine())
    except ValueError:
        return
    raise AssertionError("expected ValueError")


def test_signal_profile_routes_to_32_review(monkeypatch):
    from core import review_runner

    captured = {}

    class FakeResult:
        def to_dict(self):
            return {
                "status": "completed",
                "transcript": [],
                "verdict": {"signal": {"direction": "long"}},
                "meta": {},
            }

    def fake_run(topic, **kwargs):
        captured.update(kwargs)
        return FakeResult()

    monkeypatch.setattr(review_runner, "run_review_sync", fake_run)
    result = run_dsh_debate_sync("fast", "BTC 信号", profile="signal")

    assert captured["profile"] == "signal"
    assert result["mode"] == "fast"
    assert result["meta"]["backend"] == "32-signal"
    assert result["meta"]["profile"] == "signal"


def test_deep_mode_normalizes_unknown_winner():
    class DrawEngine(FakeEngine):
        async def run_deep(self, topic, background=""):
            data = await super().run_deep(topic, background)
            data["verdict"] = dict(data["verdict"], winner="draw")
            return data

    result = run_dsh_debate_sync(
        "deep",
        "topic",
        engine=DrawEngine(),
        adjudicator=FakeAdjudicator(),
    )
    assert result["verdict"]["winner"] is None
    jsonschema.validate(result, _schema())
