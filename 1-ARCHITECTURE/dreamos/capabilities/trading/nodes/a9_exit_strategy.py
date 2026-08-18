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

        # 持仓 K 线数（从 state.cycle_id 推断）
        bars_held = self._get_bars_held(state)

        # 时间衰减因子: 0-20 根=1.5x, 20-50 根线性衰减到 1.0x, 50+=1.0x
        if bars_held <= 20:
            time_factor = 1.5
        elif bars_held <= 50:
            time_factor = 1.5 - (bars_held - 20) * (0.5 / 30)
        else:
            time_factor = 1.0

        # 市场状态因子：震荡市更宽（1.5x），趋势市更紧（1.0x）
        regime = self._detect_regime(mkt, atr_pct)
        regime_factor = 1.5 if regime == "ranging" else 1.0

        # 币种波动率因子：以 BTC 为基准
        symbol = position.get("symbol", mkt.get("symbol", "BTC"))
        symbol_vol_factor = self._calc_symbol_vol_factor(symbol, atr_pct)

        # 最终复合因子 = 时间 × 市场状态 × 币种波动率
        sl_factor = time_factor * regime_factor * symbol_vol_factor

        exit_decision = "HOLD"
        exit_reason = ""
        exit_price = price

        exit_checks = [
            self._check_atr_stop(direction, price, entry_price, stop_loss, atr_pct, bars_held, sl_factor),
            self._check_moving_tp(direction, price, entry_price, take_profit, atr_pct, bars_held),
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

    def _check_atr_stop(self, direction: str, price: float, entry: float,
                        sl: float, atr_pct: float,
                        bars_held: int = 0, sl_factor: float = 1.0) -> tuple:
        """ATR 止损检查 — 时间衰减 × 市场状态复合因子

        sl_factor = time_factor × regime_factor
        前 20 根: 放宽止损范围
        20 根后: 收紧 + 移动止损保护利润
        """
        if sl == 0:
            return "HOLD", "", price

        # 前 20 根 K 线：用复合因子放宽止损
        if bars_held <= 20:
            sl_distance = abs(entry - sl) * sl_factor if entry != sl else atr_pct * entry * sl_factor
            if direction == "LONG":
                sl = entry - sl_distance
            else:
                sl = entry + sl_distance

        # 20 根后：移动止损保护利润
        if bars_held > 20:
            if direction == "LONG":
                profit_pct = (price - entry) / entry if entry > 0 else 0
                if profit_pct > 0:
                    trail_stop = entry * (1 + profit_pct * 0.5)
                    sl = max(sl, trail_stop)
            else:
                profit_pct = (entry - price) / entry if entry > 0 else 0
                if profit_pct > 0:
                    trail_stop = entry * (1 - profit_pct * 0.5)
                    sl = min(sl, trail_stop)

        if direction == "LONG":
            if price <= sl:
                return "EXIT", f"ATR止损触发: 现价${price:.4f} ≤ 止损${sl:.4f} (持仓{bars_held}根, factor={sl_factor:.2f})", sl
        else:
            if price >= sl:
                return "EXIT", f"ATR止损触发: 现价${price:.4f} ≥ 止损${sl:.4f} (持仓{bars_held}根, factor={sl_factor:.2f})", sl

        return "HOLD", "", price

    def _check_moving_tp(self, direction: str, price: float, entry: float,
                         tp: float, atr_pct: float, bars_held: int = 0) -> tuple:
        """移动止盈检查 — 20 根 K 线后激活"""
        if tp == 0:
            return "HOLD", "", price

        trail_pct = atr_pct * 1.0
        profit_pct = abs(price - entry) / entry if entry > 0 else 0

        # 20 根后降低触发门槛（从 1.5x ATR 降到 1.0x ATR）
        activation_threshold = atr_pct * (1.5 if bars_held <= 20 else 1.0)

        if profit_pct >= activation_threshold:
            if direction == "LONG":
                trail_price = price * (1 - trail_pct)
                if price <= trail_price:
                    return "EXIT", f"移动止盈触发: 现价${price:.4f} ≤ 追踪价${trail_price:.4f} (持仓{bars_held}根)", trail_price
            else:
                trail_price = price * (1 + trail_pct)
                if price >= trail_price:
                    return "EXIT", f"移动止盈触发: 现价${price:.4f} ≥ 追踪价${trail_price:.4f} (持仓{bars_held}根)", trail_price

        if direction == "LONG":
            if price >= tp:
                return "EXIT", f"止盈触发: 现价${price:.4f} ≥ 止盈${tp:.4f}", tp
        else:
            if price <= tp:
                return "EXIT", f"止盈触发: 现价${price:.4f} ≤ 止盈${tp:.4f}", tp

        return "HOLD", "", price

    def _get_bars_held(self, state: State) -> int:
        """从 state.cycle_id 推断持仓 K 线数"""
        cycle_id = getattr(state, "cycle_id", "")
        if cycle_id:
            import re
            match = re.search(r"-(\d+)$", cycle_id)
            if match:
                return int(match.group(1))

        # 回退：从 state.inputs.context 获取
        ctx = state.inputs.get("context", {}) if hasattr(state, "inputs") else {}
        bars = ctx.get("bars_held", 0)
        return max(0, bars)

    def _detect_regime(self, mkt: Dict[str, Any], atr_pct: float) -> str:
        """判断市场状态：震荡市 vs 趋势市

        震荡市: EMA 纠缠，价格在均线间反复
        趋势市: EMA 多头/空头排列
        """
        try:
            from dreamos.core.sense.scenario_classifier import ScenarioClassifier
            classifier = ScenarioClassifier()
            scenario = classifier.classify(mkt)
            if scenario.trend in ("BULL", "BEAR"):
                return "trend"
            return "ranging"
        except Exception:
            # 回退：ATR% 阈值
            if atr_pct > 0.03:
                return "trend"
            return "ranging"

    _btc_atr_cache: float = 0.0

    def _calc_symbol_vol_factor(self, symbol: str, atr_pct: float) -> float:
        """计算币种波动率因子（以 BTC 为基准）

        回测中通过缓存 BTC 的 ATR% 作为基准，比较各币种波动率。
        """
        sym = symbol.upper().strip()

        # BTC 自身是基准
        if sym in ("BTC", "BTCUSDT"):
            self._btc_atr_cache = atr_pct  # 缓存 BTC ATR%
            return 1.0

        # 有 BTC 缓存时用动态比值
        if self._btc_atr_cache > 0:
            ratio = atr_pct / self._btc_atr_cache
            if ratio <= 1.0:
                return 0.8
            elif ratio <= 2.0:
                return 1.0
            elif ratio <= 3.0:
                return 1.2
            else:
                return 1.3

        # 无 BTC 缓存时用硬编码回退
        HIGH_VOL = {"SOL", "AVAX", "MATIC", "DOT", "LINK", "DOGE", "SHIB", "OP", "ARB"}
        if sym in HIGH_VOL:
            return 1.2
        return 1.0

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