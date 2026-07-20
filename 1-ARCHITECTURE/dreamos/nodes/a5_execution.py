"""
A5 交易执行节点 — 综合前序结果，生成最终交易指令
"""

from __future__ import annotations

import os
from typing import Dict, Any, List

from dreamos.registry.base import BaseNode
from dreamos.shared.state import State, NodeResult

MIN_LEVERAGE = 1
MAX_LEVERAGE = 5
DEFAULT_LEVERAGE = 3
CONFIDENCE_THRESHOLD = float(os.environ.get("DREAMOS_CONFIDENCE_THRESHOLD", "0.4"))


def calc_dynamic_leverage(
    confidence: float,
    min_lev: int = MIN_LEVERAGE,
    max_lev: int = MAX_LEVERAGE,
    threshold: float = CONFIDENCE_THRESHOLD,
) -> int:
    """基于置信度动态计算杠杆倍数

    映射逻辑:
      - 置信度 = threshold (默认 0.4) → min_lev (1x)
      - 置信度 = 0.6 → 约 3x
      - 置信度 >= 0.8 → max_lev (5x)
    """
    if confidence <= threshold:
        return min_lev
    if confidence >= 0.8:
        return max_lev
    ratio = (confidence - threshold) / (0.8 - threshold)
    lev = min_lev + ratio * (max_lev - min_lev)
    return max(min_lev, min(max_lev, int(round(lev))))


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
        if "leverage" in strategy and strategy["leverage"]:
            leverage = int(strategy["leverage"])
            leverage = max(MIN_LEVERAGE, min(MAX_LEVERAGE, leverage))
        else:
            leverage = calc_dynamic_leverage(confidence)
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
        rationale.append(f"  杠杆: {trade_order['leverage']}x (置信度={confidence:.2f})")
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