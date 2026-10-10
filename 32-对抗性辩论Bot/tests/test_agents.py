"""test_agents.py — 辩手 Agent 单元测试（TDD RED phase）

测试 SPEC 3.2 的核心设计：
- Prompt 锁立场（Bull 只支持 / Bear 只反对）
- LLM 调用 + JSON 解析
- JSON 解析失败重试 1 次
- FAIL-OPEN 兜底 Argument
- 上下文注入（transcript / background / injected_views）
"""
from __future__ import annotations

import json
from typing import Sequence

import pytest

from core.models import Argument, Turn
from core.agents import BullAgent, BearAgent, LLMClient
from core.prompts import BULL_SYSTEM_PROMPT, BEAR_SYSTEM_PROMPT


# ─── Mock LLM Client ──────────────────────────────────────────────

class MockLLMClient:
    """可控的 LLM mock：按调用顺序返回预设响应。"""

    def __init__(self, responses: Sequence[str]):
        self._responses = list(responses)
        self._call_idx = 0
        self.calls: list[dict] = []  # 记录每次调用的参数

    async def chat(self, system_prompt: str, user_prompt: str,
                   max_tokens: int = 600) -> str:
        self.calls.append({
            "system": system_prompt,
            "user": user_prompt,
            "max_tokens": max_tokens,
        })
        if self._call_idx < len(self._responses):
            resp = self._responses[self._call_idx]
            self._call_idx += 1
            if isinstance(resp, Exception):
                raise resp
            return resp
        raise RuntimeError("MockLLMClient: no more responses")


# ─── 辅助 ─────────────────────────────────────────────────────────

def make_bull_arg() -> Argument:
    return Argument(thesis="BTC 是数字黄金", arguments=["稀缺性", "机构入场"],
                    quote="数字时代的诺克斯堡", confidence=0.85, raw="{}")


def make_bear_arg() -> Argument:
    return Argument(thesis="BTC 不是数字黄金", arguments=["波动率太高", "无内在价值"],
                    quote="投机泡沫终将破灭", confidence=0.75, raw="{}")


VALID_BULL_JSON = json.dumps({
    "thesis": "BTC 是真正的数字黄金",
    "arguments": ["总量恒定 2100 万枚，具备稀缺性", "机构持续增持，需求稳定增长"],
    "quote": "数字时代的诺克斯堡",
    "confidence": 0.85,
}, ensure_ascii=False)

VALID_BEAR_JSON = json.dumps({
    "thesis": "BTC 不是数字黄金",
    "arguments": ["年化波动率超 60%，远超黄金", "无内在价值，全靠共识支撑"],
    "quote": "共识一旦崩塌，泡沫终将破灭",
    "confidence": 0.72,
}, ensure_ascii=False)

INVALID_JSON = "这不是JSON，只是一段普通文本。"

JSON_WITH_EXTRA = '''
好的，我来分析一下。
{"thesis": "BTC 是数字黄金", "arguments": ["稀缺性"], "quote": "金句", "confidence": 0.8}
以上是我的论点。
'''


# ─── BullAgent 测试 ───────────────────────────────────────────────

class TestBullAgent:
    """正方辩手。"""

    @pytest.mark.asyncio
    async def test_argue_valid_json(self):
        """LLM 返回合法 JSON → 正常解析为 Argument。"""
        mock = MockLLMClient([VALID_BULL_JSON])
        agent = BullAgent(mock)
        arg = await agent.argue("BTC 是数字黄金吗？", [])

        assert isinstance(arg, Argument)
        assert arg.thesis == "BTC 是真正的数字黄金"
        assert len(arg.arguments) == 2
        assert arg.quote == "数字时代的诺克斯堡"
        assert arg.confidence == 0.85
        assert mock._call_idx == 1  # 只调用 1 次

    @pytest.mark.asyncio
    async def test_prompt_locks_bull_stance(self):
        """Bull 的 system prompt 必须包含立场锁定关键词。"""
        mock = MockLLMClient([VALID_BULL_JSON])
        agent = BullAgent(mock)
        await agent.argue("BTC 是数字黄金吗？", [])

        sys_prompt = mock.calls[0]["system"]
        assert "正方" in sys_prompt or "支持" in sys_prompt

    @pytest.mark.asyncio
    async def test_json_retry_once(self):
        """JSON 解析失败 → 重试 1 次 → 第二次成功。"""
        mock = MockLLMClient([INVALID_JSON, VALID_BULL_JSON])
        agent = BullAgent(mock)
        arg = await agent.argue("BTC 是数字黄金吗？", [])

        assert isinstance(arg, Argument)
        assert arg.thesis == "BTC 是真正的数字黄金"
        assert mock._call_idx == 2  # 调用了 2 次

    @pytest.mark.asyncio
    async def test_json_retry_fail_fallback(self):
        """JSON 两次都失败 → 返回 fallback Argument。"""
        mock = MockLLMClient([INVALID_JSON, INVALID_JSON])
        agent = BullAgent(mock)
        arg = await agent.argue("BTC 是数字黄金吗？", [])

        assert isinstance(arg, Argument)
        assert arg.confidence == 0.0
        assert arg.arguments == []
        assert mock._call_idx == 2

    @pytest.mark.asyncio
    async def test_llm_exception_fallback(self):
        """LLM 直接抛异常 → fallback（不重试）。"""
        mock = MockLLMClient([RuntimeError("网络错误")])
        agent = BullAgent(mock)
        arg = await agent.argue("BTC 是数字黄金吗？", [])

        assert isinstance(arg, Argument)
        assert arg.confidence == 0.0
        assert mock._call_idx == 1

    @pytest.mark.asyncio
    async def test_transcript_context_injected(self):
        """transcript 中 Bear 上一轮的论点应注入 user prompt。"""
        bear_turn = Turn(speaker="bear", round=1, content=make_bear_arg())
        mock = MockLLMClient([VALID_BULL_JSON])
        agent = BullAgent(mock)
        await agent.argue("BTC 是数字黄金吗？", [bear_turn])

        user_prompt = mock.calls[0]["user"]
        assert "BTC 不是数字黄金" in user_prompt  # Bear 的 thesis 出现在 prompt

    @pytest.mark.asyncio
    async def test_background_injected(self):
        """background 材料应注入 user prompt。"""
        mock = MockLLMClient([VALID_BULL_JSON])
        agent = BullAgent(mock)
        await agent.argue("BTC 是数字黄金吗？", [], background="近期 BTC ETF 获批")

        user_prompt = mock.calls[0]["user"]
        assert "ETF" in user_prompt

    @pytest.mark.asyncio
    async def test_injected_views_in_prompt(self):
        """群主注入的观点应出现在 user prompt。"""
        mock = MockLLMClient([VALID_BULL_JSON])
        agent = BullAgent(mock)
        await agent.argue("BTC 是数字黄金吗？", [],
                          injected_views=["请讨论 ETF 的影响"])

        user_prompt = mock.calls[0]["user"]
        assert "ETF" in user_prompt

    @pytest.mark.asyncio
    async def test_json_with_extra_text(self):
        """LLM 输出包含 JSON + 额外文本 → 能提取 JSON 部分。"""
        mock = MockLLMClient([JSON_WITH_EXTRA])
        agent = BullAgent(mock)
        arg = await agent.argue("BTC 是数字黄金吗？", [])

        assert isinstance(arg, Argument)
        assert arg.thesis == "BTC 是数字黄金"

    @pytest.mark.asyncio
    async def test_max_tokens_limit(self):
        """辩手 max_tokens 应限制为 600。"""
        mock = MockLLMClient([VALID_BULL_JSON])
        agent = BullAgent(mock)
        await agent.argue("BTC 是数字黄金吗？", [])

        assert mock.calls[0]["max_tokens"] == 600


# ─── BearAgent 测试 ───────────────────────────────────────────────

class TestBearAgent:
    """反方辩手。"""

    @pytest.mark.asyncio
    async def test_rebut_valid_json(self):
        """LLM 返回合法 JSON → 正常解析为 Argument。"""
        mock = MockLLMClient([VALID_BEAR_JSON])
        agent = BearAgent(mock)
        arg = await agent.rebut("BTC 是数字黄金吗？", [])

        assert isinstance(arg, Argument)
        assert arg.thesis == "BTC 不是数字黄金"
        assert len(arg.arguments) == 2
        assert arg.confidence == 0.72

    @pytest.mark.asyncio
    async def test_prompt_locks_bear_stance(self):
        """Bear 的 system prompt 必须包含反对立场。"""
        mock = MockLLMClient([VALID_BEAR_JSON])
        agent = BearAgent(mock)
        await agent.rebut("BTC 是数字黄金吗？", [])

        sys_prompt = mock.calls[0]["system"]
        assert "反方" in sys_prompt or "反对" in sys_prompt

    @pytest.mark.asyncio
    async def test_transcript_context_injected(self):
        """transcript 中 Bull 上一轮的论点应注入 user prompt。"""
        bull_turn = Turn(speaker="bull", round=1, content=make_bull_arg())
        mock = MockLLMClient([VALID_BEAR_JSON])
        agent = BearAgent(mock)
        await agent.rebut("BTC 是数字黄金吗？", [bull_turn])

        user_prompt = mock.calls[0]["user"]
        assert "数字黄金" in user_prompt  # Bull 的 thesis 出现在 prompt

    @pytest.mark.asyncio
    async def test_json_retry_fail_fallback(self):
        """两次 JSON 失败 → fallback。"""
        mock = MockLLMClient([INVALID_JSON, INVALID_JSON])
        agent = BearAgent(mock)
        arg = await agent.rebut("BTC 是数字黄金吗？", [])

        assert arg.confidence == 0.0
        assert mock._call_idx == 2

    @pytest.mark.asyncio
    async def test_llm_exception_fallback(self):
        mock = MockLLMClient([RuntimeError("超时")])
        agent = BearAgent(mock)
        arg = await agent.rebut("BTC 是数字黄金吗？", [])

        assert arg.confidence == 0.0
        assert mock._call_idx == 1


# ─── Prompt 模板测试 ──────────────────────────────────────────────

class TestPrompts:
    """立场 prompt 模板。"""

    def test_bull_prompt_contains_stance_lock(self):
        """Bull prompt 必须包含立场锁关键词。"""
        assert "支持" in BULL_SYSTEM_PROMPT
        assert "禁止" in BULL_SYSTEM_PROMPT or "不得" in BULL_SYSTEM_PROMPT

    def test_bear_prompt_contains_stance_lock(self):
        """Bear prompt 必须包含反对立场锁。"""
        assert "反对" in BEAR_SYSTEM_PROMPT
        assert "禁止" in BEAR_SYSTEM_PROMPT or "不得" in BEAR_SYSTEM_PROMPT

    def test_bull_prompt_has_json_schema(self):
        """Bull prompt 包含 JSON 输出格式约束。"""
        assert "thesis" in BULL_SYSTEM_PROMPT
        assert "arguments" in BULL_SYSTEM_PROMPT
        assert "quote" in BULL_SYSTEM_PROMPT
        assert "confidence" in BULL_SYSTEM_PROMPT

    def test_bear_prompt_has_json_schema(self):
        """Bear prompt 包含 JSON 输出格式约束。"""
        assert "thesis" in BEAR_SYSTEM_PROMPT
        assert "arguments" in BEAR_SYSTEM_PROMPT
        assert "quote" in BEAR_SYSTEM_PROMPT
        assert "confidence" in BEAR_SYSTEM_PROMPT
