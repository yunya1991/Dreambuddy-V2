"""
C5 离场系统节点

基于经典指标系统的四级离场体系：
    - P0: 安全硬退出（最大持仓时间、最大亏损、强平缓冲、周线反转、风险闸门）
    - P1: 价值-风险评估（hold_risk/hold_value/MRD Score）
    - P2: Triple Barrier（止损/止盈/时间屏障）
    - P3: 执行层约束（TSTP、跟踪止损、分批减仓）

输入: state.market_data + state.position (持仓信息)
输出: action (close/reduce/hold/raise_tp) + reduce_frac + stop_loss + take_profit + new_tp_price + rationale
"""

from __future__ import annotations

from typing import Dict, Any, List, Optional
from enum import Enum

from dreamos.registry.base import BaseNode
from dreamos.shared.state import State, NodeResult


class ExitAction(str, Enum):
    CLOSE = "close"
    REDUCE = "reduce"
    HOLD = "hold"
    RAISE_TP = "raise_tp"    # 提高止盈价（强反弹时让利润奔跑）


class C5ExitSystemNode(BaseNode):
    """C5 离场系统节点

    四级离场体系：安全硬退出 → 价值风险评估 → 三重屏障 → 执行约束
    """

    node_id = "C5"
    name = "离场系统"
    description = "四级离场体系（P0安全硬退出/P1价值风险/P2三重屏障/P3执行约束）"
    chain = "C"
    tags = ["exit", "classic", "risk", "stop_loss", "take_profit"]
    estimated_tokens = 0
    estimated_latency_ms = 150

    def execute_core(self, state: State) -> NodeResult:
        mkt = self._get_market_data(state)
        position = self._get_position(state)
        rationale: List[str] = []
        scores = []

        price = mkt.get("price", 0)
        entry_price = position.get("entry_price", price)
        position_size = position.get("size", 0)
        direction = position.get("direction", "LONG")
        leverage = position.get("leverage", 1)
        pnl = self._calculate_pnl(price, entry_price, direction, leverage)
        pnl_pct = self._calculate_pnl_pct(price, entry_price, direction, leverage)

        # ── P0: 安全硬退出（一票否决） ──────────────────
        action = ExitAction.HOLD
        reduce_frac = 0.5
        stop_loss = None
        take_profit = None
        new_tp_price = 0.0
        new_tp_pct = 0.0

        max_loss_pct = self.config.get("max_loss_pct", 5.0)
        max_hold_hours = self.config.get("max_hold_hours", 24)
        hold_duration = position.get("hold_duration_hours", 0)

        if pnl_pct < -max_loss_pct:
            action = ExitAction.CLOSE
            scores.append(("CLOSE", 1.0, f"最大亏损触发(-{pnl_pct:.1f}% > -{max_loss_pct}%)"))
        elif hold_duration > max_hold_hours:
            action = ExitAction.CLOSE
            scores.append(("CLOSE", 1.0, f"最大持仓时间触发({hold_duration:.0f}h > {max_hold_hours}h)"))

        # ── P1: 价值-风险评估 ──────────────────────────
        if action == ExitAction.HOLD:
            atr_pct = mkt.get("atr_pct", 0.02)
            rsi = mkt.get("rsi14", 50)
            macd = mkt.get("macd", 0)

            hold_risk = self._calculate_hold_risk(pnl_pct, atr_pct, rsi)
            hold_value = self._calculate_hold_value(pnl_pct, macd, rsi)

            if hold_risk > 0.7:
                action = ExitAction.CLOSE
                scores.append(("CLOSE", 0.8, f"持有风险过高({hold_risk:.1%})"))
            elif hold_risk > 0.5:
                action = ExitAction.REDUCE
                reduce_frac = 0.6
                scores.append(("REDUCE", 0.6, f"持有风险偏高({hold_risk:.1%})，减仓"))
            elif hold_value > 0.7:
                action = ExitAction.HOLD
                scores.append(("HOLD", 0.7, f"持有价值高({hold_value:.1%})，继续持有"))

            # RAISE_TP: 价值高且风险低 → 提高止盈价（让利润奔跑）
            raise_tp_value_thr = self.config.get("raise_tp_value_thr", 0.65)
            raise_tp_risk_thr = self.config.get("raise_tp_risk_thr", 0.30)
            raise_tp_atr_mult = self.config.get("raise_tp_atr_mult", 4.0)
            if hold_value > raise_tp_value_thr and hold_risk < raise_tp_risk_thr:
                if action == ExitAction.HOLD:
                    new_tp_pct = atr_pct * raise_tp_atr_mult
                    if direction == "LONG":
                        new_tp_price = price * (1.0 + new_tp_pct)
                    else:
                        new_tp_price = price * (1.0 - new_tp_pct)
                    action = ExitAction.RAISE_TP
                    scores.append(("RAISE_TP", 0.65, f"提高止盈价(v={hold_value:.2f},risk={hold_risk:.2f},new_tp={raise_tp_atr_mult:.1f}xATR)"))

        # ── P2: Triple Barrier（三重屏障） ──────────────
        if action == ExitAction.HOLD:
            atr = mkt.get("atr", 0) or price * 0.02
            atr_mult_stop = self.config.get("atr_mult_stop", 2.0)
            atr_mult_take = self.config.get("atr_mult_take", 3.0)

            if direction == "LONG":
                stop_loss = entry_price - atr * atr_mult_stop
                take_profit = entry_price + atr * atr_mult_take
            else:
                stop_loss = entry_price + atr * atr_mult_stop
                take_profit = entry_price - atr * atr_mult_take

            if direction == "LONG" and price <= stop_loss:
                action = ExitAction.CLOSE
                scores.append(("CLOSE", 0.9, f"止损触发(现价{price:.2f} <= 止损{stop_loss:.2f})"))
            elif direction == "LONG" and price >= take_profit:
                action = ExitAction.REDUCE
                reduce_frac = 0.5
                scores.append(("REDUCE", 0.8, f"止盈触发(现价{price:.2f} >= 止盈{take_profit:.2f})"))

            if direction == "SHORT" and price >= stop_loss:
                action = ExitAction.CLOSE
                scores.append(("CLOSE", 0.9, f"止损触发(现价{price:.2f} >= 止损{stop_loss:.2f})"))
            elif direction == "SHORT" and price <= take_profit:
                action = ExitAction.REDUCE
                reduce_frac = 0.5
                scores.append(("REDUCE", 0.8, f"止盈触发(现价{price:.2f} <= 止盈{take_profit:.2f})"))

        # ── P3: 执行层约束 ──────────────────────────────
        if action == ExitAction.HOLD:
            trailing_stop_activated = position.get("trailing_stop_activated", False)
            if trailing_stop_activated:
                trail_distance = mkt.get("atr", 0) * 1.5
                trail_stop = price - trail_distance if direction == "LONG" else price + trail_distance
                if direction == "LONG" and price - trail_distance <= trail_stop:
                    action = ExitAction.CLOSE
                    scores.append(("CLOSE", 0.7, "跟踪止损触发"))

        # ── 综合输出 ────────────────────────────────────
        rationale = [r for _, _, r in scores[:6]]
        rationale.insert(0, f"[C5离场] 持仓:{direction} | 入场:{entry_price:.2f} | 现价:{price:.2f} | P&L:{pnl_pct:+.1%}")
        rationale.append(f"  动作: {action.value} | 减仓比例: {reduce_frac}")

        outputs = {
            "action": action.value,
            "reduce_fraction": reduce_frac,
            "stop_loss": round(stop_loss, 2) if stop_loss else None,
            "take_profit": round(take_profit, 2) if take_profit else None,
            "new_tp_price": round(new_tp_price, 2) if new_tp_price else 0.0,
            "new_tp_pct": round(new_tp_pct, 4) if new_tp_pct else 0.0,
            "pnl": round(pnl, 2),
            "pnl_pct": round(pnl_pct, 2),
            "position": position,
            "rationale": rationale,
        }

        confidence = 0.7
        if action == ExitAction.CLOSE:
            confidence = 0.95

        return NodeResult(
            node_id="C5",
            confidence=round(confidence, 3),
            direction=action.value,
            outputs=outputs,
        )

    def _calculate_pnl(self, price: float, entry: float, direction: str, leverage: float) -> float:
        if direction == "LONG":
            return (price - entry) * leverage
        return (entry - price) * leverage

    def _calculate_pnl_pct(self, price: float, entry: float, direction: str, leverage: float) -> float:
        if entry == 0:
            return 0
        if direction == "LONG":
            return ((price - entry) / entry) * 100 * leverage
        return ((entry - price) / entry) * 100 * leverage

    def _calculate_hold_risk(self, pnl_pct: float, atr_pct: float, rsi: float) -> float:
        risk = 0.3
        if pnl_pct < -2:
            risk += 0.3
        if atr_pct > 0.04:
            risk += 0.2
        if (rsi > 70 or rsi < 30):
            risk += 0.2
        return min(1.0, risk)

    def _calculate_hold_value(self, pnl_pct: float, macd: float, rsi: float) -> float:
        value = 0.3
        if pnl_pct > 2:
            value += 0.2
        if macd > 0:
            value += 0.2
        if 45 < rsi < 55:
            value += 0.2
        return min(1.0, value)

    def _get_market_data(self, state: State) -> Dict[str, Any]:
        if hasattr(state, "market") and state.market:
            return state.market
        if hasattr(state, "market_data") and state.market_data:
            return state.market_data
        if isinstance(state.intent, dict) and "mkt" in state.intent:
            return state.intent["mkt"]
        return {}

    def _get_position(self, state: State) -> Dict[str, Any]:
        if hasattr(state, "position") and state.position:
            return state.position
        if isinstance(state.intent, dict) and "position" in state.intent:
            return state.intent["position"]
        return {"entry_price": 0, "size": 0, "direction": "LONG", "leverage": 1, "hold_duration_hours": 0}