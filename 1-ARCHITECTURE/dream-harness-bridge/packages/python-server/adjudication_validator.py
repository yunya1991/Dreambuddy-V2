#!/usr/bin/env python3
"""adjudication_validator.py — 方案B 评审结果校验 (SPEC §4)

Layer 1 Adjudicator 用 LLM 产出评分后，用 jev 做二次校验：
1. noul — 评分分布是否合理
2. choice — 胜方判定是否一致

评分不合理 → 警告不覆盖（jev 仅校验）
胜方不一致 → 取 jev 建议胜方（jev 是专用决策模型）

HC-J1: FAIL-OPEN — jev 不可用时不影响 LLM 评分
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Callable, Optional

logger = logging.getLogger("debate.adjudication_validator")

# 评分合理性阈值
SCORE_REASONABLE_THRESHOLD = 0.5


@dataclass
class ValidationResult:
    """评审校验结果。"""
    score_reasonable: bool
    winner_consistent: bool
    noul: float
    suggested_winner: str
    degraded: bool


# ── jev 问题模板 ─────────────────────────────────────────────

SCORE_REASONABLE_QUESTION = {
    "type": "noul",
    "instructions": (
        "评估以下辩论评分是否合理。"
        "合理评分特征：分数差异与 RFD 描述一致、维度间无明显矛盾、"
        "胜方在关键维度（逻辑有效性/事实真实性）领先。"
        "返回 yes/no/uncertain + 置信度。"
    ),
}

WINNER_CONSISTENT_QUESTION = {
    "type": "choice",
    "instructions": "根据以下辩论内容和评分，判定胜方。",
    "criteria": {
        "bull": "正方获胜",
        "bear": "反方获胜",
        "draw": "平局",
    },
}


class AdjudicationValidator:
    """评审结果校验器。

    用法:
        validator = AdjudicationValidator(jev_fn=jev_fn)
        result = validator.validate(topic, transcript, adj_result)
    """

    def __init__(
        self,
        jev_fn: Optional[Callable[..., dict]] = None,
    ):
        self._jev_fn = jev_fn

    def validate(
        self,
        topic: str,
        transcript: list[dict],
        adjudication_result: Any,
    ) -> ValidationResult:
        """校验 LLM 评分结果的合理性。

        Args:
            topic: 辩论话题
            transcript: 辩论记录
            adjudication_result: AdjudicationResult (会被原地修改 winner)

        Returns:
            ValidationResult

        FAIL-OPEN: jev 不可用/异常 → degraded=True，评分不变
        """
        # HC-J1: 无 jev_fn → 降级
        if self._jev_fn is None:
            return ValidationResult(
                score_reasonable=True, winner_consistent=True,
                noul=0.0, suggested_winner="", degraded=True)

        # 构建 state
        state = self._build_state(topic, transcript, adjudication_result)
        questions = {
            "score_q": SCORE_REASONABLE_QUESTION,
            "winner_q": WINNER_CONSISTENT_QUESTION,
        }

        try:
            resp = self._jev_fn(state, questions)
        except Exception as e:  # noqa: BLE001 FAIL-OPEN
            logger.warning("评审校验 jev 异常(FAIL-OPEN): %s", e)
            return ValidationResult(
                score_reasonable=True, winner_consistent=True,
                noul=0.0, suggested_winner="", degraded=True)

        # jev 降级
        if not isinstance(resp, dict) or resp.get("degraded", False):
            return ValidationResult(
                score_reasonable=True, winner_consistent=True,
                noul=0.0, suggested_winner="", degraded=True)

        answers = resp.get("answers", {})

        # 提取评分合理性 noul
        noul = 0.0
        score_ans = answers.get("score_q", {})
        if isinstance(score_ans, dict) and "noul" in score_ans:
            try:
                noul = float(score_ans["noul"])
            except (ValueError, TypeError):
                noul = 0.0
        score_reasonable = noul >= SCORE_REASONABLE_THRESHOLD

        if not score_reasonable:
            logger.warning("评分合理性校验未通过 noul=%.2f (不覆盖 LLM 评分)", noul)

        # 提取胜方 choice
        winner_ans = answers.get("winner_q", {})
        suggested_winner = ""
        if isinstance(winner_ans, dict):
            suggested_winner = str(winner_ans.get("choice", ""))

        current_winner = getattr(adjudication_result, "winner", "draw")
        winner_consistent = (suggested_winner == current_winner)

        # 胜方不一致 → 取 jev 建议
        if not winner_consistent and suggested_winner in ("bull", "bear", "draw"):
            logger.info("胜方不一致: LLM=%s, jev=%s → 采用 jev 建议",
                        current_winner, suggested_winner)
            adjudication_result.winner = suggested_winner

        return ValidationResult(
            score_reasonable=score_reasonable,
            winner_consistent=winner_consistent,
            noul=noul,
            suggested_winner=suggested_winner,
            degraded=False,
        )

    @staticmethod
    def _build_state(
        topic: str,
        transcript: list[dict],
        adjudication_result: Any,
    ) -> dict:
        """构建 jev 状态输入。"""
        dim_comp = getattr(adjudication_result, "dimension_comparison", {})
        bull_scores = {d: dim_comp.get(d, {}).get("bull", 0) for d in dim_comp}
        bear_scores = {d: dim_comp.get(d, {}).get("bear", 0) for d in dim_comp}

        return {
            "topic": topic,
            "winner": getattr(adjudication_result, "winner", "draw"),
            "bull_total": getattr(adjudication_result, "bull_total", 0.0),
            "bear_total": getattr(adjudication_result, "bear_total", 0.0),
            "bull_scores": bull_scores,
            "bear_scores": bear_scores,
            "rfd": getattr(adjudication_result, "rfd", ""),
            "key_clash_points": getattr(adjudication_result, "key_clash_points", []),
        }
