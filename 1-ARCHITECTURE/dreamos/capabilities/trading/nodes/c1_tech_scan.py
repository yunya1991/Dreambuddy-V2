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
            if bull_count == 3:
                scores.append(("LONG", 0.25, "多头排列（3/3）"))
            elif bull_count == 2:
                scores.append(("LONG", 0.15, "偏多排列（2/3）"))
            elif bull_count == 1:
                scores.append(("HOLD", 0.10, "多空交织（1/3），方向不明"))
            else:
                scores.append(("SHORT", 0.25, "空头排列（0/3）"))

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

        # ── 6. Freqtrade 量化策略信号 ────────────
        ft_signal = mkt.get("freqtrade_signal")
        if ft_signal and isinstance(ft_signal, dict):
            ft_direction = ft_signal.get("direction", "HOLD")
            ft_conf = float(ft_signal.get("confidence", 0))
            ft_strategy_count = int(ft_signal.get("strategy_count", 0))
            ft_long_votes = int(ft_signal.get("long_votes", 0))
            ft_short_votes = int(ft_signal.get("short_votes", 0))

            if ft_strategy_count >= 3 and ft_direction in ("LONG", "SHORT") and ft_conf > 0.55:
                # 策略数≥3且高置信时，作为强技术信号
                ft_weight = min(0.20, 0.08 + ft_strategy_count * 0.015 + (ft_conf - 0.5) * 0.2)
                scores.append((ft_direction, ft_weight,
                              f"Freqtrade策略({ft_strategy_count}个)看多 {ft_long_votes} vs 看空 {ft_short_votes}，置信 {ft_conf:.0%}"))
            elif ft_strategy_count >= 2 and ft_direction in ("LONG", "SHORT"):
                # 策略数较少时，作为中等强度信号
                ft_weight = min(0.10, 0.05 + ft_strategy_count * 0.01)
                scores.append((ft_direction, ft_weight,
                              f"Freqtrade策略({ft_strategy_count}个)偏{ft_direction}，置信 {ft_conf:.0%}"))
            elif ft_direction == "HOLD" or ft_strategy_count == 0:
                scores.append(("HOLD", 0.05, "Freqtrade信号中性或策略不足"))

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
            confidence *= 0.92  # 分歧大，轻微降置信

        # P3-4: 中期趋势过滤器 — 避免在中期趋势中逆势操作
        # 使用EMA20 vs EMA50（更灵敏，避免滞后）
        # 如果EMA20 < EMA50（中期下跌趋势），限制做多
        # 如果EMA20 > EMA50（中期上涨趋势），限制做空
        ema_trend_bull = ema20 > ema50
        ema_trend_bear = ema20 < ema50

        if direction == "LONG" and ema_trend_bear:
            # 中期下跌趋势中做多，逆势，适度降权
            if confidence < 0.6:
                direction = "HOLD"
                confidence = 0.3
            else:
                confidence *= 0.75
        elif direction == "SHORT" and ema_trend_bull:
            # 中期上涨趋势中做空，逆势，适度降权
            if confidence < 0.6:
                direction = "HOLD"
                confidence = 0.3
            else:
                confidence *= 0.75

        # P3-4: 趋势确认 — 价格相对于 EMA50/EMA200 的位置
        if direction == "LONG":
            if price < ema50:
                confidence *= 0.90  # 价格在 EMA50 之下做多，轻微降权
            if price < ema200:
                confidence *= 0.95   # 价格在 EMA200 之下做多，极轻微降权
        elif direction == "SHORT":
            if price > ema50:
                confidence *= 0.90  # 价格在 EMA50 之上做空，轻微降权
            if price > ema200:
                confidence *= 0.95   # 价格在 EMA200 之上做空，极轻微降权

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
        # P0-5 修复: 纯代码节点的最低置信度设为 0.3, 避免触发 Reflector 无意义的 REDO
        # (代码节点重试结果相同, REDO 只会浪费计算资源)
        final_conf = round(max(min(confidence, 0.95), 0.3), 3)
        return NodeResult(
            node_id="C1",
            confidence=final_conf,
            direction=direction,
            outputs=indicators,
        )

    def _get_market_data(self, state: State) -> Dict[str, Any]:
        """从 state 中提取市场数据"""
        if hasattr(state, "market") and state.market:
            return state.market
        if hasattr(state, "market_data") and state.market_data:
            return state.market_data
        if isinstance(state.intent, dict) and "mkt" in state.intent:
            return state.intent["mkt"]
        return {}
