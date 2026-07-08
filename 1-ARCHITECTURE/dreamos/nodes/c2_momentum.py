"""
C2 动量指标节点 — 多周期动量分析
"""

from __future__ import annotations

from typing import Dict, Any, List

from dreamos.registry.base import BaseNode
from dreamos.shared.state import State, NodeResult


class C2MomentumNode(BaseNode):
    """C2 动量指标节点

    多周期动量综合分析:
        - RSI 动量
        - MACD 动量
        - KDJ 动量
        - 价格动量因子
    """

    node_id = "C2"
    name = "动量分析"
    description = "多周期动量综合分析（RSI/MACD/KDJ/价格动量）"
    chain = "C"
    tags = ["momentum", "technical", "indicator"]
    estimated_tokens = 0
    estimated_latency_ms = 80

    def execute_core(self, state: State) -> NodeResult:
        mkt = self._get_market_data(state)
        rationale: List[str] = []
        signals = []

        price = mkt.get("price", 0)
        rsi = mkt.get("rsi14", 50)
        macd = mkt.get("macd", 0)
        macd_signal = mkt.get("macd_signal", 0)
        kdj_k = mkt.get("kdj_k", 50)
        kdj_d = mkt.get("kdj_d", 50)
        change_24h = mkt.get("change_24h", 0)
        change_4h = mkt.get("change_4h", 0)
        change_1h = mkt.get("change_1h", 0)

        # RSI 动量
        rsi_signal, rsi_weight = self._analyze_rsi(rsi)
        if rsi_signal:
            signals.append((rsi_signal, rsi_weight, f"RSI动量: {rsi_signal} ({rsi:.1f})"))

        # MACD 动量
        macd_signal_dir, macd_weight = self._analyze_macd(macd, macd_signal)
        if macd_signal_dir:
            signals.append((macd_signal_dir, macd_weight, f"MACD动量: {macd_signal_dir}"))

        # KDJ 动量
        kdj_signal_dir, kdj_weight = self._analyze_kdj(kdj_k, kdj_d)
        if kdj_signal_dir:
            signals.append((kdj_signal_dir, kdj_weight, f"KDJ动量: {kdj_signal_dir}"))

        # 价格动量因子
        price_signal_dir, price_weight = self._analyze_price_momentum(change_24h, change_4h, change_1h)
        if price_signal_dir:
            signals.append((price_signal_dir, price_weight, f"价格动量: {price_signal_dir}"))

        long_score = sum(w for d, w, _ in signals if d == "LONG")
        short_score = sum(w for d, w, _ in signals if d == "SHORT")
        total = long_score + short_score

        if total == 0:
            direction = "HOLD"
            confidence = 0.35
        elif long_score > short_score:
            direction = "LONG"
            confidence = long_score / max(total, 0.01)
        else:
            direction = "SHORT"
            confidence = short_score / max(total, 0.01)

        confidence = min(max(confidence, 0.25), 0.85)

        rationale.append(f"[C2动量] 动量分析")
        for _, _, r in signals:
            rationale.append(f"  • {r}")
        rationale.append(f"  综合: {direction} | 置信度 {confidence:.1%}")

        return NodeResult(
            node_id="C2",
            confidence=round(confidence, 3),
            direction=direction,
            outputs={
                "rationale": rationale,
                "signals": signals,
                "rsi": rsi,
                "macd": macd,
                "macd_signal": macd_signal,
                "kdj_k": kdj_k,
                "kdj_d": kdj_d,
                "momentum_score": round(long_score - short_score, 3),
            },
        )

    def _analyze_rsi(self, rsi: float) -> tuple:
        if rsi < 30:
            return "LONG", 0.25
        elif rsi > 70:
            return "SHORT", 0.25
        elif rsi < 40:
            return "LONG", 0.10
        elif rsi > 60:
            return "SHORT", 0.10
        return "", 0

    def _analyze_macd(self, macd: float, signal: float) -> tuple:
        diff = macd - signal
        if diff > 0 and macd > 0:
            return "LONG", 0.25
        elif diff < 0 and macd < 0:
            return "SHORT", 0.25
        elif diff > 0:
            return "LONG", 0.12
        elif diff < 0:
            return "SHORT", 0.12
        return "", 0

    def _analyze_kdj(self, k: float, d: float) -> tuple:
        if k > 80 and d > 80:
            return "SHORT", 0.20
        elif k < 20 and d < 20:
            return "LONG", 0.20
        elif k > d and k > 50:
            return "LONG", 0.10
        elif k < d and k < 50:
            return "SHORT", 0.10
        return "", 0

    def _analyze_price_momentum(self, ch24: float, ch4h: float, ch1h: float) -> tuple:
        momentum = ch24 * 0.5 + ch4h * 0.3 + ch1h * 0.2

        if momentum > 0.02:
            return "LONG", 0.30
        elif momentum < -0.02:
            return "SHORT", 0.30
        elif momentum > 0:
            return "LONG", 0.15
        elif momentum < 0:
            return "SHORT", 0.15
        return "", 0

    def _get_market_data(self, state: State) -> Dict[str, Any]:
        if hasattr(state, "market") and state.market:
            return state.market
        if hasattr(state, "market_data") and state.market_data:
            return state.market_data
        if isinstance(state.intent, dict) and "mkt" in state.intent:
            return state.intent["mkt"]
        return {}