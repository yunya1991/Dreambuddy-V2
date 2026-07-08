"""
C3 波动率分析节点 — 波动率周期与极值判定
"""

from __future__ import annotations

from typing import Dict, Any, List

from dreamos.registry.base import BaseNode
from dreamos.shared.state import State, NodeResult


class C3VolatilityNode(BaseNode):
    """C3 波动率分析节点

    波动率周期与极值判定:
        - ATR 波动率
        - Bollinger Bands 宽度
        - IV 百分位（模拟）
        - 波动率收缩/扩张识别
    """

    node_id = "C3"
    name = "波动率分析"
    description = "波动率周期与极值判定（ATR/布林带/IV百分位）"
    chain = "C"
    tags = ["volatility", "technical", "risk"]
    estimated_tokens = 0
    estimated_latency_ms = 80

    def execute_core(self, state: State) -> NodeResult:
        mkt = self._get_market_data(state)
        rationale: List[str] = []

        price = mkt.get("price", 0)
        atr_pct = mkt.get("atr_pct", 0.02)
        bb_width = mkt.get("bb_width", 0.02)
        iv_rank = mkt.get("iv_rank", 0.5)
        vol_20d_avg = mkt.get("vol_20d_avg", 0.02)
        change_24h = mkt.get("change_24h", 0)

        vol_state = self._get_vol_state(atr_pct)

        vol_regime = self._determine_vol_regime(atr_pct, vol_20d_avg)

        bb_signal = self._analyze_bb(bb_width)

        iv_signal = self._analyze_iv(iv_rank)

        signals = []
        if vol_regime == "EXPANDING":
            signals.append(("LONG" if change_24h > 0 else "SHORT", 0.25, f"波动率扩张"))
        elif vol_regime == "CONTRACTING":
            signals.append(("HOLD", 0.20, f"波动率收缩，方向不明"))
        else:
            signals.append(("HOLD", 0.10, f"波动率中性"))

        if bb_signal:
            signals.append(bb_signal)

        if iv_signal:
            signals.append(iv_signal)

        long_score = sum(w for d, w, _ in signals if d == "LONG")
        short_score = sum(w for d, w, _ in signals if d == "SHORT")
        hold_score = sum(w for d, w, _ in signals if d == "HOLD")
        total = long_score + short_score + hold_score

        if hold_score > 0.3:
            direction = "HOLD"
            confidence = hold_score
        elif long_score > short_score:
            direction = "LONG"
            confidence = long_score / max(long_score + short_score, 0.01)
        else:
            direction = "SHORT"
            confidence = short_score / max(long_score + short_score, 0.01)

        confidence = min(max(confidence, 0.25), 0.85)

        rationale.append(f"[C3波动率] 波动率分析")
        rationale.append(f"  波动率状态: {vol_state} (ATR {atr_pct:.1%})")
        rationale.append(f"  波动率模式: {vol_regime}")
        rationale.append(f"  布林带宽度: {bb_width:.1%}")
        rationale.append(f"  IV分位: {iv_rank:.0%}")
        for _, _, r in signals:
            rationale.append(f"  • {r}")
        rationale.append(f"  综合: {direction} | 置信度 {confidence:.1%}")

        return NodeResult(
            node_id="C3",
            confidence=round(confidence, 3),
            direction=direction,
            outputs={
                "rationale": rationale,
                "volatility_state": vol_state,
                "volatility_regime": vol_regime,
                "atr_pct": round(atr_pct, 4),
                "bb_width": round(bb_width, 4),
                "iv_rank": round(iv_rank, 3),
                "signals": signals,
            },
        )

    def _get_vol_state(self, atr_pct: float) -> str:
        if atr_pct >= 0.05:
            return "VERY_HIGH"
        elif atr_pct >= 0.03:
            return "HIGH"
        elif atr_pct >= 0.015:
            return "NORMAL"
        elif atr_pct >= 0.008:
            return "LOW"
        else:
            return "VERY_LOW"

    def _determine_vol_regime(self, atr_pct: float, vol_avg: float) -> str:
        if vol_avg == 0:
            return "NEUTRAL"

        ratio = atr_pct / vol_avg
        if ratio > 1.5:
            return "EXPANDING"
        elif ratio < 0.7:
            return "CONTRACTING"
        else:
            return "NEUTRAL"

    def _analyze_bb(self, bb_width: float) -> tuple:
        if bb_width > 0.06:
            return "HOLD", 0.15, f"布林带极度扩张，波动极端"
        elif bb_width < 0.015:
            return "HOLD", 0.20, f"布林带极度收缩，即将突破"
        elif bb_width > 0.04:
            return "HOLD", 0.10, f"布林带扩张"
        else:
            return "", 0, ""

    def _analyze_iv(self, iv_rank: float) -> tuple:
        if iv_rank > 0.8:
            return "HOLD", 0.15, f"IV高位({iv_rank:.0%})，期权溢价高"
        elif iv_rank < 0.2:
            return "HOLD", 0.15, f"IV低位({iv_rank:.0%})，期权便宜"
        return "", 0, ""

    def _get_market_data(self, state: State) -> Dict[str, Any]:
        if hasattr(state, "market") and state.market:
            return state.market
        if hasattr(state, "market_data") and state.market_data:
            return state.market_data
        if isinstance(state.intent, dict) and "mkt" in state.intent:
            return state.intent["mkt"]
        return {}