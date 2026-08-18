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
    description = "A7 实践论闸门，置信度 ≥ 门槛才允许开仓（做空门槛更高）"
    chain = "A"
    tags = ["gate", "risk-control", "practice-theory"]
    estimated_tokens = 0
    estimated_latency_ms = 50

    # 对称门槛：多空同等置信度要求（避免做空被过度过滤）
    LONG_THRESHOLD = 0.62
    SHORT_THRESHOLD = 0.62

    def _get_threshold(self, direction: str) -> float:
        return self.SHORT_THRESHOLD if direction == "SHORT" else self.LONG_THRESHOLD

    def execute_core(self, state: State) -> NodeResult:
        # 收集前序节点数据
        direction, confidence = self._collect_direction(state)
        threshold = self._get_threshold(direction)

        rationale: List[str] = [
            f"[A4/A7 门禁] 置信度: {confidence:.0%} | 门槛: {threshold:.0%}",
            f"方向: {direction}",
        ]

        # 门禁检查
        gate_passed = confidence >= threshold and direction != "HOLD"

        if gate_passed:
            rationale.append(f"✅ A7 闸门通过: {confidence:.0%} ≥ {threshold:.0%}")
            gate_reason = f"置信度{confidence:.0%} ≥ 门槛{threshold:.0%}，允许开仓"
        else:
            if confidence < threshold:
                rationale.append(f"❌ A7 拦截: 置信度{confidence:.0%} < 门槛{threshold:.0%}")
                gate_reason = f"置信度{confidence:.0%} < 门槛{threshold:.0%}，未过A7"
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
        """从 state 的结果中收集方向和置信度

        P3-4 优化: 从单节点最高置信度改为多节点加权投票 + 趋势确认
        - 收集所有非 HOLD 方向的节点
        - 加权投票（A 链权重 > C 链 > F 链）
        - 趋势确认：价格在 EMA50 之上才允许 LONG，之下才允许 SHORT
        - 方向分歧大时降为 HOLD
        """
        results = state.results if state.results else {}
        mkt = state.market_data if hasattr(state, "market_data") and state.market_data else {}

        # 收集所有非 HOLD 方向的节点
        votes = []  # [(node_id, direction, confidence, weight)]
        NODE_WEIGHTS = {
            "A0": 1.5, "A1": 1.3, "A2": 1.5, "A3": 1.5,
            "C1": 1.0, "C2": 0.8, "C3": 0.8,
            "F1": 0.7, "F2": 0.7, "F3": 0.6,
        }

        for node_id, result in results.items():
            if not hasattr(result, "direction") or not result.direction or result.direction == "HOLD":
                continue
            if not hasattr(result, "confidence") or result.confidence <= 0:
                continue
            weight = NODE_WEIGHTS.get(node_id, 0.5)
            votes.append((node_id, result.direction, result.confidence, weight))

        if not votes:
            return "HOLD", 0.0

        # 加权投票
        long_score = sum(c * w for _, d, c, w in votes if d == "LONG")
        short_score = sum(c * w for _, d, c, w in votes if d == "SHORT")
        total = long_score + short_score

        if total == 0:
            return "HOLD", 0.0

        long_ratio = long_score / total
        short_ratio = short_score / total

        # 方向分歧检查：如果多空接近（差 < 20%），返回 HOLD
        if abs(long_ratio - short_ratio) < 0.2:
            return "HOLD", max(long_score, short_score) / total * 0.5

        # 确定方向
        direction = "LONG" if long_score > short_score else "SHORT"
        confidence = max(long_score, short_score) / total

        # P3-4: 趋势确认 — 价格相对于 EMA50 的位置
        price = mkt.get("price", 0)
        ema50 = mkt.get("ema50", 0)
        ema200 = mkt.get("ema200", 0)

        if price > 0 and ema50 > 0:
            if direction == "LONG" and price < ema50:
                # 做多但价格在 EMA50 之下，趋势不支持，适度降权
                confidence *= 0.85  # 原为0.7，过于保守
            elif direction == "SHORT" and price > ema50:
                # 做空但价格在 EMA50 之上，趋势不支持，适度降权
                confidence *= 0.85  # 原为0.7

        # 大趋势确认（EMA200）
        if price > 0 and ema200 > 0:
            if direction == "LONG" and price < ema200:
                confidence *= 0.9   # 大趋势向下，做多轻微降权（原为0.8）
            elif direction == "SHORT" and price > ema200:
                confidence *= 0.9   # 大趋势向上，做空轻微降权（原为0.8）

        # 投票一致性加成：如果 2+ 节点同方向，置信度提升
        same_dir_count = sum(1 for _, d, _, _ in votes if d == direction)
        if same_dir_count >= 3:
            confidence *= 1.1
        elif same_dir_count == 1:
            confidence *= 0.9   # 仅 1 个节点支持，轻微降权（原为0.85）

        confidence = min(confidence, 0.95)

        return direction, round(confidence, 3)
