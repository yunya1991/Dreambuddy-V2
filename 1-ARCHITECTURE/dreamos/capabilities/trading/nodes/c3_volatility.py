"""
C3 波动率分析节点

基于经典指标系统的波动率分析能力：
    - ATR 波动率
    - Bollinger Bands 带宽
    - 历史波动率对比
    - 波动率趋势判断
    - 波动率挤压（Volatility Squeeze）检测

输入: state.market_data 或 state.inputs["mkt"]
输出: direction / confidence / volatility_level / squeeze / rationale
"""

from __future__ import annotations

from typing import Dict, Any, List

from dreamos.registry.base import BaseNode
from dreamos.shared.state import State, NodeResult


class C3VolatilityNode(BaseNode):
    """C3 波动率分析节点

    多维度波动率分析，检测行情状态和潜在突破机会。
    """

    node_id = "C3"
    name = "波动率分析"
    description = "多维度波动率分析（ATR/布林带/历史对比/波动率挤压）"
    chain = "C"
    tags = ["volatility", "classic", "atr", "bollinger"]
    estimated_tokens = 0
    estimated_latency_ms = 100

    def execute_core(self, state: State) -> NodeResult:
        mkt = self._get_market_data(state)
        rationale: List[str] = []
        scores = []

        price = mkt.get("price", 0)
        atr = mkt.get("atr", 0)
        atr_pct = mkt.get("atr_pct", 0.02)
        bb_upper = mkt.get("bb_upper", price)
        bb_lower = mkt.get("bb_lower", price)
        bb_middle = mkt.get("bb_middle", price)
        bb_width = mkt.get("bb_width", 0.05)
        vol_ratio = mkt.get("vol_ratio", 1.0)
        change_24h = mkt.get("change_24h", 0)

        # ── 1. ATR 波动率等级 ──────────────────────────
        volatility_level = "normal"
        if atr_pct > 0.04:
            volatility_level = "high"
            scores.append(("HOLD", 0.15, f"高波动(ATR={atr_pct:.1%})，风险较高"))
        elif atr_pct < 0.015:
            volatility_level = "low"
            scores.append(("HOLD", 0.15, f"低波动(ATR={atr_pct:.1%})，方向不明"))
        else:
            scores.append(("HOLD", 0.10, f"正常波动(ATR={atr_pct:.1%})"))

        # ── 2. 布林带带宽分析 ──────────────────────────
        if bb_width > 0.08:
            scores.append(("HOLD", 0.15, f"布林带宽({bb_width:.1%})，高波动"))
            volatility_level = "high"
        elif bb_width < 0.03:
            scores.append(("LONG", 0.25, f"波动率挤压(带宽={bb_width:.1%})，潜在突破"))
            volatility_level = "squeeze"
        else:
            scores.append(("HOLD", 0.10, f"正常布林带宽({bb_width:.1%})"))

        # ── 3. 价格相对于布林带位置 ──────────────────────
        if price >= bb_upper:
            scores.append(("SHORT", 0.15, f"触及布林上轨({price:.2f})，超买"))
        elif price <= bb_lower:
            scores.append(("LONG", 0.15, f"触及布林下轨({price:.2f})，超卖"))
        else:
            # P3-2: 布林带中线附近 ±15% 带宽内给中性，避免频繁给方向
            bb_range = bb_upper - bb_lower
            if bb_range > 0:
                dist_from_mid = abs(price - bb_middle) / bb_range
                if dist_from_mid < 0.15:
                    scores.append(("HOLD", 0.08, "布林带中线附近震荡，方向不明"))
                elif price > bb_middle:
                    scores.append(("LONG", 0.08, f"布林带上半区({price:.2f})"))
                else:
                    scores.append(("SHORT", 0.08, f"布林带下半区({price:.2f})"))

        # ── 4. 成交量波动率 ────────────────────────────
        if vol_ratio > 2.0:
            scores.append(("LONG" if change_24h > 0 else "SHORT", 0.15,
                          f"放量({vol_ratio:.1f}x)，趋势加速"))
        elif vol_ratio < 0.5:
            scores.append(("HOLD", 0.10, f"缩量({vol_ratio:.1f}x)，观望"))

        # ── 5. 波动率趋势判断 ──────────────────────────
        atr_change = mkt.get("atr_change", 0)
        if atr_change > 0.2:
            scores.append(("HOLD", 0.10, f"波动率上升({atr_change:.1%})，风险加大"))
        elif atr_change < -0.2:
            scores.append(("HOLD", 0.10, f"波动率下降({atr_change:.1%})，趋势减弱"))

        # ── 综合计算 ──────────────────────────────────
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

        # 波动率挤压时提高置信度
        if volatility_level == "squeeze":
            confidence = min(0.95, confidence + 0.2)

        rationale = [r for _, _, r in scores[:6]]
        rationale.insert(0, f"[C3波动率] 级别={volatility_level} | ATR={atr_pct:.1%} | 带宽={bb_width:.1%}")
        rationale.append(f"  方向: {direction} | 置信度: {confidence:.1%}")

        outputs = {
            "volatility_level": volatility_level,
            "squeeze": volatility_level == "squeeze",
            "atr": atr,
            "atr_pct": atr_pct,
            "atr_change": atr_change,
            "bollinger": {
                "upper": bb_upper,
                "middle": bb_middle,
                "lower": bb_lower,
                "width": bb_width,
            },
            "volume_ratio": vol_ratio,
            "scores": {"long": round(long_score, 3), "short": round(short_score, 3), "hold": round(hold_score, 3)},
            "rationale": rationale,
        }

        return NodeResult(
            node_id="C3",
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