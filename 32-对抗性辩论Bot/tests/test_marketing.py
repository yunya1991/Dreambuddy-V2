"""test_marketing.py — MarketingExtractor 单元测试（TDD RED phase）

测试 SPEC 3.4：
- 金句摘录（从双方 quote 字段）
- 话题标签（从 topic 提取）
- 精华段落（Judge 综合 + 双方最强论点；无 Judge 时 fallback 拼接）
- 短文案（LLM 生成，失败时 fallback）
- 辩论标题（LLM 生成，失败时 fallback）
"""
from __future__ import annotations

import json

import pytest

from core.models import Argument, Turn, Verdict, MarketingMaterial
from core.marketing import MarketingExtractor


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
    bull = Argument(
        thesis="BTC 是数字黄金", arguments=["稀缺性 2100万枚", "机构持续买入"],
        quote="数字时代的诺克斯堡", confidence=0.85, raw="{}",
    )
    bear = Argument(
        thesis="BTC 不是数字黄金", arguments=["波动率太高", "无内在价值"],
        quote="泡沫终将破灭", confidence=0.72, raw="{}",
    )
    return [
        Turn(speaker="bull", round=1, content=bull),
        Turn(speaker="bear", round=1, content=bear),
    ]


def _make_verdict():
    return Verdict(
        summary="正方以稀缺性论证为主，反方以波动率反驳。",
        winner="bull",
        key_insights=["稀缺性是核心支撑", "波动率是关键障碍"],
        topic_angle="从货币演进史看数字资产定位",
    )


VALID_SHORT_COPY_JSON = json.dumps({
    "copies": [
        "BTC 是数字黄金？两位 AI 辩手给出截然不同的答案",
        "稀缺性 vs 泡沫：一场关于 BTC 本质的辩论",
        "2100万枚的稀缺性能否支撑 BTC 的数字黄金叙事？",
    ],
    "title": "BTC 数字黄金之争：稀缺性与泡沫的终极对决",
}, ensure_ascii=False)


class TestMarketingExtractor:

    @pytest.mark.asyncio
    async def test_extract_quotes(self):
        """金句从双方 quote 字段提取。"""
        extractor = MarketingExtractor(MockLLMClient())
        m = await extractor.extract("BTC 是数字黄金吗？", _make_transcript(),
                                     _make_verdict())

        assert "数字时代的诺克斯堡" in m.quotes
        assert "泡沫终将破灭" in m.quotes

    @pytest.mark.asyncio
    async def test_extract_hashtags(self):
        """话题标签从 topic 提取。"""
        extractor = MarketingExtractor(MockLLMClient())
        m = await extractor.extract("BTC 是数字黄金吗？", _make_transcript(),
                                     _make_verdict())

        assert len(m.hashtags) >= 2
        assert any("BTC" in tag or "比特币" in tag for tag in m.hashtags)

    @pytest.mark.asyncio
    async def test_highlight_with_verdict(self):
        """有 Verdict 时，精华段落包含 Judge 的总结。"""
        extractor = MarketingExtractor(MockLLMClient())
        m = await extractor.extract("BTC 是数字黄金吗？", _make_transcript(),
                                     _make_verdict())

        assert "稀缺性" in m.highlight_paragraph or "正方" in m.highlight_paragraph

    @pytest.mark.asyncio
    async def test_highlight_without_verdict(self):
        """无 Verdict 时，fallback 为双方最强论点拼接。"""
        extractor = MarketingExtractor(MockLLMClient())
        m = await extractor.extract("BTC 是数字黄金吗？", _make_transcript(),
                                     verdict=None)

        assert m.highlight_paragraph != ""
        assert "数字黄金" in m.highlight_paragraph

    @pytest.mark.asyncio
    async def test_short_copy_llm_success(self):
        """LLM 成功生成短文案和标题。"""
        mock = MockLLMClient([VALID_SHORT_COPY_JSON])
        extractor = MarketingExtractor(mock)
        m = await extractor.extract("BTC 是数字黄金吗？", _make_transcript(),
                                     _make_verdict())

        assert len(m.short_copy) == 3
        assert m.debate_title == "BTC 数字黄金之争：稀缺性与泡沫的终极对决"

    @pytest.mark.asyncio
    async def test_short_copy_llm_fail_fallback(self):
        """LLM 失败时短文案/标题走 fallback。"""
        mock = MockLLMClient([RuntimeError("网络错误")])
        extractor = MarketingExtractor(mock)
        m = await extractor.extract("BTC 是数字黄金吗？", _make_transcript(),
                                     _make_verdict())

        # fallback 不为空
        assert len(m.short_copy) >= 1
        assert m.debate_title != ""

    @pytest.mark.asyncio
    async def test_short_copy_invalid_json_fallback(self):
        """LLM 返回非法 JSON 时 fallback。"""
        mock = MockLLMClient(["这不是JSON"])
        extractor = MarketingExtractor(mock)
        m = await extractor.extract("BTC 是数字黄金吗？", _make_transcript(),
                                     _make_verdict())

        assert len(m.short_copy) >= 1
        assert m.debate_title != ""

    @pytest.mark.asyncio
    async def test_full_extract(self):
        """完整提取：所有字段都有值。"""
        mock = MockLLMClient([VALID_SHORT_COPY_JSON])
        extractor = MarketingExtractor(mock)
        m = await extractor.extract("BTC 是数字黄金吗？", _make_transcript(),
                                     _make_verdict())

        assert isinstance(m, MarketingMaterial)
        assert len(m.quotes) >= 2
        assert len(m.hashtags) >= 2
        assert m.highlight_paragraph != ""
        assert len(m.short_copy) >= 1
        assert m.debate_title != ""

    @pytest.mark.asyncio
    async def test_empty_transcript(self):
        """空 transcript 不崩溃，返回空/默认值。"""
        extractor = MarketingExtractor(MockLLMClient())
        m = await extractor.extract("空话题", [], None)

        assert isinstance(m, MarketingMaterial)
        assert m.quotes == []
