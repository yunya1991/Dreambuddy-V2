"""
A4 门禁节点 — A7 实践论闸门
"""

from __future__ import annotations

from typing import Any, Dict, List

from dreamos.registry.base import BaseNode
from dreamos.shared.state import State, NodeResult


class A4GateNode(BaseNode):
    """A4 门禁节点 — A7 实践论闸门

    置信度达到门槛才允许开仓，防止低质量信号。
    默认门槛: 65%
    """

    node_id = "A4"
    name = "门禁闸门"
    description = "A7 实践论闸门，置信度 ≥ 门槛才允许开仓"
    chain = "A"
    tags = ["gate", "risk-control", "practice-theory"]
    estimated_tokens = 0
    estimated_latency_ms = 50

    GATE_THRESHOLD = 0.65

    def execute_core(self, state: State) -> NodeResult:
        # 收集前序节点数据
        direction, confidence = self._collect_direction(state)

        rationale: List[str] = [
            f"[A4/A7 门禁] 置信度: {confidence:.0%} | 门槛: {self.GATE_THRESHOLD:.0%}",
            f"方向: {direction}",
        ]

        # 门禁检查
        gate_passed = confidence >= self.GATE_THRESHOLD and direction != "HOLD"

        if gate_passed:
            rationale.append(f"✅ A7 闸门通过: {confidence:.0%} ≥ {self.GATE_THRESHOLD:.0%}")
            gate_reason = f"置信度{confidence:.0%} ≥ 门槛{self.GATE_THRESHOLD:.0%}，允许开仓"
        else:
            if confidence < self.GATE_THRESHOLD:
                rationale.append(f"❌ A7 拦截: 置信度{confidence:.0%} < 门槛{self.GATE_THRESHOLD:.0%}")
                gate_reason = f"置信度{confidence:.0%} < 门槛{self.GATE_THRESHOLD:.0%}，未过A7"
            else:
                rationale.append(f"❌ A7 拦截: 方向={direction}（非交易方向）")
                gate_reason = f"方向={direction}，无有效信号"

        # A8 知行合一检查
        intent = getattr(state, "intent", {}) if hasattr(state, "intent") else {}
        intent_confidence = intent.get("confidence", 0.0) if isinstance(intent, dict) else 0.0
        if intent_confidence > 0:
            gap = abs(confidence - intent_confidence)
            rationale.append(f"[A8 知行合一] 意图={intent_confidence:.0%} vs 执行={confidence:.0%} | Gap={gap:+.0%}")
            if gap > 0.25:
                rationale.append("⚠️ 知行偏差大，建议反思")
            elif gap <= 0.10:
                rationale.append("✅ 知行基本一致")

        # 门禁拦截则方向改为 HOLD
        final_direction = direction if gate_passed else "HOLD"

        return NodeResult(
            node_id="A4",
            confidence=round(confidence, 3),
            direction=final_direction,
            outputs={
                "gate_passed": gate_passed,
                "gate_reason": gate_reason,
                "rationale": rationale,
            },
        )

    def _collect_direction(self, state: State) -> tuple:
        """从 state 的结果中收集方向和置信度"""
        direction = "HOLD"
        confidence = 0.0

        results = state.results if state.results else {}
        for node_id, result in results.items():
            if hasattr(result, "direction") and result.direction and result.direction != "HOLD":
                if hasattr(result, "confidence") and result.confidence > confidence:
                    direction = result.direction
                    confidence = result.confidence

        return direction, confidence
