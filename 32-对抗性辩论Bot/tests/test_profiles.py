"""profile 层测试：marketing / technical / signal。"""
from __future__ import annotations

import json

import pytest

from core.agents import BullAgent, BearAgent, JudgeAgent
from core.models import Turn
from core.profiles import PROFILE_NAMES, get_profile
from core.review_runner import run_review_sync


class FakeLLM:
    provider = "fake"
    model = "fake"

    def __init__(self, judge_json: str):
        self.judge_json = judge_json
        self.calls: list[dict] = []

    async def chat(self, system_prompt, user_prompt, max_tokens=None):
        self.calls.append({"system": system_prompt, "user": user_prompt})
        if "裁判" in system_prompt:
            return self.judge_json
        if "空头" in system_prompt or "反方" in system_prompt:
            return json.dumps({
                "thesis": "反方判断", "arguments": ["反论据"],
                "evidence": ["file.py:10"], "quote": "反证据",
                "confidence": 0.4,
            }, ensure_ascii=False)
        return json.dumps({
            "thesis": "正方判断", "arguments": ["正论据"],
            "evidence": ["doc §1"], "quote": "正证据",
            "confidence": 0.8,
        }, ensure_ascii=False)


def test_profile_registry():
    assert PROFILE_NAMES == ("marketing", "technical", "signal")
    assert get_profile(None).name == "marketing"
    assert get_profile("technical").technical is True
    assert get_profile("signal").signal is True
    with pytest.raises(ValueError):
        get_profile("unknown")


@pytest.mark.asyncio
async def test_agent_uses_profile_prompts():
    mock = FakeLLM("{}")
    technical_bull = BullAgent(mock, profile="technical")
    signal_bear = BearAgent(mock, profile="signal")

    await technical_bull.argue("命题", [])
    await signal_bear.rebut("命题", [])

    assert "技术评审员" in mock.calls[0]["system"]
    assert "空头信号评审员" in mock.calls[1]["system"]


@pytest.mark.asyncio
async def test_profile_cross_exam_prompts_are_domain_specific():
    mock = FakeLLM("{}")
    technical = BullAgent(mock, profile="technical")
    signal = BearAgent(mock, profile="signal")

    await technical.cross_examine("命题", [])
    await signal.answer_cross("命题", ["Q1"], [])

    assert "证据" in mock.calls[0]["system"]
    assert "信号字段" in mock.calls[1]["system"]


@pytest.mark.asyncio
async def test_argument_evidence_parsed():
    mock = FakeLLM("{}")
    agent = BullAgent(mock, profile="technical")
    arg = await agent.argue("命题", [])
    assert arg.evidence == ["doc §1"]


@pytest.mark.asyncio
async def test_technical_verdict_fields():
    verdict_json = json.dumps({
        "summary": "可行但有风险", "winner": "bear",
        "key_insights": ["接口未闭合"], "topic_angle": "",
        "feasibility": 0.55, "risks": ["契约漂移"],
        "evidence_gaps": ["缺少运行态验证"],
        "recommendation": "先补契约测试",
    }, ensure_ascii=False)
    judge = JudgeAgent(FakeLLM(verdict_json), profile="technical")
    verdict = await judge.synthesize("命题", [])
    assert verdict.feasibility == 0.55
    assert verdict.risks == ["契约漂移"]
    assert verdict.evidence_gaps == ["缺少运行态验证"]
    assert verdict.recommendation == "先补契约测试"


@pytest.mark.asyncio
async def test_signal_verdict_fields():
    verdict_json = json.dumps({
        "summary": "偏多但风险偏高", "winner": "bull",
        "key_insights": ["信号一致"], "topic_angle": "",
        "signal": {
            "direction": "long", "confidence": 0.72,
            "risk_flags": ["高波动"], "evidence": ["signal:1"],
            "counter_evidence": ["资金流背离"],
        },
    }, ensure_ascii=False)
    judge = JudgeAgent(FakeLLM(verdict_json), profile="signal")
    verdict = await judge.synthesize("命题", [])
    assert verdict.signal["direction"] == "long"
    assert verdict.signal["risk_flags"] == ["高波动"]


def test_review_runner_technical_profile():
    verdict_json = json.dumps({
        "summary": "可行", "winner": "bull", "key_insights": ["ok"],
        "topic_angle": "", "feasibility": 0.8, "risks": [],
        "evidence_gaps": [], "recommendation": "继续",
    }, ensure_ascii=False)
    llm = FakeLLM(verdict_json)
    result = run_review_sync(
        "命题", rounds=1, debater_llm=llm, judge_llm=llm,
        profile="technical", adjudication=False,
    )
    payload = result.to_dict()
    assert payload["meta"]["profile"] == "technical"
    assert payload["verdict"]["feasibility"] == 0.8


def test_review_runner_signal_profile():
    verdict_json = json.dumps({
        "summary": "偏多", "winner": "bull", "key_insights": ["ok"],
        "topic_angle": "", "signal": {"direction": "long", "confidence": 0.7},
    }, ensure_ascii=False)
    llm = FakeLLM(verdict_json)
    result = run_review_sync(
        "BTC 信号", rounds=1, debater_llm=llm, judge_llm=llm,
        profile="signal", adjudication=False,
    )
    payload = result.to_dict()
    assert payload["meta"]["profile"] == "signal"
    assert payload["verdict"]["signal"]["direction"] == "long"