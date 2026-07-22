"""
A8 知行合一验证节点

基于知行合一的执行验证能力：
    - 策略执行一致性检查
    - 计划 vs 实际执行对比
    - 知行偏差检测
    - 行动验证
    - 执行质量评估

输入: state.intent + state.position + state.execution_history
输出: direction / confidence / consistency_score / execution_quality / rationale
"""

from __future__ import annotations

from typing import Dict, Any, List, Optional

from dreamos.registry.base import BaseNode
from dreamos.shared.state import State, NodeResult


class A8UnityNode(BaseNode):
    """A8 知行合一验证节点

    验证策略计划与实际执行的一致性，检测知行偏差。
    """

    node_id = "A8"
    name = "知行合一"
    description = "策略执行验证（计划vs实际/知行偏差/执行质量/一致性检查）"
    chain = "A"
    tags = ["unity", "execution", "consistency", "validation", "action"]
    estimated_tokens = 0
    estimated_latency_ms = 100

    def execute_core(self, state: State) -> NodeResult:
        intent = state.intent if isinstance(state.intent, dict) else {}
        position = self._get_position(state)
        execution_history = self._get_execution_history(state)
        rationale: List[str] = []
        scores = []

        # ── 1. 获取计划和执行信息 ────────────────────────
        planned_direction = intent.get("direction", "HOLD")
        planned_entry = intent.get("planned_entry", 0)
        planned_stop = intent.get("planned_stop", 0)
        planned_target = intent.get("planned_target", 0)

        actual_direction = position.get("direction", "HOLD")
        actual_entry = position.get("entry_price", 0)
        actual_size = position.get("size", 0)

        # ── 2. 方向一致性检查 ────────────────────────────
        direction_consistent = planned_direction == actual_direction
        if direction_consistent:
            scores.append(("LONG", 0.25, "计划方向与实际一致"))
        else:
            scores.append(("HOLD", 0.30, f"方向不一致(计划:{planned_direction} vs 实际:{actual_direction})"))

        # ── 3. 入场价格偏差检查 ──────────────────────────
        entry_deviation = 0
        if planned_entry > 0 and actual_entry > 0:
            entry_deviation = abs(actual_entry - planned_entry) / planned_entry * 100

        if entry_deviation < 1:
            scores.append(("LONG", 0.20, f"入场价格偏差小({entry_deviation:.2f}%)"))
        elif entry_deviation < 3:
            scores.append(("LONG", 0.10, f"入场价格偏差可接受({entry_deviation:.2f}%)"))
        else:
            scores.append(("HOLD", 0.20, f"入场价格偏差大({entry_deviation:.2f}%)"))

        # ── 4. 仓位一致性检查 ────────────────────────────
        planned_size = intent.get("planned_size", 0)
        size_consistent = abs(actual_size - planned_size) < max(planned_size, 1) * 0.1
        if planned_size > 0:
            if size_consistent:
                scores.append(("LONG", 0.15, "仓位执行一致"))
            else:
                scores.append(("HOLD", 0.15, f"仓位不一致(计划:{planned_size} vs 实际:{actual_size})"))

        # ── 5. 执行历史质量评估 ──────────────────────────
        execution_quality = self._evaluate_execution_quality(execution_history)
        if execution_quality > 80:
            scores.append(("LONG", 0.20, f"执行质量高({execution_quality:.0f})"))
        elif execution_quality > 60:
            scores.append(("LONG", 0.10, f"执行质量良好({execution_quality:.0f})"))
        elif execution_quality > 40:
            scores.append(("HOLD", 0.10, f"执行质量一般({execution_quality:.0f})"))
        else:
            scores.append(("HOLD", 0.20, f"执行质量差({execution_quality:.0f})"))

        # ── 6. 知行偏差检测 ──────────────────────────────
        inconsistency_count = sum([
            not direction_consistent,
            entry_deviation > 3,
            not size_consistent,
            execution_quality < 50,
        ])

        if inconsistency_count == 0:
            scores.append(("LONG", 0.20, "知行合一，无偏差"))
        elif inconsistency_count <= 1:
            scores.append(("LONG", 0.10, f"轻微知行偏差({inconsistency_count}项)"))
        else:
            scores.append(("HOLD", 0.25, f"明显知行偏差({inconsistency_count}项)"))

        # ── 7. 行动验证 ──────────────────────────────────
        action_taken = actual_size > 0
        if action_taken:
            scores.append(("LONG", 0.10, "已执行交易"))
        else:
            scores.append(("HOLD", 0.10, "未执行交易"))

        # ── 综合计算 ────────────────────────────────────
        long_score = sum(w for d, w, _ in scores if d == "LONG")
        short_score = sum(w for d, w, _ in scores if d == "SHORT")
        hold_score = sum(w for d, w, _ in scores if d == "HOLD")
        total = long_score + short_score + hold_score

        consistency_score = long_score / max(total + hold_score, 0.01)

        if total == 0:
            direction = "LONG"
            confidence = 0.5
        elif hold_score > long_score:
            direction = "HOLD"
            confidence = hold_score / max(total, 0.01)
        elif long_score > short_score:
            direction = "LONG"
            confidence = long_score / max(total, 0.01)
        else:
            direction = "SHORT"
            confidence = short_score / max(total, 0.01)

        rationale = [r for _, _, r in scores[:6]]
        rationale.insert(0, f"[A8知行合一] 一致性得分={consistency_score:.2f} | 执行质量={execution_quality:.0f}")
        rationale.append(f"  方向: {direction} | 置信度: {confidence:.1%}")

        outputs = {
            "consistency_score": round(consistency_score, 3),
            "execution_quality": execution_quality,
            "direction_consistent": direction_consistent,
            "entry_deviation_pct": round(entry_deviation, 2),
            "size_consistent": size_consistent,
            "inconsistency_count": inconsistency_count,
            "action_taken": action_taken,
            "planned": {
                "direction": planned_direction,
                "entry": planned_entry,
                "stop": planned_stop,
                "target": planned_target,
                "size": planned_size,
            },
            "actual": {
                "direction": actual_direction,
                "entry": actual_entry,
                "size": actual_size,
            },
            "scores": {"long": round(long_score, 3), "short": round(short_score, 3), "hold": round(hold_score, 3)},
            "rationale": rationale,
        }

        return NodeResult(
            node_id="A8",
            confidence=round(confidence, 3),
            direction=direction,
            outputs=outputs,
        )

    def _evaluate_execution_quality(self, history: List[Dict]) -> float:
        if not history:
            return 70

        total = len(history)
        success_count = sum(1 for h in history if h.get("success", False))
        avg_latency = sum(h.get("latency_ms", 0) for h in history) / total

        quality = 50
        quality += (success_count / total) * 30
        quality += min(20, max(0, (1000 - avg_latency) / 50))
        return min(100, quality)

    def _get_position(self, state: State) -> Dict[str, Any]:
        if hasattr(state, "position") and state.position:
            return state.position
        if isinstance(state.intent, dict) and "position" in state.intent:
            return state.intent["position"]
        return {"direction": "HOLD", "entry_price": 0, "size": 0}

    def _get_execution_history(self, state: State) -> List[Dict]:
        if hasattr(state, "execution_history") and state.execution_history:
            return state.execution_history
        if isinstance(state.intent, dict) and "execution_history" in state.intent:
            return state.intent["execution_history"]
        return []