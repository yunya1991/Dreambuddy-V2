"""
A0 矛盾论节点 — 内部方法论框架

⚠️ A0 不是独立执行节点，内嵌到 A1→A2→A3 全链路，三节点各自调用 A0 做不同维度的矛盾分析:
    - A1 深度调研: 调用 A0 发现主要矛盾（识别市场当前的主要矛盾是什么）
    - A2 第一性原理: 调用 A0 辩证看待矛盾（分析矛盾的主次关系，哪个是主要矛盾）
    - A3 策略设计: 调用 A0 推演解决矛盾（围绕主要矛盾推演解决方案）

此文件提供 A0 的分析逻辑实现，供 A1/A2/A3 内部调用，
不通过 Registry 注册为独立节点。

多维度主矛盾分析:
    - 多空矛盾（趋势 vs 反趋势）
    - 量价矛盾（放量 vs 缩量）
    - 周期矛盾（长周期 vs 短周期）
    - 情绪矛盾（贪婪 vs 恐惧）

方法论：四维评分，找出当前市场的主要矛盾，
主要矛盾决定方向，次要矛盾决定节奏。
"""

from __future__ import annotations

from typing import Dict, Any, List, Tuple

from dreamos.registry.base import BaseNode
from dreamos.shared.state import State, NodeResult


class A0ContradictionNode(BaseNode):
    """A0 矛盾论节点 — 内部方法论

    ⚠️ 此节点不注册到 Registry，不独立执行。
    内嵌到 A1/A2/A3 三个节点:
        A1 调用 A0 → 发现主要矛盾
        A2 调用 A0 → 辩证看待矛盾
        A3 调用 A0 → 推演解决矛盾

    四维矛盾分析，找出市场主矛盾。
    """

    node_id = "A0"
    name = "矛盾论(内部)"
    description = "内部方法论: 多维度主矛盾分析（多空/量价/周期/情绪）"
    chain = "A"
    tags = ["research", "contradiction", "methodology", "internal"]
    estimated_tokens = 0
    estimated_latency_ms = 150

    # 矛盾维度
    DIMENSIONS = [
        ("trend_counter", "趋势 vs 反趋势", 0.30),
        ("volume_price", "量价配合", 0.25),
        ("timeframe", "长周期 vs 短周期", 0.25),
        ("sentiment", "贪婪 vs 恐惧", 0.20),
    ]

    def execute_core(self, state: State) -> NodeResult:
        mkt = self._get_market_data(state)
        rationale: List[str] = []
        contradictions: Dict[str, Dict[str, Any]] = {}

        # ── 1. 多空矛盾 ──────────────────────
        trend_score = self._analyze_trend_contradiction(mkt)
        contradictions["trend_counter"] = trend_score

        # ── 2. 量价矛盾 ──────────────────────
        vp_score = self._analyze_volume_price(mkt)
        contradictions["volume_price"] = vp_score

        # ── 3. 周期矛盾 ──────────────────────
        tf_score = self._analyze_timeframe(mkt)
        contradictions["timeframe"] = tf_score

        # ── 4. 情绪矛盾 ──────────────────────
        sent_score = self._analyze_sentiment(mkt)
        contradictions["sentiment"] = sent_score

        # ── 综合：找出主矛盾 ──────────────────
        main_dim, main_data = max(
            contradictions.items(),
            key=lambda x: x[1]["intensity"]
        )
        main_direction = main_data["direction"]
        intensity = main_data["intensity"]

        # 置信度 = 基础 + 主矛盾强度 + 维度一致性
        agreement = self._calc_agreement(contradictions)
        confidence = 0.4 + intensity * 0.4 + agreement * 0.2
        confidence = min(confidence, 0.95)

        direction = main_direction

        rationale.append("[A0矛盾论] 四维矛盾分析")
        for dim_key, dim_name, weight in self.DIMENSIONS:
            d = contradictions[dim_key]
            rationale.append(f"  {dim_name}: {d['direction']} (强度{d['intensity']:.0%})")
        rationale.append(f"  ★ 主矛盾: {main_data['name']} → 方向{direction}, 强度{intensity:.0%}")
        rationale.append(f"  维度一致性: {agreement:.0%} | 综合置信度: {confidence:.1%}")

        return NodeResult(
            node_id="A0",
            confidence=round(confidence, 3),
            direction=direction,
            outputs={
                "main_contradiction": main_dim,
                "main_direction": direction,
                "intensity": intensity,
                "agreement": agreement,
                "dimensions": contradictions,
                "rationale": rationale,
            },
        )

    def _analyze_trend_contradiction(self, mkt: Dict) -> Dict[str, Any]:
        """趋势 vs 反趋势 矛盾"""
        price = mkt.get("price", 0)
        ema20 = mkt.get("ema20", price)
        ema50 = mkt.get("ema50", price)
        rsi = mkt.get("rsi14", 50)
        ch24 = mkt.get("change_24h", 0)

        # 趋势方向（EMA）— 放宽判断，不需要完全排列
        trend_bull = price > ema20 and ema20 > ema50
        trend_bear = price < ema20 and ema20 < ema50
        weak_bull = price > ema50  # 价格至少在EMA50之上
        weak_bear = price < ema50   # 价格至少在EMA50之下

        # 反趋势信号（RSI 极值）
        counter_bull = rsi < 35  # 超卖 = 反弹
        counter_bear = rsi > 65  # 超买 = 回调

        if trend_bull and counter_bear:
            direction = "LONG"  # 趋势向上，回踩
            intensity = 0.5
        elif trend_bear and counter_bull:
            direction = "SHORT"
            intensity = 0.5
        elif trend_bull and not counter_bear:
            direction = "LONG"
            intensity = 0.8
        elif trend_bear and not counter_bull:
            direction = "SHORT"
            intensity = 0.8
        elif weak_bull and not counter_bear:
            # 价格>EMA50但EMA排列不完整，弱多头
            direction = "LONG"
            intensity = 0.4
        elif weak_bear and not counter_bull:
            # 价格<EMA50但EMA排列不完整，弱空头
            direction = "SHORT"
            intensity = 0.4
        else:
            # 震荡
            direction = "HOLD"
            intensity = 0.3

        return {
            "name": "趋势 vs 反趋势",
            "direction": direction,
            "intensity": intensity,
            "trend": "bull" if trend_bull else "bear" if trend_bear else "neutral",
            "counter": "bull" if counter_bull else "bear" if counter_bear else "neutral",
        }

    def _analyze_volume_price(self, mkt: Dict) -> Dict[str, Any]:
        """量价配合分析"""
        vol_ratio = mkt.get("vol_ratio", 1.0)
        ch24 = mkt.get("change_24h", 0)
        ch4h = mkt.get("change_4h", 0)

        # 量价配合度
        price_up = ch24 > 0
        vol_up = vol_ratio > 1.2
        vol_down = vol_ratio < 0.8

        if price_up and vol_up:
            direction = "LONG"
            intensity = 0.75  # 放量上涨，健康
        elif price_up and vol_down:
            direction = "LONG"
            intensity = 0.35  # 缩量上涨，动力不足
        elif not price_up and vol_up:
            direction = "SHORT"
            intensity = 0.75  # 放量下跌，空头强
        elif not price_up and vol_down:
            direction = "SHORT"
            intensity = 0.35  # 缩量下跌，空头衰竭
        else:
            direction = "HOLD"
            intensity = 0.3

        return {
            "name": "量价配合",
            "direction": direction,
            "intensity": intensity,
            "volume": "high" if vol_up else "low" if vol_down else "normal",
            "price_direction": "up" if price_up else "down",
        }

    def _analyze_timeframe(self, mkt: Dict) -> Dict[str, Any]:
        """长周期 vs 短周期 矛盾"""
        ch24 = mkt.get("change_24h", 0)
        ch4h = mkt.get("change_4h", 0)
        ch1h = mkt.get("change_1h", 0)

        long_dir = 1 if ch24 > 0 else -1
        mid_dir = 1 if ch4h > 0 else -1
        short_dir = 1 if ch1h > 0 else -1

        consistency = (long_dir + mid_dir + short_dir) / 3

        if consistency > 0.5:
            direction = "LONG"
            intensity = 0.8
        elif consistency < -0.5:
            direction = "SHORT"
            intensity = 0.8
        elif long_dir != short_dir:
            # 周期背离
            direction = "LONG" if long_dir > 0 else "SHORT"
            intensity = 0.4  # 有矛盾，强度降
        else:
            direction = "HOLD"
            intensity = 0.3

        return {
            "name": "周期共振",
            "direction": direction,
            "intensity": intensity,
            "long_trend": "up" if long_dir > 0 else "down",
            "short_trend": "up" if short_dir > 0 else "down",
            "consistency": consistency,
        }

    def _analyze_sentiment(self, mkt: Dict) -> Dict[str, Any]:
        """情绪矛盾分析"""
        rsi = mkt.get("rsi14", 50)
        funding = mkt.get("funding_rate", 0)
        fgi = mkt.get("fgi", 50)  # Fear & Greed

        # 情绪极值
        extreme_fear = fgi < 30 or rsi < 30
        extreme_greed = fgi > 70 or rsi > 70

        # 资金费率反向指标
        funding_extreme = abs(funding) > 0.001  # 10bps以上

        if extreme_fear:
            direction = "LONG"  # 恐惧 = 买入机会
            intensity = 0.7
        elif extreme_greed:
            direction = "SHORT"  # 贪婪 = 卖出机会
            intensity = 0.7
        elif funding_extreme and funding > 0:
            direction = "SHORT"  # 多头拥挤
            intensity = 0.5
        elif funding_extreme and funding < 0:
            direction = "LONG"  # 空头拥挤
            intensity = 0.5
        elif fgi > 55:
            direction = "LONG"
            intensity = 0.4
        elif fgi < 45:
            direction = "SHORT"
            intensity = 0.4
        else:
            direction = "HOLD"
            intensity = 0.3

        return {
            "name": "情绪极值",
            "direction": direction,
            "intensity": intensity,
            "fgi": fgi,
            "funding_rate": funding,
        }

    def _calc_agreement(self, contradictions: Dict) -> float:
        """计算维度一致性"""
        directions = [d["direction"] for d in contradictions.values() if d["direction"] != "HOLD"]
        if not directions:
            return 0.5
        from collections import Counter
        counts = Counter(directions)
        most_common_count = counts.most_common(1)[0][1]
        return most_common_count / len(directions)

    def _get_market_data(self, state: State) -> Dict[str, Any]:
        if hasattr(state, "market") and state.market:
            return state.market
        if hasattr(state, "market_data") and state.market_data:
            return state.market_data
        if isinstance(state.intent, dict) and "mkt" in state.intent:
            return state.intent["mkt"]
        return {}
