"""
F3 情绪分析节点

市场情绪分析：
    - 恐惧贪婪指数（FGI）
    - 多空持仓比
    - 资金费率情绪
    - 社交媒体情绪
"""

from __future__ import annotations

from typing import Dict, Any, List

from dreamos.registry.base import BaseNode
from dreamos.shared.state import State, NodeResult


class F3SentimentNode(BaseNode):
    """F3 情绪分析节点

    多维度市场情绪综合分析。
    """

    node_id = "F3"
    name = "情绪分析"
    description = "市场情绪分析（FGI/多空比/社交情绪）"
    chain = "F"
    tags = ["fundamental", "sentiment", "fgi"]
    estimated_tokens = 0
    estimated_latency_ms = 100

    def execute_core(self, state: State) -> NodeResult:
        mkt = self._get_market_data(state)
        rationale: List[str] = []
        signals = []

        # ── 1. 恐惧贪婪指数 FGI ────────────
        fgi = mkt.get("fgi", 50)
        fgi_class = self._fgi_class(fgi)
        if fgi < 25:
            signals.append(("LONG", 0.30, f"FGI={fgi}（极度恐惧），逆向买入机会"))
        elif fgi > 75:
            signals.append(("SHORT", 0.30, f"FGI={fgi}（极度贪婪），逆向卖出信号"))
        elif fgi < 40:
            signals.append(("LONG", 0.15, f"FGI={fgi}（恐惧），偏多"))
        elif fgi > 60:
            signals.append(("SHORT", 0.15, f"FGI={fgi}（贪婪），偏空"))
        else:
            signals.append(("HOLD", 0.05, f"FGI={fgi}（中性）"))

        # ── 2. 多空持仓比 ─────────────────
        long_short_ratio = mkt.get("long_short_ratio", 1.0)
        if long_short_ratio > 1.5:
            signals.append(("SHORT", 0.20, f"多空比 {long_short_ratio:.2f}，多头拥挤，反向做空"))
        elif long_short_ratio < 0.7:
            signals.append(("LONG", 0.20, f"多空比 {long_short_ratio:.2f}，空头拥挤，反向做多"))
        elif long_short_ratio > 1.2:
            signals.append(("SHORT", 0.08, f"多空比 {long_short_ratio:.2f}，偏多"))
        elif long_short_ratio < 0.9:
            signals.append(("LONG", 0.08, f"多空比 {long_short_ratio:.2f}，偏空"))

        # ── 3. 社交情绪 ──────────────────
        social_sentiment = mkt.get("social_sentiment", 0)  # -1 到 1
        if social_sentiment > 0.3:
            signals.append(("LONG", 0.10, f"社媒情绪偏多（{social_sentiment:+.2f}）"))
        elif social_sentiment < -0.3:
            signals.append(("SHORT", 0.10, f"社媒情绪偏空（{social_sentiment:+.2f}）"))

        # ── 4. 波动率情绪 ─────────────────
        atr_pct = mkt.get("atr_pct", 0.02)
        if atr_pct > 0.05:
            signals.append(("HOLD", 0.10, f"高波动（ATR {atr_pct:.1%}），情绪极端，建议观望"))

        # ── 综合 ──────────────────────────
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

        rationale.append("[F3情绪] 市场情绪分析")
        rationale.append(f"  FGI: {fgi} ({fgi_class}) | 多空比: {long_short_ratio:.2f}")
        if social_sentiment:
            rationale.append(f"  社媒情绪: {social_sentiment:+.2f} | ATR: {atr_pct:.1%}")
        for _, _, r in signals[:4]:
            rationale.append(f"  • {r}")
        rationale.append(f"  综合: {direction} | 置信度 {confidence:.1%}")

        return NodeResult(
            node_id="F3",
            confidence=round(confidence, 3),
            direction=direction,
            outputs={
                "fgi": fgi,
                "fgi_class": fgi_class,
                "long_short_ratio": long_short_ratio,
                "social_sentiment": social_sentiment,
                "atr_pct": atr_pct,
                "rationale": rationale,
            },
        )

    def _fgi_class(self, fgi: float) -> str:
        if fgi < 25:
            return "极度恐惧"
        elif fgi < 45:
            return "恐惧"
        elif fgi < 55:
            return "中性"
        elif fgi < 75:
            return "贪婪"
        else:
            return "极度贪婪"

    def _get_market_data(self, state: State) -> Dict[str, Any]:
        if hasattr(state, "market") and state.market:
            return state.market
        if hasattr(state, "market_data") and state.market_data:
            return state.market_data
        if isinstance(state.intent, dict) and "mkt" in state.intent:
            return state.intent["mkt"]
        return {}
