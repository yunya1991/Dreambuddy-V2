"""
A6 情报监控节点 — 市场状态雷达
"""

from __future__ import annotations

from typing import Dict, Any, List

from dreamos.registry.base import BaseNode
from dreamos.shared.state import State, NodeResult


class A6RegimeMonitorNode(BaseNode):
    """A6 情报监控节点

    监控市场状态（regime/波动率/趋势强度），为策略调整提供依据。
    输出: market_regime + volatility_state + trend_strength
    """

    node_id = "A6"
    name = "情报监控"
    description = "市场状态雷达（regime/波动率/趋势强度）"
    chain = "A"
    tags = ["regime", "monitor", "intelligence"]
    estimated_tokens = 0
    estimated_latency_ms = 80

    REGIME_THRESHOLDS = {
        "TREND": 0.6,
        "RANGE": 0.4,
    }

    VOLATILITY_THRESHOLDS = {
        "HIGH": 0.04,
        "NORMAL": 0.02,
        "LOW": 0.01,
    }

    def execute_core(self, state: State) -> NodeResult:
        mkt = self._get_market_data(state)
        rationale: List[str] = []

        price = mkt.get("price", 0)
        atr_pct = mkt.get("atr_pct", 0.02)
        change_24h = mkt.get("change_24h", 0)
        vol_ratio = mkt.get("vol_ratio", 1.0)
        ema20 = mkt.get("ema20", price)
        ema50 = mkt.get("ema50", price)
        ema200 = mkt.get("ema200", price)

        trend_score = self._calculate_trend_score(price, ema20, ema50, ema200, change_24h)
        regime = self._determine_regime(trend_score)

        vol_state = self._determine_volatility(atr_pct)

        momentum = self._calculate_momentum(mkt)

        volatility_rank = self._get_volatility_rank(mkt)

        regime_confidence = min(max(trend_score, 0.3), 0.95)

        rationale.append(f"[A6情报监控] 市场状态分析")
        rationale.append(f"  趋势得分: {trend_score:.1%}")
        rationale.append(f"  市场模式: {regime}")
        rationale.append(f"  波动状态: {vol_state} (ATR {atr_pct:.1%})")
        rationale.append(f"  动量: {momentum:+.2f}")
        rationale.append(f"  波动率分位: {volatility_rank:.0%}")

        return NodeResult(
            node_id="A6",
            confidence=round(regime_confidence, 3),
            direction="HOLD",
            outputs={
                "rationale": rationale,
                "regime": regime,
                "regime_confidence": round(regime_confidence, 3),
                "trend_score": round(trend_score, 3),
                "volatility_state": vol_state,
                "volatility_pct": round(atr_pct, 4),
                "momentum": round(momentum, 3),
                "volatility_rank": round(volatility_rank, 3),
                "vol_ratio": vol_ratio,
            },
        )

    def _calculate_trend_score(self, price: float, ema20: float, ema50: float, ema200: float, change_24h: float) -> float:
        score = 0.0

        if price > ema20 > ema50 > ema200:
            score += 0.4
        elif price < ema20 < ema50 < ema200:
            score += 0.4

        if ema20 > ema50:
            score += 0.2
        elif ema20 < ema50:
            score += 0.2

        score += abs(change_24h) * 0.3

        return min(max(score, 0), 1)

    def _determine_regime(self, trend_score: float) -> str:
        if trend_score >= self.REGIME_THRESHOLDS["TREND"]:
            return "TREND"
        elif trend_score <= self.REGIME_THRESHOLDS["RANGE"]:
            return "RANGE"
        else:
            return "TRANSITION"

    def _determine_volatility(self, atr_pct: float) -> str:
        if atr_pct >= self.VOLATILITY_THRESHOLDS["HIGH"]:
            return "HIGH"
        elif atr_pct >= self.VOLATILITY_THRESHOLDS["NORMAL"]:
            return "NORMAL"
        elif atr_pct >= self.VOLATILITY_THRESHOLDS["LOW"]:
            return "LOW"
        else:
            return "VERY_LOW"

    def _calculate_momentum(self, mkt: Dict) -> float:
        change_24h = mkt.get("change_24h", 0)
        change_4h = mkt.get("change_4h", 0)
        change_1h = mkt.get("change_1h", 0)

        momentum = change_24h * 0.5 + change_4h * 0.3 + change_1h * 0.2
        return momentum

    def _get_volatility_rank(self, mkt: Dict) -> float:
        atr_pct = mkt.get("atr_pct", 0.02)
        vol_20d_avg = mkt.get("vol_20d_avg", 0.02)

        if vol_20d_avg == 0:
            return 0.5

        ratio = atr_pct / vol_20d_avg
        return min(max(ratio, 0), 1)

    def _get_market_data(self, state: State) -> Dict[str, Any]:
        if hasattr(state, "market") and state.market:
            return state.market
        if hasattr(state, "market_data") and state.market_data:
            return state.market_data
        if isinstance(state.intent, dict) and "mkt" in state.intent:
            return state.intent["mkt"]
        return {}