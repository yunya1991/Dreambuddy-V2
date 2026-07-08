"""
A1 深度调研节点 — 发现主要矛盾

核心职责: 通过 Tavily + LLM 深度调研，调用 A0 矛盾论识别市场当前的主要矛盾。

A0 矛盾论内嵌关系:
    A1 = 发现主要矛盾（调用 A0 识别市场主要矛盾是什么）
    A2 = 辩证看待矛盾（调用 A0 分析矛盾的主次关系）
    A3 = 推演解决矛盾（调用 A0 围绕主要矛盾推演解决方案）

调研内容:
    - 多周期共振验证（日/4h/1h）
    - 关键支撑阻力位
    - 形态识别
    - 趋势强度评估
    - 调用 A0 做多维度矛盾识别

依赖 C1 技术扫描的结果，在此基础上做深化分析。
"""

from __future__ import annotations

from typing import Dict, Any, List

from dreamos.registry.base import BaseNode
from dreamos.shared.state import State, NodeResult


class A1DeepResearchNode(BaseNode):
    """A1 深度调研节点 — 发现主要矛盾

    通过多周期深度研究，调用 A0 矛盾论识别市场主要矛盾。
    """

    node_id = "A1"
    name = "深度研究"
    description = "多周期深度研究（共振验证/支撑阻力/形态识别）"
    chain = "A"
    tags = ["research", "deep-dive", "multi-timeframe"]
    estimated_tokens = 0
    estimated_latency_ms = 120

    def execute_core(self, state: State) -> NodeResult:
        mkt = self._get_market_data(state)
        rationale: List[str] = []

        price = mkt.get("price", 0)
        ch24 = mkt.get("change_24h", 0)
        ch4h = mkt.get("change_4h", 0)
        ch1h = mkt.get("change_1h", 0)
        ema20 = mkt.get("ema20", price)
        ema50 = mkt.get("ema50", price)
        ema200 = mkt.get("ema200", price)
        rsi = mkt.get("rsi14", 50)
        atr_pct = mkt.get("atr_pct", 0.02)
        vol_ratio = mkt.get("vol_ratio", 1.0)
        high_24h = mkt.get("high_24h", price * 1.05)
        low_24h = mkt.get("low_24h", price * 0.95)

        # ── 1. 多周期共振 ────────────────────
        tf_signals = []
        if ch24 > 0:
            tf_signals.append(("LONG", 0.35, "日线上行"))
        elif ch24 < 0:
            tf_signals.append(("SHORT", 0.35, "日线下行"))
        else:
            tf_signals.append(("HOLD", 0.1, "日线持平"))

        if ch4h > 0:
            tf_signals.append(("LONG", 0.30, "4h上行"))
        elif ch4h < 0:
            tf_signals.append(("SHORT", 0.30, "4h下行"))
        else:
            tf_signals.append(("HOLD", 0.1, "4h持平"))

        if ch1h > 0:
            tf_signals.append(("LONG", 0.20, "1h上行"))
        elif ch1h < 0:
            tf_signals.append(("SHORT", 0.20, "1h下行"))
        else:
            tf_signals.append(("HOLD", 0.1, "1h持平"))

        long_w = sum(w for d, w, _ in tf_signals if d == "LONG")
        short_w = sum(w for d, w, _ in tf_signals if d == "SHORT")

        # 共振强度
        resonance = abs(long_w - short_w)
        direction = "LONG" if long_w > short_w else "SHORT" if short_w > long_w else "HOLD"

        # ── 2. 关键位置 ──────────────────────
        # 距高点/低点位置
        range_total = high_24h - low_24h
        if range_total > 0:
            pos_in_range = (price - low_24h) / range_total
        else:
            pos_in_range = 0.5

        # 支撑/阻力
        support = min(ema20, ema50)
        resistance = max(ema20, ema50)
        near_support = price < support * 1.02 and price > support * 0.98
        near_resistance = price > resistance * 0.98 and price < resistance * 1.02

        # ── 3. 趋势强度 ──────────────────────
        # ADX 近似：用 ATR% 和 趋势持续度
        trend_strength = min(1.0, abs(ch24) / max(atr_pct, 0.01) * 0.1)

        # ── 综合置信度 ───────────────────────
        base_conf = resonance  # 共振度 0 - 0.85
        confidence = base_conf

        # 靠近支撑/阻力调整
        if near_support and direction == "LONG":
            confidence += 0.1  # 支撑位做多，加分
        elif near_resistance and direction == "SHORT":
            confidence += 0.1  # 阻力位做空，加分
        elif near_support and direction == "SHORT":
            confidence -= 0.05  # 支撑位做空，减分
        elif near_resistance and direction == "LONG":
            confidence -= 0.05  # 阻力位做多，减分

        # 趋势强度调整
        confidence = confidence * (0.7 + trend_strength * 0.3)
        confidence = min(max(confidence, 0.2), 0.92)

        rationale.append("[A1深度研究] 多周期研究")
        rationale.append(f"  日线: {ch24:+.2f}% | 4h: {ch4h:+.2f}% | 1h: {ch1h:+.2f}%")
        rationale.append(f"  周期共振: {resonance:.0%} → 方向 {direction}")
        rationale.append(f"  24h位置: {pos_in_range:.0%} (高{high_24h:.2f} / 低{low_24h:.2f})")
        rationale.append(f"  趋势强度: {trend_strength:.0%} | 综合置信: {confidence:.1%}")

        return NodeResult(
            node_id="A1",
            confidence=round(confidence, 3),
            direction=direction,
            outputs={
                "resonance": resonance,
                "trend_strength": trend_strength,
                "position_in_range": pos_in_range,
                "support": support,
                "resistance": resistance,
                "timeframe_signals": tf_signals,
                "rationale": rationale,
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
