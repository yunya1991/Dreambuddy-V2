"""
C2 动量分析节点

基于经典指标系统的动量分析能力：
    - 动量方向与强度
    - 动量变化率
    - 动量背离检测
    - RSI 动量
    - MACD 动量
    - 价格变化动量

输入: state.market_data 或 state.inputs["mkt"]
输出: direction / confidence / momentum_score / divergence / rationale
"""

from __future__ import annotations

from typing import Dict, Any, List

from dreamos.registry.base import BaseNode
from dreamos.shared.state import State, NodeResult


class C2MomentumNode(BaseNode):
    """C2 动量分析节点

    多维度动量分析，检测趋势强度和潜在背离信号。
    """

    node_id = "C2"
    name = "动量分析"
    description = "多维度动量分析（趋势强度/变化率/背离检测/RSI/MACD）"
    chain = "C"
    tags = ["momentum", "classic", "divergence"]
    estimated_tokens = 0
    estimated_latency_ms = 100

    def execute_core(self, state: State) -> NodeResult:
        mkt = self._get_market_data(state)
        rationale: List[str] = []
        scores = []

        price = mkt.get("price", 0)
        ch1h = mkt.get("change_1h", 0)
        ch4h = mkt.get("change_4h", 0)
        ch24h = mkt.get("change_24h", 0)
        rsi = mkt.get("rsi14", 50)
        macd = mkt.get("macd", 0)
        macd_signal = mkt.get("macd_signal", 0)
        macd_hist = mkt.get("macd_hist", 0)

        # ── 1. 价格动量 ───────────────────────────────
        momentum_score = 0
        if ch24h > 3:
            scores.append(("LONG", 0.20, f"24h涨幅{ch24h:.1f}%，强势上涨"))
            momentum_score += 0.3
        elif ch24h < -3:
            scores.append(("SHORT", 0.20, f"24h跌幅{ch24h:.1f}%，强势下跌"))
            momentum_score -= 0.3
        elif ch24h > 1:
            scores.append(("LONG", 0.10, f"24h小幅上涨{ch24h:.1f}%"))
            momentum_score += 0.15
        elif ch24h < -1:
            scores.append(("SHORT", 0.10, f"24h小幅下跌{ch24h:.1f}%"))
            momentum_score -= 0.15

        # ── 2. 动量加速度（多周期变化） ────────────────
        # P3-2: 增加中性区间，避免震荡市场中过度敏感
        accel_threshold = abs(ch24h) * 0.2  # 20% 以内视为正常波动
        diff = ch4h - ch24h / 6
        if abs(diff) < max(accel_threshold, 0.1):
            scores.append(("HOLD", 0.10, f"动量平稳：4h({ch4h:.1f}%) ≈ 24h平均({ch24h/6:.1f}%)"))
        elif ch4h > ch24h / 6:
            scores.append(("LONG", 0.15, f"动量加速：4h({ch4h:.1f}%) > 24h平均({ch24h/6:.1f}%)"))
            momentum_score += 0.2
        else:
            scores.append(("SHORT", 0.15, f"动量减速：4h({ch4h:.1f}%) < 24h平均({ch24h/6:.1f}%)"))
            momentum_score -= 0.2

        # ── 3. RSI 动量 ──────────────────────────────
        if rsi > 55:
            scores.append(("LONG", 0.10, f"RSI动量偏多({rsi:.1f})"))
            momentum_score += 0.1
        elif rsi < 45:
            scores.append(("SHORT", 0.10, f"RSI动量偏空({rsi:.1f})"))
            momentum_score -= 0.1

        # ── 4. MACD 动量 ─────────────────────────────
        if macd > macd_signal:
            scores.append(("LONG", 0.15, f"MACD动量偏多(macd={macd:.3f}, signal={macd_signal:.3f})"))
            momentum_score += 0.15
        else:
            scores.append(("SHORT", 0.15, f"MACD动量偏空(macd={macd:.3f}, signal={macd_signal:.3f})"))
            momentum_score -= 0.15

        # ── 5. 动量背离检测 ──────────────────────────
        divergence = "none"
        if ch24h > 0 and rsi < 50:
            divergence = "bullish_divergence"
            scores.append(("LONG", 0.20, "看涨背离：价格上涨但RSI未跟上"))
            momentum_score += 0.25
        elif ch24h < 0 and rsi > 50:
            divergence = "bearish_divergence"
            scores.append(("SHORT", 0.20, "看跌背离：价格下跌但RSI未下跌"))
            momentum_score -= 0.25
        elif macd_hist > 0 and ch24h < 0:
            divergence = "bullish_divergence"
            scores.append(("LONG", 0.15, "MACD柱背离：柱体上升但价格下跌"))
            momentum_score += 0.2

        # ── 综合计算 ────────────────────────────────
        momentum_score = max(-1.0, min(1.0, momentum_score))
        long_score = sum(w for d, w, _ in scores if d == "LONG")
        short_score = sum(w for d, w, _ in scores if d == "SHORT")
        total = long_score + short_score

        if total == 0:
            direction = "HOLD"
            confidence = 0.3
        elif long_score > short_score:
            direction = "LONG"
            confidence = long_score / max(total, 0.01)
        else:
            direction = "SHORT"
            confidence = short_score / max(total, 0.01)

        confidence = min(0.95, confidence + abs(momentum_score) * 0.4)

        # P3-4: 趋势确认 — 价格相对于 EMA 的位置
        mkt = self._get_market_data(state)
        price = mkt.get("price", 0)
        ema50 = mkt.get("ema50", price)
        ema200 = mkt.get("ema200", price)

        # 中期趋势过滤器 — 避免在中期趋势中逆势操作
        # 使用EMA20 vs EMA50（更灵敏，避免滞后）
        ema20 = mkt.get("ema20", price)
        ema_trend_bull = ema20 > ema50
        ema_trend_bear = ema20 < ema50

        if direction == "LONG" and ema_trend_bear:
            if confidence < 0.6:
                direction = "HOLD"
                confidence = 0.3
            else:
                confidence *= 0.75
        elif direction == "SHORT" and ema_trend_bull:
            if confidence < 0.6:
                direction = "HOLD"
                confidence = 0.3
            else:
                confidence *= 0.75

        if direction == "LONG":
            if price < ema50:
                confidence *= 0.90  # 轻微降权
            if price < ema200:
                confidence *= 0.95   # 极轻微降权
        elif direction == "SHORT":
            if price > ema50:
                confidence *= 0.90  # 轻微降权
            if price > ema200:
                confidence *= 0.95   # 极轻微降权

        rationale = [r for _, _, r in scores[:6]]
        rationale.insert(0, f"[C2动量分析] 动量得分={momentum_score:+.2f} | 背离={divergence}")
        rationale.append(f"  方向: {direction} | 置信度: {confidence:.1%}")

        outputs = {
            "momentum_score": round(momentum_score, 3),
            "divergence": divergence,
            "price_momentum": {
                "change_1h": ch1h,
                "change_4h": ch4h,
                "change_24h": ch24h,
            },
            "rsi_momentum": rsi,
            "macd_momentum": {
                "macd": macd,
                "signal": macd_signal,
                "histogram": macd_hist,
            },
            "scores": {"long": round(long_score, 3), "short": round(short_score, 3)},
            "rationale": rationale,
        }

        return NodeResult(
            node_id="C2",
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