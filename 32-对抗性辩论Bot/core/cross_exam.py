"""cross_exam.py — 交叉质询阶段（v2.0-rc3 §4.2）。

流程（每个方向 2 次 LLM 调用）：
  Bear 质询 Bull → Bull 逐条回答
  Bull 质询 Bear → Bear 逐条回答

设计边界：
- 可选阶段，由调用方 `cross_examination=True` 开启；默认不改变现有辩论路径；
- 任一方向的质询生成失败 → 跳过该方向（FAIL-OPEN），不阻塞裁判/营销；
- 生成的 `CrossExamination` Turn 写入 transcript，供后续辩手、裁判与营销提取复用。
"""
from __future__ import annotations

import logging
from typing import Awaitable, Callable, Protocol

from core.models import CrossExamination, Turn

logger = logging.getLogger("debate.cross_exam")


class CrossExamAgent(Protocol):
    side: str

    async def cross_examine(
        self, topic: str, transcript: list[Turn], background: str = "",
        injected_views: list[str] | None = None,
    ) -> list[str]: ...

    async def answer_cross(
        self, topic: str, questions: list[str], transcript: list[Turn],
        background: str = "", injected_views: list[str] | None = None,
    ) -> list[str]: ...


async def run_cross_examination(
    bull_agent: CrossExamAgent,
    bear_agent: CrossExamAgent,
    topic: str,
    transcript: list[Turn],
    background: str = "",
    injected_views: list[str] | None = None,
    round_num: int = 1,
    on_turn: Callable[[Turn], Awaitable[None]] | None = None,
) -> list[Turn]:
    """执行双向交叉质询，返回新增的 Turn 列表。

    Turn.speaker 记为质询方（bull/bear），content 为 CrossExamination。
    """
    turns: list[Turn] = []
    directions: list[tuple[str, str, CrossExamAgent, CrossExamAgent]] = [
        ("bear", "bull", bear_agent, bull_agent),
        ("bull", "bear", bull_agent, bear_agent),
    ]

    for questioner, respondent, q_agent, a_agent in directions:
        questions = await q_agent.cross_examine(
            topic, transcript, background, injected_views,
        )
        if not questions:
            logger.info("交叉质询跳过：%s 未生成问题", questioner)
            continue

        answers = await a_agent.answer_cross(
            topic, questions, transcript, background, injected_views,
        )
        if not answers:
            logger.info("交叉质询跳过：%s 未生成回答", respondent)
            continue

        turn = Turn(
            speaker=questioner,
            round=round_num,
            content=CrossExamination(
                questioner=questioner,
                respondent=respondent,
                questions=questions,
                answers=answers,
                raw="",
            ),
        )
        transcript.append(turn)
        turns.append(turn)
        if on_turn is not None:
            await on_turn(turn)

    return turns