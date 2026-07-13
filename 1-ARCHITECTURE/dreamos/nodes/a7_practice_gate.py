"""
A7 实践论门禁节点

基于实践论的决策验证能力：
    - 历史表现验证
    - 策略胜率检查
    - 置信度校准
    - 实战记录匹配
    - 65% 置信度门槛

输入: state.intent + state.history + state.prior_conclusions
输出: direction / confidence / gate_result / confidence_threshold / rationale
"""

from __future__ import annotations

from typing import Dict, Any, List, Optional

from dreamos.registry.base import BaseNode
from dreamos.shared.state import State, NodeResult


class A7PracticeGateNode(BaseNode):
    """A7 实践论门禁节点

    基于历史实战记录验证当前决策的有效性，65% 置信度门槛。
    """

    node_id = "A7"
    name = "实践论门禁"
    description = "历史实战验证（策略胜率/置信度校准/65%门槛/实战记录匹配）"
    chain = "A"
    tags = ["practice", "gate", "validation", "confidence", "history"]
    estimated_tokens = 0
    estimated_latency_ms = 100

    def execute_core(self, state: State) -> NodeResult:
        intent = state.intent if isinstance(state.intent, dict) else {}
        prior_conclusions = self._get_prior_conclusions(state)
        history = self._get_history(state)
        rationale: List[str] = []
        scores = []

        confidence_threshold = 0.65
        proposed_direction = intent.get("direction", "HOLD")
        proposed_confidence = intent.get("confidence", 0.5)

        # ── 1. 获取历史表现 ──────────────────────────────
        total_trades = history.get("total_trades", 0)
        win_trades = history.get("win_trades", 0)
        win_rate = win_trades / max(total_trades, 1) * 100

        # ── 2. 策略胜率检查 ──────────────────────────────
        if win_rate > 60:
            scores.append(("LONG", 0.20, f"历史胜率高({win_rate:.1f}%)"))
        elif win_rate < 40:
            scores.append(("HOLD", 0.25, f"历史胜率低({win_rate:.1f}%)，需要提高置信度"))

        # ── 3. 置信度校准 ────────────────────────────────
        calibrated_confidence = proposed_confidence
        if total_trades > 10:
            calibrated_confidence = proposed_confidence * (0.5 + win_rate / 200)

        # ── 4. 实战记录匹配 ──────────────────────────────
        similar_trades = history.get("similar_trades", [])
        similar_win_rate = 0
        if similar_trades:
            similar_win_rate = sum(1 for t in similar_trades if t.get("win", False)) / len(similar_trades) * 100
            if similar_win_rate > 65:
                scores.append(("LONG", 0.20, f"相似场景胜率高({similar_win_rate:.1f}%)"))
            elif similar_win_rate < 45:
                scores.append(("HOLD", 0.20, f"相似场景胜率低({similar_win_rate:.1f}%)"))

        # ── 5. 65% 置信度门槛检查 ────────────────────────
        gate_passed = calibrated_confidence >= confidence_threshold

        if gate_passed:
            scores.append(("LONG", 0.30, f"置信度达标({calibrated_confidence:.1%} >= {confidence_threshold:.1%})"))
        else:
            scores.append(("HOLD", 0.35, f"置信度未达标({calibrated_confidence:.1%} < {confidence_threshold:.1%})"))

        # ── 6. 连续亏损检查 ──────────────────────────────
        loss_streak = history.get("loss_streak", 0)
        if loss_streak >= 3:
            scores.append(("HOLD", 0.20, f"连续亏损{loss_streak}次，建议观望"))
            gate_passed = False

        # ── 7. 与前期结论一致性检查 ────────────────────────
        if prior_conclusions:
            recent_directions = [c.get("direction") for c in prior_conclusions[-5:] if c.get("direction")]
            if recent_directions and all(d == proposed_direction for d in recent_directions):
                scores.append(("LONG", 0.10, "与前期结论一致"))
            elif len(set(recent_directions)) > 1:
                scores.append(("HOLD", 0.10, "前期结论不一致"))

        # ── 综合计算 ────────────────────────────────────
        long_score = sum(w for d, w, _ in scores if d == "LONG")
        short_score = sum(w for d, w, _ in scores if d == "SHORT")
        hold_score = sum(w for d, w, _ in scores if d == "HOLD")
        total = long_score + short_score + hold_score

        if gate_passed:
            direction = proposed_direction
            confidence = calibrated_confidence
        else:
            direction = "HOLD"
            confidence = calibrated_confidence

        gate_result = "passed" if gate_passed else "blocked"

        rationale = [r for _, _, r in scores[:6]]
        rationale.insert(0, f"[A7实践论门禁] 门禁={gate_result} | 校准置信度={calibrated_confidence:.1%}")
        rationale.append(f"  方向: {direction} | 门槛: {confidence_threshold:.1%}")

        outputs = {
            "gate_result": gate_result,
            "gate_passed": gate_passed,
            "confidence_threshold": confidence_threshold,
            "proposed_confidence": proposed_confidence,
            "calibrated_confidence": round(calibrated_confidence, 3),
            "direction": direction,
            "history": {
                "total_trades": total_trades,
                "win_trades": win_trades,
                "win_rate": round(win_rate, 2),
                "loss_streak": loss_streak,
                "similar_trades_count": len(similar_trades),
                "similar_win_rate": round(similar_win_rate, 2),
            },
            "prior_conclusions_consistency": len(set(recent_directions)) == 1 if recent_directions else True,
            "scores": {"long": round(long_score, 3), "short": round(short_score, 3), "hold": round(hold_score, 3)},
            "rationale": rationale,
        }

        return NodeResult(
            node_id="A7",
            confidence=round(confidence, 3),
            direction=direction,
            outputs=outputs,
        )

    def _get_prior_conclusions(self, state: State) -> List[Dict]:
        if hasattr(state, "prior_conclusions") and state.prior_conclusions:
            return state.prior_conclusions
        if isinstance(state.intent, dict) and "prior_conclusions" in state.intent:
            return state.intent["prior_conclusions"]
        return []

    def _get_history(self, state: State) -> Dict[str, Any]:
        if hasattr(state, "history") and state.history:
            return state.history
        if isinstance(state.intent, dict) and "history" in state.intent:
            return state.intent["history"]
        return {"total_trades": 0, "win_trades": 0, "loss_streak": 0, "similar_trades": []}