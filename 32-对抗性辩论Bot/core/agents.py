"""agents.py — BullAgent / BearAgent 辩手

核心设计（借鉴 TradingAgents）：
- Prompt 锁立场：Bull 只支持 / Bear 只反对
- LLM 调用 → JSON 解析 → 失败重试 1 次 → FAIL-OPEN 兜底
- 上下文注入：transcript 对方上轮 + background + injected_views
"""
from __future__ import annotations

import json
import logging
import re
from typing import Protocol

from core.models import Argument, Turn, Verdict
from core.prompts import (
    BULL_SYSTEM_PROMPT, BEAR_SYSTEM_PROMPT, JUDGE_SYSTEM_PROMPT,
    build_user_prompt,
)

logger = logging.getLogger("debate.agents")


class LLMClient(Protocol):
    """LLM 客户端接口（duck-typed）。"""

    async def chat(self, system_prompt: str, user_prompt: str,
                   max_tokens: int = 600) -> str:
        """调用 LLM，返回文本响应。"""
        ...


def _extract_json(raw: str) -> dict | None:
    """从 LLM 输出中提取 JSON 对象。

    处理三种情况：
    1. 纯 JSON 字符串
    2. JSON 嵌在额外文本中
    3. 非 JSON 文本
    """
    raw = raw.strip()
    # 尝试直接解析
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        pass

    # 尝试提取 { ... } 片段
    match = re.search(r'\{[^{}]*\}', raw, re.DOTALL)
    if match:
        try:
            return json.loads(match.group())
        except json.JSONDecodeError:
            pass

    return None


def _parse_argument(raw: str) -> Argument | None:
    """解析 LLM 输出为 Argument，失败返回 None。"""
    data = _extract_json(raw)
    if data is None:
        return None

    try:
        return Argument(
            thesis=str(data["thesis"]),
            arguments=list(data.get("arguments", [])),
            quote=str(data.get("quote", "")),
            confidence=float(data.get("confidence", 0.0)),
            raw=raw,
        )
    except (KeyError, TypeError, ValueError) as e:
        logger.warning("Argument 解析失败: %s", e)
        return None


def _get_opponent_thesis(transcript: list[Turn], my_side: str) -> str | None:
    """从 transcript 中提取对方最后一轮的 thesis。

    Args:
        transcript: 辩论历史
        my_side: 'bull' 或 'bear'
    """
    opponent = "bear" if my_side == "bull" else "bull"
    for turn in reversed(transcript):
        if turn.speaker == opponent and isinstance(turn.content, Argument):
            return turn.content.thesis
    return None


class BaseAgent:
    """辩手基类：立场 prompt + LLM 调用 + JSON 解析 + 重试 + FAIL-OPEN。"""

    def __init__(self, llm_client: LLMClient, system_prompt: str,
                 side: str, max_tokens: int = 600):
        self.llm = llm_client
        self.system_prompt = system_prompt
        self.side = side  # 'bull' or 'bear'
        self.max_tokens = max_tokens

    async def _speak(self, topic: str, transcript: list[Turn],
                     background: str = "",
                     injected_views: list[str] | None = None) -> Argument:
        """核心逻辑：构建 prompt → LLM 调用 → JSON 解析 → 重试 → 兜底。"""
        opponent_last = _get_opponent_thesis(transcript, self.side)
        user_prompt = build_user_prompt(
            topic, opponent_last, background, injected_views,
        )

        # 第一次调用
        try:
            raw = await self.llm.chat(
                self.system_prompt, user_prompt, self.max_tokens,
            )
        except Exception as e:
            logger.warning("%s 第一次 LLM 调用异常: %s", self.side, e)
            return Argument.fallback()

        arg = _parse_argument(raw)
        if arg is not None:
            return arg

        # 重试 1 次（追加 "请严格输出 JSON" 提示）
        logger.info("%s JSON 解析失败，重试 1 次", self.side)
        retry_prompt = user_prompt + "\n\n请严格只输出 JSON，不要输出其他内容。"
        try:
            raw2 = await self.llm.chat(
                self.system_prompt, retry_prompt, self.max_tokens,
            )
        except Exception as e:
            logger.warning("%s 重试 LLM 调用异常: %s", self.side, e)
            return Argument.fallback()

        arg2 = _parse_argument(raw2)
        if arg2 is not None:
            return arg2

        # 两次都失败 → FAIL-OPEN 兜底
        logger.warning("%s 两次 JSON 解析均失败，返回兜底 Argument", self.side)
        return Argument.fallback()


class BullAgent(BaseAgent):
    """正方辩手：立场锁定为支持话题。"""

    def __init__(self, llm_client: LLMClient, max_tokens: int = 600):
        super().__init__(llm_client, BULL_SYSTEM_PROMPT, "bull", max_tokens)

    async def argue(self, topic: str, transcript: list[Turn],
                    background: str = "",
                    injected_views: list[str] | None = None) -> Argument:
        """正方发言。"""
        return await self._speak(topic, transcript, background, injected_views)


class BearAgent(BaseAgent):
    """反方辩手：立场锁定为反对话题。"""

    def __init__(self, llm_client: LLMClient, max_tokens: int = 600):
        super().__init__(llm_client, BEAR_SYSTEM_PROMPT, "bear", max_tokens)

    async def rebut(self, topic: str, transcript: list[Turn],
                    background: str = "",
                    injected_views: list[str] | None = None) -> Argument:
        """反方反驳。"""
        return await self._speak(topic, transcript, background, injected_views)


# ─── JudgeAgent ───────────────────────────────────────────────────

def _parse_verdict(raw: str) -> Verdict | None:
    """解析 LLM 输出为 Verdict，失败返回 None。"""
    data = _extract_json(raw)
    if data is None:
        return None

    try:
        winner = data.get("winner")
        # winner 只允许 'bull', 'bear' 或 None
        if winner not in ("bull", "bear", None):
            winner = None
        return Verdict(
            summary=str(data.get("summary", "")),
            winner=winner,
            key_insights=list(data.get("key_insights", [])),
            topic_angle=str(data.get("topic_angle", "")),
        )
    except (TypeError, ValueError) as e:
        logger.warning("Verdict 解析失败: %s", e)
        return None


def _build_judge_user_prompt(topic: str, transcript: list[Turn]) -> str:
    """构建裁判 user prompt：话题 + 双方论点。"""
    parts = [f"辩论话题：{topic}\n"]

    for turn in transcript:
        if isinstance(turn.content, Argument):
            side_name = "正方" if turn.speaker == "bull" else "反方"
            parts.append(
                f"【{side_name}·第{turn.round}轮】\n"
                f"论点：{turn.content.thesis}\n"
                f"论据：{'；'.join(turn.content.arguments)}\n"
                f"金句：{turn.content.quote}\n"
                f"置信度：{turn.content.confidence}\n"
            )

    parts.append("请综合以上辩论，输出你的裁决 JSON。")
    return "\n".join(parts)


class JudgeAgent:
    """综合裁判：综合双方论点 → Verdict。

    与辩手共用 LLM 调用 + JSON 解析 + 重试 + FAIL-OPEN 模式。
    """

    def __init__(self, llm_client: LLMClient, max_tokens: int = 800):
        self.llm = llm_client
        self.max_tokens = max_tokens

    async def synthesize(self, topic: str, transcript: list[Turn]) -> Verdict:
        """综合双方论点，输出裁决。"""
        user_prompt = _build_judge_user_prompt(topic, transcript)

        # 第一次调用
        try:
            raw = await self.llm.chat(
                JUDGE_SYSTEM_PROMPT, user_prompt, self.max_tokens,
            )
        except Exception as e:
            logger.warning("Judge 第一次 LLM 调用异常: %s", e)
            return Verdict(
                summary="（裁判因技术原因无法输出裁决）",
                winner=None, key_insights=[], topic_angle="",
            )

        verdict = _parse_verdict(raw)
        if verdict is not None:
            return verdict

        # 重试 1 次
        logger.info("Judge JSON 解析失败，重试 1 次")
        retry_prompt = user_prompt + "\n\n请严格只输出 JSON，不要输出其他内容。"
        try:
            raw2 = await self.llm.chat(
                JUDGE_SYSTEM_PROMPT, retry_prompt, self.max_tokens,
            )
        except Exception as e:
            logger.warning("Judge 重试 LLM 调用异常: %s", e)
            return Verdict(
                summary="（裁判因技术原因无法输出裁决）",
                winner=None, key_insights=[], topic_angle="",
            )

        verdict2 = _parse_verdict(raw2)
        if verdict2 is not None:
            return verdict2

        # FAIL-OPEN 兜底
        logger.warning("Judge 两次 JSON 解析均失败，返回兜底 Verdict")
        return Verdict(
            summary="（裁判因技术原因无法输出裁决）",
            winner=None, key_insights=[], topic_angle="",
        )
