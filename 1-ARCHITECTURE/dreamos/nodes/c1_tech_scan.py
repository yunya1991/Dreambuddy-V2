"""
C1 技术扫描节点

多周期技术指标扫描：
    - 趋势判断（EMA 排列）
    - RSI 超买超卖
    - MACD 金叉死叉
    - 量能分析
    - 波动率分析

输入: state.market_data 或 state.inputs["mkt"]
输出: direction / confidence / rationale / indicators
"""

from __future__ import annotations

from typing import Dict, Any, List

from dreamos.registry.base import BaseNode
from dreamos.shared.state import State, NodeResult


class C1TechScanNode(BaseNode):
    """C1 技术扫描节点

    多周期技术指标综合分析，输出趋势方向和置信度。
    """

    node_id = "C1"
    name = "技术扫描"
    description = "多周期技术指标扫描（EMA/RSI/MACD/量能/波动率）"
    chain = "C"
    tags = ["technical", "classic", "trend"]
    estimated_tokens = 0
    estimated_latency_ms = 100

    def execute_core(self, state: State) -> NodeResult:
        mkt = self._get_market_data(state)
        rationale: List[str] = []
        scores = []  # (方向, 权重, 理由)

        # ── 1. EMA 排列（趋势） ────────────────────
        price = mkt.get("price", 0)
        ema20 = mkt.get("ema20", price)
        ema50 = mkt.get("ema50", price)
        ema200 = mkt.get("ema200", price)

        if price > ema20 > ema50 > ema200:
            scores.append(("LONG", 0.25, "多头排列：价格>EMA20>EMA50>EMA200"))
        elif price < ema20 < ema50 < ema200:
            scores.append(("SHORT", 0.25, "空头排列：价格<EMA20<EMA50<EMA200"))
        else:
            # 部分多头/空头
            bull_count = sum([
                price > ema20,
                ema20 > ema50,
                ema50 > ema200,
            ])
            if bull_count >= 2:
                scores.append(("LONG", 0.10 + bull_count * 0.05, f"偏多排列（{bull_count}/3）"))
            elif bull_count <= 1:
                scores.append(("SHORT", 0.10 + (3 - bull_count) * 0.05, f"偏空排列（{bull_count}/3）"))

        # ── 2. RSI ──────────────────────────────
        rsi = mkt.get("rsi14", 50)
        if rsi < 30:
            scores.append(("LONG", 0.15, f"RSI={rsi:.1f} 超卖，反弹概率高"))
        elif rsi > 70:
            scores.append(("SHORT", 0.15, f"RSI={rsi:.1f} 超买，回调风险高"))
        elif rsi < 45:
            scores.append(("LONG", 0.05, f"RSI={rsi:.1f} 偏弱"))
        elif rsi > 55:
            scores.append(("SHORT", 0.05, f"RSI={rsi:.1f} 偏强"))

        # ── 3. MACD ─────────────────────────────
        macd = mkt.get("macd", 0)
        macd_signal = mkt.get("macd_signal", 0)
        if macd > macd_signal and macd > 0:
            scores.append(("LONG", 0.15, "MACD 金叉且在零轴上方"))
        elif macd < macd_signal and macd < 0:
            scores.append(("SHORT", 0.15, "MACD 死叉且在零轴下方"))
        elif macd > macd_signal:
            scores.append(("LONG", 0.08, "MACD 金叉（零轴下）"))
        else:
            scores.append(("SHORT", 0.08, "MACD 死叉（零轴上）"))

        # ── 4. 量能 ─────────────────────────────
        vol_ratio = mkt.get("vol_ratio", 1.0)
        ch24 = mkt.get("change_24h", 0)
        if vol_ratio > 1.5 and ch24 > 0:
            scores.append(("LONG", 0.10, f"放量上涨（量比{vol_ratio:.1f}x，24h {ch24:+.1f}%）"))
        elif vol_ratio > 1.5 and ch24 < 0:
            scores.append(("SHORT", 0.10, f"放量下跌（量比{vol_ratio:.1f}x，24h {ch24:+.1f}%）"))
        elif vol_ratio < 0.7:
            scores.append(("HOLD", 0.05, f"缩量震荡（量比{vol_ratio:.1f}x），方向不明"))

        # ── 5. 波动率 ───────────────────────────
        atr_pct = mkt.get("atr_pct", 0.02)
        regime = mkt.get("regime", "RANGE")
        if regime == "TREND" and atr_pct > 0.03:
            scores.append(("LONG" if ch24 > 0 else "SHORT", 0.10, f"趋势行情+高波动（ATR {atr_pct:.1%}）"))
        elif regime == "RANGE":
            scores.append(("HOLD", 0.10, "震荡行情，建议观望"))

        # ── 综合计算 ────────────────────────────
        long_score = sum(w for d, w, _ in scores if d == "LONG")
        short_score = sum(w for d, w, _ in scores if d == "SHORT")
        hold_score = sum(w for d, w, _ in scores if d == "HOLD")

        total = long_score + short_score + hold_score
        if total == 0:
            direction = "HOLD"
            confidence = 0.3
        elif hold_score > 0.4:
            direction = "HOLD"
            confidence = hold_score
        elif long_score > short_score:
            direction = "LONG"
            confidence = long_score / max(total, 0.01)
        else:
            direction = "SHORT"
            confidence = short_score / max(total, 0.01)

        # 置信度修正：指标一致性
        diff = abs(long_score - short_score)
        if diff < 0.1:
            confidence *= 0.7  # 分歧大，降置信

        rationale = [r for _, _, r in scores[:5]]
        rationale.insert(0, f"[C1技术扫描] 价格=${price:.2f} | RSI={rsi:.1f} | 量比={vol_ratio:.2f}x")
        rationale.append(f"  方向: {direction} | 置信度: {confidence:.1%}")

        indicators = {
            "price": price,
            "ema20": ema20,
            "ema50": ema50,
            "ema200": ema200,
            "rsi": rsi,
            "macd": macd,
            "macd_signal": macd_signal,
            "vol_ratio": vol_ratio,
            "atr_pct": atr_pct,
            "regime": regime,
            "scores": {"long": round(long_score, 3), "short": round(short_score, 3), "hold": round(hold_score, 3)},
        }

        indicators["rationale"] = rationale
        return NodeResult(
            node_id="C1",
            confidence=round(min(confidence, 0.95), 3),
            direction=direction,
            outputs=indicators,
        )

    def _get_market_data(self, state: State) -> Dict[str, Any]:
        """从 state 中提取市场数据"""
        if hasattr(state, "market_data") and state.market_data:
            return state.market_data
        if isinstance(state.inputs, dict) and "mkt" in state.inputs:
            return state.inputs["mkt"]
        if isinstance(state.inputs, dict):
            return state.inputs
        return {}
