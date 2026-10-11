#!/usr/bin/env python3
"""jev_score_supplement.py — 方案A 补充评分 (SPEC §5)

用 jev score 原语补充客观维度（事实真实性/逻辑有效性）评分，
与 LLM 评分加权融合。主观维度保留 LLM 评分。

融合: fused = (1 - jev_weight) * llm_score + jev_weight * jev_score
默认 jev_weight=0.4, 即 0.6*LLM + 0.4*jev

HC-J1: FAIL-OPEN — jev 不可用时保留 LLM 评分
"""
from __future__ import annotations

import logging
from typing import Any, Callable, Optional

logger = logging.getLogger("debate.jev_score_supplement")

OBJECTIVE_DIMS = ["fact_authenticity", "logical_validity"]
DEFAULT_JEV_WEIGHT = 0.4


# ── jev score 问题模板 ───────────────────────────────────────

SCORE_CRITERIA = ["明显虚假", "部分失实", "基本准确", "准确", "高度准确"]
LOGIC_CRITERIA = ["逻辑谬误严重", "逻辑有缺陷", "逻辑基本成立", "逻辑严密", "逻辑无懈可击"]


class JevScoreSupplement:
    """用 jev score 补充客观维度评分。"""

    def __init__(
        self,
        jev_fn: Optional[Callable[..., dict]] = None,
        jev_weight: float = DEFAULT_JEV_WEIGHT,
    ):
        self._jev_fn = jev_fn
        self._jev_weight = jev_weight

    def supplement(
        self,
        topic: str,
        transcript: list[dict],
        adjudication_result: Any,
    ) -> dict:
        """返回 jev 对客观维度的融合评分。

        Returns:
            {"fact_authenticity": {"bull": float, "bear": float},
             "logical_validity": {"bull": float, "bear": float},
             "degraded": bool}
        """
        result = {
            "fact_authenticity": {"bull": 0.0, "bear": 0.0},
            "logical_validity": {"bull": 0.0, "bear": 0.0},
            "degraded": True,
        }

        if self._jev_fn is None:
            return result

        dim_comp = getattr(adjudication_result, "dimension_comparison", {})

        # 4 个 score 问题
        questions = {
            "fact_bull": {"type": "score", "instructions": "评估正方论点的事实真实性。", "criteria": SCORE_CRITERIA},
            "fact_bear": {"type": "score", "instructions": "评估反方论点的事实真实性。", "criteria": SCORE_CRITERIA},
            "logic_bull": {"type": "score", "instructions": "评估正方论点的逻辑有效性。", "criteria": LOGIC_CRITERIA},
            "logic_bear": {"type": "score", "instructions": "评估反方论点的逻辑有效性。", "criteria": LOGIC_CRITERIA},
        }

        try:
            resp = self._jev_fn({"topic": topic}, questions)
        except Exception as e:  # noqa: BLE001 FAIL-OPEN
            logger.warning("补充评分 jev 异常(FAIL-OPEN): %s", e)
            return result

        if not isinstance(resp, dict) or resp.get("degraded", False):
            return result

        answers = resp.get("answers", {})

        # 提取 jev 评分
        jev_scores = {}
        for key in ["fact_bull", "fact_bear", "logic_bull", "logic_bear"]:
            ans = answers.get(key, {})
            if isinstance(ans, dict) and "score" in ans:
                try:
                    jev_scores[key] = float(ans["score"])
                except (ValueError, TypeError):
                    jev_scores[key] = 0.0

        # 融合
        w = self._jev_weight
        for dim in OBJECTIVE_DIMS:
            for side in ["bull", "bear"]:
                llm_val = dim_comp.get(dim, {}).get(side, 3.0)
                jev_key = f"{'fact' if dim == 'fact_authenticity' else 'logic'}_{side}"
                jev_val = jev_scores.get(jev_key, llm_val)
                # 钳制 1-5
                fused = (1 - w) * llm_val + w * jev_val
                fused = max(1.0, min(5.0, fused))
                result[dim][side] = fused

        result["degraded"] = False
        return result

    def apply(
        self,
        topic: str,
        transcript: list[dict],
        adjudication_result: Any,
    ) -> dict:
        """计算融合评分并原地更新 adjudication_result。

        仅更新客观维度，主观维度不变。
        """
        supplement = self.supplement(topic, transcript, adjudication_result)
        if supplement["degraded"]:
            return supplement

        dim_comp = getattr(adjudication_result, "dimension_comparison", {})
        if not isinstance(dim_comp, dict):
            return supplement

        for dim in OBJECTIVE_DIMS:
            if dim not in dim_comp:
                dim_comp[dim] = {}
            dim_comp[dim]["bull"] = supplement[dim]["bull"]
            dim_comp[dim]["bear"] = supplement[dim]["bear"]

        return supplement
