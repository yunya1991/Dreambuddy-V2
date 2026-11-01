# -*- coding: utf-8 -*-
"""
position_swap.py — 裁判顺序对调（P2-5，SPEC §9）
==================================================
同一对候选按 (A,B) 与 (B,A) 两次询问裁判；只有两次映射回同一胜者才算一致，
用于抑制首位偏好（position bias）。不一致记为 flip，winner=None，交由人工/仲裁。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

VERDICTS = ("first", "second", "tie")


def winner_from_pair(verdict: str, swapped: bool = False) -> str:
    """把裁判的 first/second/tie 映射成候选 A/B/tie（swapped=True 表示第二遍对调）。"""
    if verdict not in VERDICTS:
        raise ValueError(f"非法裁判结论：{verdict}")
    if verdict == "tie":
        return "tie"
    first_is_a = not swapped
    if verdict == "first":
        return "A" if first_is_a else "B"
    return "B" if first_is_a else "A"


@dataclass(frozen=True)
class SwapJudgement:
    """一次顺序对调评审的留痕（报告证据：两遍原始结论 + 映射后胜者）。"""

    item_id: str
    prompt: str
    first_pass: str  # 映射后第一遍胜者（A/B/tie）
    second_pass: str  # 映射后第二遍胜者（A/B/tie）
    winner: str | None
    consistent: bool

    @property
    def flipped(self) -> bool:
        return not self.consistent


class PositionSwapJudge:
    """judge 返回 first/second/tie；两遍调用后取一致结论。"""

    def __init__(self, judge: Callable[[str, str, str], str]) -> None:
        self._judge = judge

    def judge(self, item_id: str, prompt: str, option_a: str, option_b: str) -> SwapJudgement:
        raw_first = self._judge(prompt, option_a, option_b)
        raw_second = self._judge(prompt, option_b, option_a)
        first_pass = winner_from_pair(raw_first, swapped=False)
        second_pass = winner_from_pair(raw_second, swapped=True)
        consistent = first_pass == second_pass
        return SwapJudgement(
            item_id=item_id,
            prompt=prompt,
            first_pass=first_pass,
            second_pass=second_pass,
            winner=first_pass if consistent else None,
            consistent=consistent,
        )
