"""test_quality.py — QualityEvaluator 单元测试（TDD RED phase）

SPEC 9.2-9.4 五维评估：
- 金句密度/观点多样性（规则分 40%）
- 冲突强度/话题升华度/文案可转化度（LLM 分 60%）
- 综合分 = rule×0.4 + llm×0.6 → S/A/B/C 分级
"""
from __future__ import annotations

import json

import pytest

from core.models import Argument, Turn, MarketingMaterial
from core.quality import QualityEvaluator


class MockLLMClient:
    def __init__(self, responses=None):
        self._responses = list(responses) if responses else []
        self._idx = 0
        self.calls: list[dict] = []

    async def chat(self, system_prompt: str, user_prompt: str,
                   max_tokens: int = 600) -> str:
        self.calls.append({"system": system_prompt, "user": user_prompt})
        if self._idx < len(self._responses):
            resp = self._responses[self._idx]
            self._idx += 1
            if isinstance(resp, Exception):
                raise resp
            return resp
        raise RuntimeError("no more mock responses")


def _make_transcript():
    bull = Argument(thesis="BTC 是数字黄金", arguments=["稀缺性", "机构入场", "抗通胀"],
                    quote="数字时代的诺克斯堡", confidence=0.85, raw="{}")
    bear = Argument(thesis="BTC 不是数字黄金", arguments=["波动率太高", "无内在价值", "监管风险"],
                    quote="泡沫终将破灭", confidence=0.72, raw="{}")
    return [
        Turn(speaker="bull", round=1, content=bull),
        Turn(speaker="bear", round=1, content=bear),
    ]


def _make_material():
    return MarketingMaterial(
        quotes=["数字时代的诺克斯堡", "泡沫终将破灭"],
        hashtags=["#BTC", "#数字黄金"],
        highlight_paragraph="正方认为 BTC 是数字黄金",
        short_copy=["BTC 是数字黄金？", "稀缺性 vs 泡沫"],
        debate_title="BTC 数字黄金之争",
    )


VALID_QUALITY_JSON = json.dumps({
    "conflict_intensity": 8.0,
    "topic_elevation": 7.5,
    "copy_convertibility": 8.5,
    "highlights": ["金句密度高", "双方立场坚定"],
    "suggestions": [],
}, ensure_ascii=False)

LOW_QUALITY_JSON = json.dumps({
    "conflict_intensity": 3.0,
    "topic_elevation": 2.5,
    "copy_convertibility": 3.0,
    "highlights": [],
    "suggestions": ["加强立场锁定", "提升金句质量"],
}, ensure_ascii=False)


class TestQualityEvaluator:

    @pytest.mark.asyncio
    async def test_rule_dimensions(self):
        """规则维度：金句密度 + 观点多样性。"""
        mock = MockLLMClient([VALID_QUALITY_JSON])
        evaluator = QualityEvaluator(mock)
        score = await evaluator.evaluate(
            "BTC 是数字黄金吗？", _make_transcript(), _make_material(),
        )

        assert "金句密度" in score.dimensions
        assert "观点多样性" in score.dimensions
        assert score.rule_score > 0

    @pytest.mark.asyncio
    async def test_llm_dimensions(self):
        """LLM 维度：冲突强度 + 话题升华度 + 文案可转化度。"""
        mock = MockLLMClient([VALID_QUALITY_JSON])
        evaluator = QualityEvaluator(mock)
        score = await evaluator.evaluate(
            "BTC 是数字黄金吗？", _make_transcript(), _make_material(),
        )

        assert score.dimensions["冲突强度"] == 8.0
        assert score.dimensions["话题升华度"] == 7.5
        assert score.dimensions["文案可转化度"] == 8.5

    @pytest.mark.asyncio
    async def test_overall_score_formula(self):
        """综合分 = rule×0.4 + llm×0.6。"""
        mock = MockLLMClient([VALID_QUALITY_JSON])
        evaluator = QualityEvaluator(mock)
        score = await evaluator.evaluate(
            "BTC 是数字黄金吗？", _make_transcript(), _make_material(),
        )

        expected_overall = score.rule_score * 0.4 + score.llm_score * 0.6
        assert abs(score.overall - expected_overall) < 0.01

    @pytest.mark.asyncio
    async def test_grade_s(self):
        """高分 → S 级。"""
        mock = MockLLMClient([VALID_QUALITY_JSON])
        evaluator = QualityEvaluator(mock)
        score = await evaluator.evaluate(
            "BTC 是数字黄金吗？", _make_transcript(), _make_material(),
        )

        assert score.grade in ("S", "A")  # 高分场

    @pytest.mark.asyncio
    async def test_grade_c(self):
        """低分 → C 级 + 有 suggestions。"""
        mock = MockLLMClient([LOW_QUALITY_JSON])
        evaluator = QualityEvaluator(mock)
        score = await evaluator.evaluate(
            "BTC 是数字黄金吗？", _make_transcript(), _make_material(),
        )

        assert score.grade in ("C", "B")
        assert len(score.suggestions) >= 1

    @pytest.mark.asyncio
    async def test_llm_fail_fallback(self):
        """LLM 失败 → fallback 评分（不崩溃）。"""
        mock = MockLLMClient([RuntimeError("网络错误")])
        evaluator = QualityEvaluator(mock)
        score = await evaluator.evaluate(
            "BTC 是数字黄金吗？", _make_transcript(), _make_material(),
        )

        assert score.llm_score >= 0
        assert score.grade in ("S", "A", "B", "C")

    @pytest.mark.asyncio
    async def test_llm_invalid_json_fallback(self):
        mock = MockLLMClient(["不是JSON"])
        evaluator = QualityEvaluator(mock)
        score = await evaluator.evaluate(
            "BTC 是数字黄金吗？", _make_transcript(), _make_material(),
        )

        assert score.llm_score >= 0
        assert score.grade in ("S", "A", "B", "C")

    @pytest.mark.asyncio
    async def test_highlights_populated(self):
        """高质量场有 highlights。"""
        mock = MockLLMClient([VALID_QUALITY_JSON])
        evaluator = QualityEvaluator(mock)
        score = await evaluator.evaluate(
            "BTC 是数字黄金吗？", _make_transcript(), _make_material(),
        )

        assert len(score.highlights) >= 1

    @pytest.mark.asyncio
    async def test_empty_transcript(self):
        """空 transcript 不崩溃。"""
        mock = MockLLMClient([VALID_QUALITY_JSON])
        evaluator = QualityEvaluator(mock)
        material = MarketingMaterial(
            quotes=[], hashtags=[], highlight_paragraph="",
            short_copy=[], debate_title="",
        )
        score = await evaluator.evaluate("空话题", [], material)

        assert score.overall >= 0
        assert score.grade in ("S", "A", "B", "C")
