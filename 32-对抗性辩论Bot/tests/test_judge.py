"""test_judge.py — JudgeAgent 综合裁判单元测试（TDD RED phase）

测试 SPEC 3.3：
- 综合双方论点 → Verdict(summary/winner/key_insights/topic_angle)
- LLM 调用 + JSON 解析 + 重试 + FAIL-OPEN
"""
from __future__ import annotations

import json

import pytest

from core.models import Argument, Turn, Verdict
from core.agents import JudgeAgent


class MockLLMClient:
    def __init__(self, responses):
        self._responses = list(responses)
        self._idx = 0
        self.calls: list[dict] = []

    async def chat(self, system_prompt: str, user_prompt: str,
                   max_tokens: int = 600) -> str:
        self.calls.append({"system": system_prompt, "user": user_prompt,
                            "max_tokens": max_tokens})
        if self._idx < len(self._responses):
            resp = self._responses[self._idx]
            self._idx += 1
            if isinstance(resp, Exception):
                raise resp
            return resp
        raise RuntimeError("no more mock responses")


def _make_transcript():
    """构建含 Bull/Bear 各一轮的 transcript。"""
    bull = Argument(thesis="BTC 是数字黄金", arguments=["稀缺性", "机构入场"],
                    quote="数字时代的诺克斯堡", confidence=0.85, raw="{}")
    bear = Argument(thesis="BTC 不是数字黄金", arguments=["波动率太高", "无内在价值"],
                    quote="泡沫终将破灭", confidence=0.72, raw="{}")
    return [
        Turn(speaker="bull", round=1, content=bull),
        Turn(speaker="bear", round=1, content=bear),
    ]


VALID_VERDICT_JSON = json.dumps({
    "summary": "正方以稀缺性和机构入场为主要论据，反方则以波动率和内在价值不足反驳。双方各有道理。",
    "winner": "bull",
    "key_insights": ["稀缺性是 BTC 价值的核心支撑", "波动率是阻碍其货币属性的关键因素"],
    "topic_angle": "从货币演进史看 BTC 的定位",
}, ensure_ascii=False)

INVALID_JSON = "这不是JSON格式的文本。"


class TestJudgeAgent:

    @pytest.mark.asyncio
    async def test_synthesize_valid_json(self):
        mock = MockLLMClient([VALID_VERDICT_JSON])
        judge = JudgeAgent(mock)
        verdict = await judge.synthesize("BTC 是数字黄金吗？", _make_transcript())

        assert isinstance(verdict, Verdict)
        assert verdict.winner == "bull"
        assert len(verdict.key_insights) == 2
        assert "货币演进" in verdict.topic_angle

    @pytest.mark.asyncio
    async def test_draw(self):
        """平局：winner=null。"""
        draw_json = json.dumps({
            "summary": "势均力敌",
            "winner": None,
            "key_insights": [],
            "topic_angle": "角度",
        }, ensure_ascii=False)
        mock = MockLLMClient([draw_json])
        judge = JudgeAgent(mock)
        verdict = await judge.synthesize("话题", _make_transcript())

        assert verdict.winner is None

    @pytest.mark.asyncio
    async def test_json_retry_success(self):
        mock = MockLLMClient([INVALID_JSON, VALID_VERDICT_JSON])
        judge = JudgeAgent(mock)
        verdict = await judge.synthesize("BTC 是数字黄金吗？", _make_transcript())

        assert isinstance(verdict, Verdict)
        assert verdict.winner == "bull"
        assert mock._idx == 2

    @pytest.mark.asyncio
    async def test_json_retry_fail_fallback(self):
        mock = MockLLMClient([INVALID_JSON, INVALID_JSON])
        judge = JudgeAgent(mock)
        verdict = await judge.synthesize("BTC 是数字黄金吗？", _make_transcript())

        assert isinstance(verdict, Verdict)
        assert verdict.winner is None
        assert verdict.summary != ""  # 有兜底文本

    @pytest.mark.asyncio
    async def test_llm_exception_fallback(self):
        mock = MockLLMClient([RuntimeError("网络错误")])
        judge = JudgeAgent(mock)
        verdict = await judge.synthesize("BTC 是数字黄金吗？", _make_transcript())

        assert isinstance(verdict, Verdict)
        assert verdict.winner is None
        assert mock._idx == 1

    @pytest.mark.asyncio
    async def test_prompt_contains_neutral(self):
        """Judge prompt 应包含中立综合角色定位。"""
        mock = MockLLMClient([VALID_VERDICT_JSON])
        judge = JudgeAgent(mock)
        await judge.synthesize("话题", _make_transcript())

        sys_prompt = mock.calls[0]["system"]
        assert "裁判" in sys_prompt or "综合" in sys_prompt or "中立" in sys_prompt

    @pytest.mark.asyncio
    async def test_transcript_in_prompt(self):
        """transcript 中双方论点应注入 prompt。"""
        mock = MockLLMClient([VALID_VERDICT_JSON])
        judge = JudgeAgent(mock)
        await judge.synthesize("BTC 是数字黄金吗？", _make_transcript())

        user_prompt = mock.calls[0]["user"]
        assert "数字黄金" in user_prompt

    @pytest.mark.asyncio
    async def test_winner_values(self):
        """winner 只能是 'bull', 'bear' 或 None。"""
        for winner_val in ["bull", "bear", None]:
            wj = json.dumps({
                "summary": "s", "winner": winner_val,
                "key_insights": [], "topic_angle": "a",
            }, ensure_ascii=False)
            mock = MockLLMClient([wj])
            judge = JudgeAgent(mock)
            v = await judge.synthesize("t", _make_transcript())
            assert v.winner == winner_val
