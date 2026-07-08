"""
A5 交易执行节点 — 综合前序结果，生成最终交易指令
"""

from __future__ import annotations

from typing import Dict, Any, List

from dreamos.registry.base import BaseNode
from dreamos.shared.state import State, NodeResult


class A5ExecutionNode(BaseNode):
    """A5 交易执行节点

    综合前序节点（A2/A3/A4）的结果，生成最终交易指令。
    输出: action + size + leverage + 入场/止损/止盈
    """

    node_id = "A5"
    name = "交易执行"
    description = "综合前序结果，生成最终交易指令"
    chain = "A"
    tags = ["execution", "trade", "final-decision"]
    estimated_tokens = 0
    estimated_latency_ms = 60

    def execute_core(self, state: State) -> NodeResult:
        mkt = self._get_market_data(state)
        price = mkt.get("price", 0)
        coin = mkt.get("coin", "BTC")
        atr_pct = mkt.get("atr_pct", 0.02)
        atr = price * atr_pct

        rationale: List[str] = []

        a4_result = state.get_result("A4")
        a3_result = state.get_result("A3")

        if a4_result:
            gate_passed = a4_result.outputs.get("gate_passed", False)
            direction = a4_result.direction or "HOLD"
            confidence = a4_result.confidence
        else:
            gate_passed = False
            direction = "HOLD"
            confidence = 0.0

        if not gate_passed or direction == "HOLD":
            rationale.append("[A5] A4门禁未通过或方向为HOLD，不生成交易指令")
            return NodeResult(
                node_id="A5",
                confidence=0.5,
                direction="HOLD",
                outputs={
                    "rationale": rationale,
                    "trade_order": {},
                },
            )

        strategy = {}
        if a3_result and a3_result.outputs.get("strategy"):
            strategy = a3_result.outputs["strategy"]

        position_size = strategy.get("position_size", 10.0)
        leverage = strategy.get("leverage", 3)
        stop_loss = strategy.get("stop_loss", 0)
        take_profit = strategy.get("take_profit", 0)

        if stop_loss == 0 or take_profit == 0:
            if direction == "LONG":
                stop_loss = round(price * (1 - atr_pct * 1.5), 4)
                take_profit = round(price * (1 + atr_pct * 3.0), 4)
            else:
                stop_loss = round(price * (1 + atr_pct * 1.5), 4)
                take_profit = round(price * (1 - atr_pct * 3.0), 4)

        trade_order = {
            "action": direction,
            "coin": coin,
            "entry_price": price,
            "position_size": round(position_size, 2),
            "leverage": leverage,
            "stop_loss": stop_loss,
            "take_profit": take_profit,
            "risk_per_trade": position_size * atr_pct,
            "rr_ratio": round(abs(take_profit - price) / max(abs(price - stop_loss), 0.0001), 2),
        }

        rationale.append(f"[A5交易执行] {direction} {coin} @ ${price:.4f}")
        rationale.append(f"  仓位: {trade_order['position_size']:.2f} USDT")
        rationale.append(f"  杠杆: {trade_order['leverage']}x")
        rationale.append(f"  止损: ${trade_order['stop_loss']:.4f}")
        rationale.append(f"  止盈: ${trade_order['take_profit']:.4f}")
        rationale.append(f"  R:R: {trade_order['rr_ratio']:.2f}:1")

        return NodeResult(
            node_id="A5",
            confidence=round(confidence, 3),
            direction=direction,
            outputs={
                "rationale": rationale,
                "trade_order": trade_order,
                "gate_passed": gate_passed,
            },
        )

    def _get_market_data(self, state: State) -> Dict[str, Any]:
        if hasattr(state, "market") and state.market:
            return state.market
        if hasattr(state, "market_data") and state.market_data:
            return state.market_data
        if isinstance(state.intent, dict) and "mkt" in state.intent:
            return state.intent["mkt"]
        return {}