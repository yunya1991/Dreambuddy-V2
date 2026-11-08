"""profiles/base.py — 辩论 profile 契约。

一个 profile 规定：
- 正/反方/裁判的 system prompt；
- 交叉质询的提问/回答 system prompt；
- 是否启用营销素材/质量评分（marketing）；
- 是否要求证据引用（technical/signal）。

profile 只改变“角色设定与输出语义”，不改变通用辩论循环/状态机。
"""
from __future__ import annotations

from dataclasses import dataclass

from core.prompts import (
    CROSS_EXAM_ANSWER_SYSTEM,
    CROSS_EXAM_QUESTION_SYSTEM,
)


@dataclass(frozen=True)
class DebateProfile:
    name: str
    bull_system_prompt: str
    bear_system_prompt: str
    judge_system_prompt: str
    question_system: str = CROSS_EXAM_QUESTION_SYSTEM
    answer_system: str = CROSS_EXAM_ANSWER_SYSTEM
    marketing: bool = False
    technical: bool = False
    signal: bool = False
    evidence_required: bool = False