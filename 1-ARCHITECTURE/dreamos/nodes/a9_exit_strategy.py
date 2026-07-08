"""
A9 离场决策节点 — 四层离场决策链
"""

from __future__ import annotations

from typing import Dict, Any, List

from dreamos.registry.base import BaseNode
from dreamos.shared.state import State, NodeResult


class A9ExitStrategyNode(BaseNode):
    """A9 离场决策节点

    四层离场决策链:
        1. ATR止损
        2. 移动止盈
        3. 时间止损
        4. 信号反转止损

    输入: 当前持仓信息 + 市场状态
    输出: exit_decision + exit_reason + exit_price
    """

    node_id = "A9"
    name = "离场决策"
    description = "四层离场决策链（ATR止损/移动止盈/时间止损/信号反转）"
    chain = "A"
    tags = ["exit", "stop-loss", "take-profit"]
    estimated_tokens = 0
    estimated_latency_ms = 70

    def execute_core(self, state: State) -> NodeResult:
        mkt = self._get_market_data(state)
        rationale: List[str] = []

        price = mkt.get("price", 0)
        atr_pct = mkt.get("atr_pct", 0.02)

        a5_result = state.get_result("A5")
        position = a5_result.outputs.get("trade_order", {}) if a5_result else {}

        if not position:
            rationale.append("[A9离场] 无持仓信息，跳过离场分析")
            return NodeResult(
                node_id="A9",
                confidence=0.5,
                direction="HOLD",
                outputs={
                    "rationale": rationale,
                    "exit_decision": "HOLD",
                },
            )

        entry_price = position.get("entry_price", price)
        direction = position.get("action", "LONG")
        stop_loss = position.get("stop_loss", 0)
        take_profit = position.get("take_profit", 0)
        leverage = position.get("leverage", 1)

        exit_decision = "HOLD"
        exit_reason = ""
        exit_price = price

        exit_checks = [
            self._check_atr_stop(direction, price, entry_price, stop_loss, atr_pct),
            self._check_moving_tp(direction, price, entry_price, take_profit, atr_pct),
            self._check_signal_reversal(state, direction),
            self._check_time_exit(state),
        ]

        for decision, reason, price_level in exit_checks:
            if decision != "HOLD":
                exit_decision = decision
                exit_reason = reason
                exit_price = price_level
                break

        if exit_decision != "HOLD":
            rationale.append(f"[A9离场] {exit_decision} | {exit_reason}")
            rationale.append(f"  离场价: ${exit_price:.4f}")
            rationale.append(f"  当前价: ${price:.4f}")
            pnl_pct = self._calculate_pnl(direction, entry_price, exit_price, leverage)
            rationale.append(f"  预估盈亏: {pnl_pct:+.2f}%")
        else:
            rationale.append("[A9离场] 无需离场，继续持有")
            current_pnl = self._calculate_pnl(direction, entry_price, price, leverage)
            rationale.append(f"  当前盈亏: {current_pnl:+.2f}%")

        return NodeResult(
            node_id="A9",
            confidence=0.6,
            direction=exit_decision,
            outputs={
                "rationale": rationale,
                "exit_decision": exit_decision,
                "exit_reason": exit_reason,
                "exit_price": exit_price,
                "current_price": price,
                "entry_price": entry_price,
                "direction": direction,
                "leverage": leverage,
            },
        )

    def _check_atr_stop(self, direction: str, price: float, entry: float, sl: float, atr_pct: float) -> tuple:
        if sl == 0:
            return "HOLD", "", price

        if direction == "LONG":
            if price <= sl:
                return "EXIT", f"ATR止损触发: 现价${price:.4f} ≤ 止损${sl:.4f}", sl
        else:
            if price >= sl:
                return "EXIT", f"ATR止损触发: 现价${price:.4f} ≥ 止损${sl:.4f}", sl

        return "HOLD", "", price

    def _check_moving_tp(self, direction: str, price: float, entry: float, tp: float, atr_pct: float) -> tuple:
        if tp == 0:
            return "HOLD", "", price

        trail_pct = atr_pct * 1.0
        profit_pct = abs(price - entry) / entry if entry > 0 else 0

        if profit_pct >= atr_pct * 1.5:
            if direction == "LONG":
                trail_price = price * (1 - trail_pct)
                if price <= trail_price:
                    return "EXIT", f"移动止盈触发: 现价${price:.4f} ≤ 追踪价${trail_price:.4f}", trail_price
            else:
                trail_price = price * (1 + trail_pct)
                if price >= trail_price:
                    return "EXIT", f"移动止盈触发: 现价${price:.4f} ≥ 追踪价${trail_price:.4f}", trail_price

        if direction == "LONG":
            if price >= tp:
                return "EXIT", f"止盈触发: 现价${price:.4f} ≥ 止盈${tp:.4f}", tp
        else:
            if price <= tp:
                return "EXIT", f"止盈触发: 现价${price:.4f} ≤ 止盈${tp:.4f}", tp

        return "HOLD", "", price

    def _check_signal_reversal(self, state: State, direction: str) -> tuple:
        results = state.results if state.results else {}

        for node_id, result in results.items():
            if hasattr(result, "direction") and result.direction:
                if result.direction != "HOLD" and result.direction != direction:
                    conf = getattr(result, "confidence", 0)
                    if conf >= 0.5:
                        return "EXIT", f"信号反转: {node_id} 给出 {result.direction} (置信度{conf:.0%})", 0

        return "HOLD", "", 0

    def _check_time_exit(self, state: State) -> tuple:
        cycle_id = getattr(state, "cycle_id", "")
        if cycle_id:
            import re
            match = re.search(r"-(\d+)$", cycle_id)
            if match:
                cycle_num = int(match.group(1))
                if cycle_num >= 24:
                    return "EXIT", "时间止损: 持仓超过24个周期", 0

        return "HOLD", "", 0

    def _calculate_pnl(self, direction: str, entry: float, exit: float, leverage: float) -> float:
        if entry == 0:
            return 0.0

        if direction == "LONG":
            return (exit - entry) / entry * leverage * 100
        else:
            return (entry - exit) / entry * leverage * 100

    def _get_market_data(self, state: State) -> Dict[str, Any]:
        if hasattr(state, "market") and state.market:
            return state.market
        if hasattr(state, "market_data") and state.market_data:
            return state.market_data
        if isinstance(state.intent, dict) and "mkt" in state.intent:
            return state.intent["mkt"]
        return {}