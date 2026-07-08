"""
F5 宏观环境节点 — 宏观经济状态分析
"""

from __future__ import annotations

from typing import Dict, Any, List

from dreamos.registry.base import BaseNode
from dreamos.shared.state import State, NodeResult


class F5MacroNode(BaseNode):
    """F5 宏观环境节点

    宏观经济状态分析（MVP 占位实现）:
        - 美元指数相关性
        - 美股相关性
        - 利率环境
        - 宏观风险偏好
    """

    node_id = "F5"
    name = "宏观环境"
    description = "宏观经济状态分析（美元指数/美股相关性/利率环境）"
    chain = "F"
    tags = ["fundamental", "macro", "economy"]
    estimated_tokens = 0
    estimated_latency_ms = 100

    def execute_core(self, state: State) -> NodeResult:
        mkt = self._get_market_data(state)
        rationale: List[str] = []
        signals = []

        dollar_index = mkt.get("dollar_index", 100)
        spx_correlation = mkt.get("spx_correlation", 0)
        rate_env = mkt.get("rate_env", "neutral")
        risk_appetite = mkt.get("risk_appetite", 0.5)
        crypto_correlation = mkt.get("crypto_correlation", 0)

        if dollar_index != 100:
            if dollar_index > 105:
                signals.append(("SHORT", 0.20, f"美元走强({dollar_index})，压制风险资产"))
            elif dollar_index < 95:
                signals.append(("LONG", 0.20, f"美元走弱({dollar_index})，利好风险资产"))

        if spx_correlation != 0:
            if spx_correlation > 0.6:
                signals.append(("HOLD", 0.15, f"与标普高相关({spx_correlation:.2f})，受美股影响大"))
            elif spx_correlation < -0.3:
                signals.append(("HOLD", 0.10, f"与标普负相关({spx_correlation:.2f})，避险属性"))

        if rate_env != "neutral":
            if rate_env == "rising":
                signals.append(("SHORT", 0.20, "利率上行周期，利空"))
            elif rate_env == "falling":
                signals.append(("LONG", 0.20, "利率下行周期，利好"))

        if risk_appetite != 0.5:
            if risk_appetite > 0.7:
                signals.append(("LONG", 0.15, f"风险偏好高({risk_appetite:.0%})"))
            elif risk_appetite < 0.3:
                signals.append(("SHORT", 0.15, f"风险偏好低({risk_appetite:.0%})"))

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

        rationale.append("[F5宏观] 宏观环境分析")
        for _, _, r in signals:
            rationale.append(f"  • {r}")
        rationale.append(f"  综合: {direction} | 置信度 {confidence:.1%}")

        return NodeResult(
            node_id="F5",
            confidence=round(confidence, 3),
            direction=direction,
            outputs={
                "rationale": rationale,
                "dollar_index": dollar_index,
                "spx_correlation": spx_correlation,
                "rate_env": rate_env,
                "risk_appetite": risk_appetite,
                "signals": signals,
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