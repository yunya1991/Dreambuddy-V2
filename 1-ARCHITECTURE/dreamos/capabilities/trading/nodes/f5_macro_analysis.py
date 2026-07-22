"""
F5 宏观分析节点

基于基本面分析系统的宏观分析能力：
    - 政策评分
    - 美元指数 (DXY)
    - 利率影响
    - 加密友好度
    - 宏观事件
    - 黄金相关性

输入: state.market_data 或 state.inputs["mkt"]
输出: direction / confidence / macro_score / policy_score / dxy / rationale
"""

from __future__ import annotations

from typing import Dict, Any, List

from dreamos.registry.base import BaseNode
from dreamos.shared.state import State, NodeResult


class F5MacroAnalysisNode(BaseNode):
    """F5 宏观分析节点

    基于宏观因素的分析，判断整体环境对加密资产的影响。
    """

    node_id = "F5"
    name = "宏观分析"
    description = "宏观分析（政策评分/DXY/利率/加密友好度/宏观事件/黄金相关性）"
    chain = "F"
    tags = ["macro", "fundamental", "policy", "dxy", "interest_rate"]
    estimated_tokens = 0
    estimated_latency_ms = 100

    def execute_core(self, state: State) -> NodeResult:
        mkt = self._get_market_data(state)
        rationale: List[str] = []
        scores = []

        # ── 1. 政策评分 ──────────────────────────────────
        policy_score = mkt.get("policy_score", 50)
        if policy_score > 60:
            scores.append(("LONG", 0.20, f"政策偏友好({policy_score:.0f})，流动性改善"))
        elif policy_score < 40:
            scores.append(("SHORT", 0.20, f"政策偏紧缩({policy_score:.0f})，流动性收紧"))

        # ── 2. 美元指数 (DXY) ────────────────────────────
        dxy_strength = mkt.get("dxy_strength", 50)
        dxy_change = mkt.get("dxy_change", 0)
        if dxy_strength < 45:
            scores.append(("LONG", 0.20, f"美元走弱(DXY={dxy_strength:.0f})，风险资产利好"))
        elif dxy_strength > 60:
            scores.append(("SHORT", 0.20, f"美元走强(DXY={dxy_strength:.0f})，风险资产承压"))

        # ── 3. 利率影响 ──────────────────────────────────
        rate_impact = mkt.get("rate_impact", 0)
        if rate_impact < -0.3:
            scores.append(("SHORT", 0.25, f"利率冲击({rate_impact:+.2f})，高利率压制估值"))
        elif rate_impact > 0.1:
            scores.append(("LONG", 0.15, f"利率利好({rate_impact:+.2f})，降息预期"))

        # ── 4. 加密友好度 ────────────────────────────────
        crypto_friendly_score = mkt.get("crypto_friendly_score", 50)
        if crypto_friendly_score > 70:
            scores.append(("LONG", 0.15, f"加密友好度高({crypto_friendly_score:.0f})"))
        elif crypto_friendly_score < 30:
            scores.append(("SHORT", 0.15, f"加密友好度低({crypto_friendly_score:.0f})"))

        # ── 5. 宏观事件 ──────────────────────────────────
        upcoming_events = mkt.get("upcoming_events_count", 0)
        event_severity = mkt.get("event_severity", "low")
        if upcoming_events > 3 and event_severity == "high":
            scores.append(("HOLD", 0.20, f"重大事件密集({upcoming_events}件)，不确定性上升"))

        # ── 6. 黄金相关性 ────────────────────────────────
        gold_correlation = mkt.get("gold_correlation", 0)
        if gold_correlation > 0.4:
            scores.append(("LONG", 0.10, f"与黄金相关性上升({gold_correlation:.2f})，避险属性显现"))

        # ── 7. 美股相关性 ────────────────────────────────
        spx_correlation = mkt.get("spx_correlation", 0)
        if spx_correlation > 0.6:
            scores.append(("HOLD", 0.10, f"与美股相关性高({spx_correlation:.2f})，风险联动"))

        # ── 综合计算 ────────────────────────────────────
        long_score = sum(w for d, w, _ in scores if d == "LONG")
        short_score = sum(w for d, w, _ in scores if d == "SHORT")
        hold_score = sum(w for d, w, _ in scores if d == "HOLD")
        total = long_score + short_score + hold_score

        if total == 0:
            direction = "HOLD"
            confidence = 0.3
        elif hold_score > long_score and hold_score > short_score:
            direction = "HOLD"
            confidence = hold_score / max(total, 0.01)
        elif long_score > short_score:
            direction = "LONG"
            confidence = long_score / max(total, 0.01)
        else:
            direction = "SHORT"
            confidence = short_score / max(total, 0.01)

        macro_score = long_score - short_score

        rationale = [r for _, _, r in scores[:6]]
        rationale.insert(0, f"[F5宏观分析] 宏观得分={macro_score:+.2f}")
        rationale.append(f"  方向: {direction} | 置信度: {confidence:.1%}")

        outputs = {
            "macro_score": round(macro_score, 3),
            "policy": {
                "score": policy_score,
            },
            "dxy": {
                "strength": dxy_strength,
                "change": dxy_change,
            },
            "rate_impact": rate_impact,
            "crypto_friendly": crypto_friendly_score,
            "events": {
                "count": upcoming_events,
                "severity": event_severity,
            },
            "correlations": {
                "gold": gold_correlation,
                "spx": spx_correlation,
            },
            "scores": {"long": round(long_score, 3), "short": round(short_score, 3), "hold": round(hold_score, 3)},
            "rationale": rationale,
        }

        return NodeResult(
            node_id="F5",
            confidence=round(confidence, 3),
            direction=direction,
            outputs=outputs,
        )

    def _get_market_data(self, state: State) -> Dict[str, Any]:
        if hasattr(state, "market") and state.market:
            return state.market
        if hasattr(state, "market_data") and state.market_data:
            return state.market_data
        if isinstance(state.intent, dict) and "mkt" in state.intent:
            return state.intent["mkt"]
        return {}