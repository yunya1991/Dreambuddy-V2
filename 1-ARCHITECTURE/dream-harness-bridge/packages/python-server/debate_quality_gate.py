#!/usr/bin/env python3
"""debate_quality_gate.py — 方案C 辩论质量门控 (SPEC §3)

在 Layer 3 训练前，用 jev noul 判断辩论是否达到训练质量门槛。
低于门槛的辩论不进入 Bayesian/Elo/CBR 更新。

HC-J1: FAIL-OPEN — jev 不可用时 passed=True（不阻塞训练）
HC-J4: 冷启动(debate_count<20)使用低阈值 cold_start_threshold
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Callable, Optional

logger = logging.getLogger("debate.quality_gate")

# 默认阈值
DEFAULT_THRESHOLD = 0.55
DEFAULT_COLD_START_THRESHOLD = 0.35
COLD_START_DEBATE_COUNT = 20


@dataclass
class QualityGateResult:
    """质量门控结果。"""
    passed: bool
    noul: float
    reason: str
    degraded: bool


# ── jev noul 问题模板 ─────────────────────────────────────────

QUALITY_GATE_QUESTION = {
    "type": "noul",
    "instructions": (
        "判断以下辩论是否达到训练质量门槛。"
        "高质量辩论特征：正反方都提出有实质内容的论点、存在真实交锋、"
        "论点与话题直接相关。低质量辩论特征：一方无实质论点、各说各话、"
        "论点与话题无关。"
        "返回 yes/no/uncertain + 置信度。"
    ),
}


class DebateQualityGate:
    """辩论质量门控器。

    用法:
        gate = DebateQualityGate(jev_fn=jev_fn)
        result = gate.gate(topic, transcript, adj_result, debate_count)
        if result.passed:
            # 执行 Layer 3 训练
    """

    def __init__(
        self,
        jev_fn: Optional[Callable[..., dict]] = None,
        threshold: float = DEFAULT_THRESHOLD,
        cold_start_threshold: float = DEFAULT_COLD_START_THRESHOLD,
    ):
        """
        Args:
            jev_fn: jev 调用函数 (state, questions) -> dict.
                None 时降级 (FAIL-OPEN).
            threshold: 正常阶段质量门槛 [0,1]
            cold_start_threshold: 冷启动阶段质量门槛
        """
        self._jev_fn = jev_fn
        self._threshold = threshold
        self._cold_start_threshold = cold_start_threshold

    def gate(
        self,
        topic: str,
        transcript: list[dict],
        adjudication_result: Any,
        debate_count: int,
    ) -> QualityGateResult:
        """判断辩论是否达到训练质量门槛。

        Args:
            topic: 辩论话题
            transcript: 辩论记录
            adjudication_result: AdjudicationResult (Layer 1 产出)
            debate_count: 累计辩论场次（用于冷启动判定）

        Returns:
            QualityGateResult

        FAIL-OPEN: jev 不可用/异常 → degraded=True, passed=True
        """
        # HC-J1: 无 jev_fn → 降级放行
        if self._jev_fn is None:
            return QualityGateResult(
                passed=True, noul=0.0, reason="jev_unavailable", degraded=True)

        # 冷启动保护：debate_count < 20 使用低阈值
        threshold = (self._cold_start_threshold
                     if debate_count < COLD_START_DEBATE_COUNT
                     else self._threshold)

        # 构建 state
        state = self._build_state(topic, transcript, adjudication_result)
        questions = {"q1": QUALITY_GATE_QUESTION}

        try:
            resp = self._jev_fn(state, questions)
        except Exception as e:  # noqa: BLE001 FAIL-OPEN
            logger.warning("质量门控 jev 异常(FAIL-OPEN): %s", e)
            return QualityGateResult(
                passed=True, noul=0.0,
                reason=f"jev_exception:{type(e).__name__}", degraded=True)

        # jev 降级 → 放行
        if not isinstance(resp, dict) or resp.get("degraded", False):
            return QualityGateResult(
                passed=True, noul=0.0,
                reason=resp.get("reason", "jev_degraded") if isinstance(resp, dict) else "jev_degraded",
                degraded=True)

        # 提取 noul
        answers = resp.get("answers", {})
        noul = None
        for v in answers.values():
            if isinstance(v, dict) and "noul" in v:
                try:
                    noul = float(v["noul"])
                except (ValueError, TypeError):
                    noul = None
                break

        # 无 noul → 降级放行
        if noul is None:
            return QualityGateResult(
                passed=True, noul=0.0, reason="missing_noul", degraded=True)

        # 门控判定
        passed = noul >= threshold
        reason = "" if passed else f"noul={noul:.2f}<threshold={threshold:.2f}"

        return QualityGateResult(
            passed=passed, noul=noul, reason=reason, degraded=False)

    @staticmethod
    def _build_state(
        topic: str,
        transcript: list[dict],
        adjudication_result: Any,
    ) -> dict:
        """构建 jev 状态输入。"""
        winner = getattr(adjudication_result, "winner", "draw")
        bull_total = getattr(adjudication_result, "bull_total", 0.0)
        bear_total = getattr(adjudication_result, "bear_total", 0.0)
        rfd = getattr(adjudication_result, "rfd", "")
        clash = getattr(adjudication_result, "key_clash_points", [])

        # 提取策略标签
        bull_strategies = []
        bear_strategies = []
        for t in transcript or []:
            content = t.get("content", {}) if isinstance(t, dict) else {}
            strat = content.get("strategy") if isinstance(content, dict) else None
            if t.get("speaker") == "bull" and strat:
                bull_strategies.append(str(strat))
            elif t.get("speaker") == "bear" and strat:
                bear_strategies.append(str(strat))

        # 辩论摘要（截断）
        summary_parts = []
        for t in (transcript or [])[:4]:
            content = t.get("content", {}) if isinstance(t, dict) else {}
            thesis = content.get("thesis", "") if isinstance(content, dict) else ""
            if thesis:
                summary_parts.append(f"{t.get('speaker','?')}: {thesis}")
        transcript_summary = " | ".join(summary_parts)[:500]

        return {
            "topic": topic,
            "winner": winner,
            "bull_total": bull_total,
            "bear_total": bear_total,
            "rfd": rfd,
            "key_clash_points": clash,
            "bull_strategies": bull_strategies,
            "bear_strategies": bear_strategies,
            "transcript_summary": transcript_summary,
        }
