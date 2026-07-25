#!/usr/bin/env python3
"""
A0 矛盾分析引擎 — 纯代码驱动，不依赖大模型。

基于《矛盾论》的7大矛盾维度，从市场数据中提取矛盾信号，
输出矛盾张力评分和方向倾向，供 BCRM2Adapter 做置信度校准。

7大维度：
  1. 多空矛盾 (bull_bear)     — 买卖力量对抗
  2. 时间矛盾 (time)          — 不同时间框架方向分歧
  3. 信息不对称矛盾 (info)    — 量价关系背离
  4. 流动性矛盾 (liquidity)   — 流动性枯竭 vs 充裕
  5. 情绪矛盾 (emotion)       — 恐惧贪婪指数极端
  6. 周期矛盾 (cycle)         — 趋势持续时间 vs 历史均值
  7. 结构矛盾 (structure)     — 支撑阻力位突破/假突破
"""
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any
import numpy as np
import logging

logger = logging.getLogger(__name__)


@dataclass
class ContradictionDimension:
    """单个矛盾维度"""
    dim_id: str
    name: str
    thesis: str           # 正题
    antithesis: str       # 反题
    tension: float        # 张力 0-1
    dominant_side: str    # BULL / BEAR / EQUAL
    evidence: str = ""    # 证据描述


@dataclass
class A0AnalysisResult:
    """A0 矛盾分析结果"""
    contradictions: List[ContradictionDimension] = field(default_factory=list)
    primary_contradiction: Optional[ContradictionDimension] = None
    overall_tension: float = 0.0       # 综合张力
    direction_bias: float = 0.0        # 方向偏置 -1(空) ~ +1(多)
    confidence_adjustment: float = 0.0  # 置信度调整 -0.15 ~ +0.15
    risk_warning: str = ""             # 风险预警
    trauma_signal: bool = False        # 创伤信号

    def to_dict(self) -> dict:
        return {
            "contradictions": [
                {
                    "dim_id": c.dim_id, "name": c.name,
                    "thesis": c.thesis, "antithesis": c.antithesis,
                    "tension": round(c.tension, 4),
                    "dominant_side": c.dominant_side,
                    "evidence": c.evidence,
                }
                for c in self.contradictions
            ],
            "primary_contradiction": self.primary_contradiction.dim_id if self.primary_contradiction else None,
            "overall_tension": round(self.overall_tension, 4),
            "direction_bias": round(self.direction_bias, 4),
            "confidence_adjustment": round(self.confidence_adjustment, 4),
            "risk_warning": self.risk_warning,
            "trauma_signal": self.trauma_signal,
        }


class A0ContradictionEngine:
    """A0 矛盾分析引擎 — 纯代码驱动"""

    # 周期统计窗口
    TREND_LOOKBACK = 60       # 看近60根K线判断趋势持续时间
    LIQUIDITY_LOOKBACK = 20   # 流动性看近20根
    STRUCTURE_LOOKBACK = 30   # 结构看近30根

    def __init__(self):
        self._trauma_tracker: Dict[str, List[Dict]] = {}  # inst_id -> 最近的决策记录

    def analyze(
        self,
        df: "pd.DataFrame",
        inst_id: str = "",
        market_snapshot: Optional[Dict[str, Any]] = None,
    ) -> A0AnalysisResult:
        """
        执行7维矛盾分析。

        Args:
            df: K线数据，需要有 open/high/low/close/volume 列
            inst_id: 交易对标识
            market_snapshot: 额外市场快照（funding_rate, rsi 等可选）
        """
        if df is None or len(df) < 30:
            return A0AnalysisResult()

        snapshot = market_snapshot or {}
        closes = df["close"].values.astype(float)
        highs = df["high"].values.astype(float)
        lows = df["low"].values.astype(float)
        volumes = df["volume"].values.astype(float) if "volume" in df else np.ones(len(closes))

        result = A0AnalysisResult()

        # 逐维度分析
        result.contradictions.append(self._dim_bull_bear(closes, volumes, snapshot))
        result.contradictions.append(self._dim_time(df, snapshot))
        result.contradictions.append(self._dim_info(closes, volumes, snapshot))
        result.contradictions.append(self._dim_liquidity(closes, volumes, snapshot))
        result.contradictions.append(self._dim_emotion(closes, snapshot))
        result.contradictions.append(self._dim_cycle(closes, snapshot))
        result.contradictions.append(self._dim_structure(closes, highs, lows, snapshot))

        # 确定主要矛盾（张力最大的）
        result.primary_contradiction = max(result.contradictions, key=lambda c: c.tension)

        # 综合张力和方向偏置
        tensions = [c.tension for c in result.contradictions]
        result.overall_tension = float(np.mean(tensions))

        direction_scores = []
        for c in result.contradictions:
            if c.dominant_side == "BULL":
                direction_scores.append(c.tension)
            elif c.dominant_side == "BEAR":
                direction_scores.append(-c.tension)
            else:
                direction_scores.append(0.0)
        result.direction_bias = float(np.mean(direction_scores))

        # 置信度调整：方向偏置与BCRM信号一致时增强，不一致时削弱
        # 最大调整 ±0.15
        result.confidence_adjustment = float(np.clip(result.direction_bias * 0.15, -0.15, 0.15))

        # 风险预警
        if result.overall_tension > 0.7:
            result.risk_warning = "综合矛盾张力极高，市场处于极端状态，建议降低仓位"
        elif result.overall_tension > 0.5:
            result.risk_warning = "综合矛盾张力较高，注意反转风险"

        # 创伤信号检测（强迫性重复）
        result.trauma_signal = self._check_trauma(inst_id, result.direction_bias)

        return result

    # ================================================================
    # 维度1：多空矛盾 — 买卖力量对抗
    # ================================================================
    def _dim_bull_bear(self, closes, volumes, snapshot) -> ContradictionDimension:
        """多空矛盾：短期价格变动 vs 成交量方向"""
        pct = float(snapshot.get("price_change_pct", snapshot.get("ch24", 0)) or 0)
        if pct == 0 and len(closes) >= 2:
            pct = (closes[-1] - closes[-2]) / closes[-2] * 100 if closes[-2] > 0 else 0

        vol_ratio = float(snapshot.get("volume_ratio", 1.0) or 1.0)
        if vol_ratio == 1.0 and len(volumes) >= 20:
            vol_ratio = volumes[-1] / max(np.mean(volumes[-20:]), 1e-8)

        tension = min(abs(pct) / 5.0, 1.0) * min(vol_ratio / 2.0, 1.0)
        dominant = "BULL" if pct > 0 else ("BEAR" if pct < 0 else "EQUAL")

        return ContradictionDimension(
            dim_id="C1_bull_bear",
            name="多空矛盾",
            thesis=f"价格变动{pct:+.2f}%，买方主导" if pct > 0 else f"价格变动{pct:+.2f}%，卖方主导",
            antithesis=f"量比{vol_ratio:.2f}，{('放量确认' if vol_ratio > 1.2 else '缩量质疑')}",
            tension=tension,
            dominant_side=dominant,
            evidence=f"pct={pct:.2f}% vol_ratio={vol_ratio:.2f}",
        )

    # ================================================================
    # 维度2：时间矛盾 — 不同时间框架方向分歧
    # ================================================================
    def _dim_time(self, df, snapshot) -> ContradictionDimension:
        """时间矛盾：短期均线 vs 长期均线方向分歧"""
        closes = df["close"].values.astype(float)
        if len(closes) < 30:
            return ContradictionDimension("C2_time", "时间矛盾", "", "", 0.0, "EQUAL")

        ma_short = np.mean(closes[-5:])
        ma_mid = np.mean(closes[-20:])
        ma_long = np.mean(closes[-50:]) if len(closes) >= 50 else np.mean(closes)

        short_vs_mid = (ma_short - ma_mid) / ma_mid if ma_mid > 0 else 0
        mid_vs_long = (ma_mid - ma_long) / ma_long if ma_long > 0 else 0

        # 时间框架分歧：短期和长期方向不一致
        disagreement = 0.0
        if short_vs_mid * mid_vs_long < 0:  # 方向相反
            disagreement = min(abs(short_vs_mid) + abs(mid_vs_long), 0.1) / 0.1

        # 主导方向以短期为准
        dominant = "BULL" if short_vs_mid > 0.001 else ("BEAR" if short_vs_mid < -0.001 else "EQUAL")

        return ContradictionDimension(
            dim_id="C2_time",
            name="时间矛盾",
            thesis=f"短期MA{'上行' if short_vs_mid > 0 else '下行'} ({short_vs_mid:+.4f})",
            antithesis=f"中长期MA{'上行' if mid_vs_long > 0 else '下行'} ({mid_vs_long:+.4f})",
            tension=disagreement,
            dominant_side=dominant,
            evidence=f"short_vs_mid={short_vs_mid:.4f} mid_vs_long={mid_vs_long:.4f} disagreement={disagreement:.2f}",
        )

    # ================================================================
    # 维度3：信息不对称矛盾 — 量价关系背离
    # ================================================================
    def _dim_info(self, closes, volumes, snapshot) -> ContradictionDimension:
        """信息不对称：量价背离检测"""
        if len(closes) < 20 or len(volumes) < 20:
            return ContradictionDimension("C3_info", "信息不对称矛盾", "", "", 0.0, "EQUAL")

        price_change = (closes[-1] - closes[-5]) / closes[-5] if closes[-5] > 0 else 0
        vol_change = (np.mean(volumes[-5:]) - np.mean(volumes[-20:])) / max(np.mean(volumes[-20:]), 1e-8)

        # 量价背离：价格涨但量缩，或价格跌但量增
        divergence = 0.0
        if price_change > 0.01 and vol_change < -0.1:
            divergence = min(abs(price_change) * 10 + abs(vol_change), 1.0)
            dominant = "BEAR"  # 量价背离 → 看空
        elif price_change < -0.01 and vol_change > 0.1:
            divergence = min(abs(price_change) * 10 + abs(vol_change), 1.0)
            dominant = "BEAR"  # 放量下跌 → 看空
        else:
            divergence = 0.1
            dominant = "BULL" if price_change > 0 else "EQUAL"

        return ContradictionDimension(
            dim_id="C3_info",
            name="信息不对称矛盾",
            thesis=f"价格{'上涨' if price_change > 0 else '下跌'} {price_change:+.2%}",
            antithesis=f"成交量{'放大' if vol_change > 0 else '萎缩'} {vol_change:+.2%}",
            tension=divergence,
            dominant_side=dominant,
            evidence=f"price_change={price_change:.4f} vol_change={vol_change:.4f}",
        )

    # ================================================================
    # 维度4：流动性矛盾 — 流动性枯竭 vs 充裕
    # ================================================================
    def _dim_liquidity(self, closes, volumes, snapshot) -> ContradictionDimension:
        """流动性矛盾：成交量萎缩 + 波动率下降 = 流动性枯竭"""
        if len(volumes) < self.LIQUIDITY_LOOKBACK:
            return ContradictionDimension("C4_liquidity", "流动性矛盾", "", "", 0.0, "EQUAL")

        vol_recent = np.mean(volumes[-5:])
        vol_baseline = np.mean(volumes[-self.LIQUIDITY_LOOKBACK:])
        vol_decline = 1.0 - (vol_recent / max(vol_baseline, 1e-8))

        # 波动率
        if len(closes) >= 20:
            returns = np.diff(np.log(closes[-20:]))
            volatility = np.std(returns) if len(returns) > 1 else 0
        else:
            volatility = 0.02

        # 流动性枯竭：量缩 + 低波动
        liquidity_stress = 0.0
        if vol_decline > 0.3 and volatility < 0.01:
            liquidity_stress = min(vol_decline, 1.0)
            dominant = "BEAR"  # 流动性枯竭 → 看空
        elif vol_decline < -0.1:
            liquidity_stress = min(abs(vol_decline) * 0.5, 0.5)
            dominant = "BULL"  # 放量 → 看多
        else:
            liquidity_stress = 0.1
            dominant = "EQUAL"

        return ContradictionDimension(
            dim_id="C4_liquidity",
            name="流动性矛盾",
            thesis=f"成交量{'萎缩' if vol_decline > 0 else '放大'} {vol_decline:+.2%}",
            antithesis=f"波动率{volatility:.4f} ({'低波动' if volatility < 0.01 else '正常波动'})",
            tension=liquidity_stress,
            dominant_side=dominant,
            evidence=f"vol_decline={vol_decline:.4f} volatility={volatility:.4f}",
        )

    # ================================================================
    # 维度5：情绪矛盾 — 恐惧贪婪指数极端
    # ================================================================
    def _dim_emotion(self, closes, snapshot) -> ContradictionDimension:
        """情绪矛盾：RSI极端 + 价格加速 = 情绪反转预警"""
        rsi = float(snapshot.get("rsi", snapshot.get("rsi14", 50)) or 50)
        if rsi == 50 and len(closes) >= 14:
            rsi = self._calc_rsi(closes[-14:])

        # 价格加速
        if len(closes) >= 10:
            recent_return = (closes[-1] - closes[-5]) / closes[-5] if closes[-5] > 0 else 0
        else:
            recent_return = 0

        emotion_tension = 0.0
        if rsi > 75:
            emotion_tension = (rsi - 50) / 50  # 0.5 ~ 1.0
            dominant = "BEAR"  # 超买 → 看空
        elif rsi < 25:
            emotion_tension = (50 - rsi) / 50
            dominant = "BULL"  # 超卖 → 看多
        elif rsi > 65 and recent_return > 0.03:
            emotion_tension = (rsi - 50) / 100 + abs(recent_return) * 5
            dominant = "BEAR"
        elif rsi < 35 and recent_return < -0.03:
            emotion_tension = (50 - rsi) / 100 + abs(recent_return) * 5
            dominant = "BULL"
        else:
            emotion_tension = 0.1
            dominant = "EQUAL"

        emotion_tension = min(emotion_tension, 1.0)

        return ContradictionDimension(
            dim_id="C5_emotion",
            name="情绪矛盾",
            thesis=f"RSI={rsi:.1f} ({'超买' if rsi > 70 else '超卖' if rsi < 30 else '中性'})",
            antithesis=f"近期收益={recent_return:+.2%}",
            tension=emotion_tension,
            dominant_side=dominant,
            evidence=f"rsi={rsi:.1f} recent_return={recent_return:.4f}",
        )

    # ================================================================
    # 维度6：周期矛盾 — 趋势持续时间 vs 历史均值
    # ================================================================
    def _dim_cycle(self, closes, snapshot) -> ContradictionDimension:
        """周期矛盾：当前趋势持续了多久？是否超过历史均值？"""
        if len(closes) < self.TREND_LOOKBACK:
            return ContradictionDimension("C6_cycle", "周期矛盾", "", "", 0.0, "EQUAL")

        # 计算当前趋势持续时间
        ma20 = np.convolve(closes[-self.TREND_LOOKBACK:], np.ones(20) / 20, mode='valid')
        if len(ma20) < 5:
            return ContradictionDimension("C6_cycle", "周期矛盾", "", "", 0.0, "EQUAL")

        # 判断趋势方向和持续时间
        trend_dir = 1 if ma20[-1] > ma20[0] else -1
        trend_duration = 0
        for i in range(len(ma20) - 1, 0, -1):
            if (ma20[i] - ma20[i - 1]) * trend_dir >= 0:
                trend_duration += 1
            else:
                break

        # 历史平均趋势持续时间
        all_trends = []
        dir_changes = 0
        current_dir = 1 if ma20[0] > 0 else -1
        current_len = 1
        for i in range(1, len(ma20)):
            d = 1 if ma20[i] > ma20[i - 1] else -1
            if d == current_dir:
                current_len += 1
            else:
                all_trends.append(current_len)
                current_dir = d
                current_len = 1
        all_trends.append(current_len)
        avg_trend = np.mean(all_trends) if all_trends else 10

        # 趋势老化：持续时间超过历史均值的1.5倍
        aging_ratio = trend_duration / max(avg_trend, 1)
        cycle_tension = 0.0
        if aging_ratio > 2.0:
            cycle_tension = min(aging_ratio / 3.0, 1.0)
            dominant = "BEAR" if trend_dir > 0 else "BULL"  # 老化趋势 → 反转预警
        elif aging_ratio > 1.5:
            cycle_tension = min(aging_ratio / 2.5, 0.6)
            dominant = "BEAR" if trend_dir > 0 else "BULL"
        else:
            cycle_tension = 0.15
            dominant = "BULL" if trend_dir > 0 else "BEAR"

        return ContradictionDimension(
            dim_id="C6_cycle",
            name="周期矛盾",
            thesis=f"当前趋势持续{trend_duration}根K线 (方向={'上行' if trend_dir > 0 else '下行'})",
            antithesis=f"历史均值{avg_trend:.0f}根，老化系数{aging_ratio:.2f}",
            tension=cycle_tension,
            dominant_side=dominant,
            evidence=f"trend_duration={trend_duration} avg={avg_trend:.0f} aging={aging_ratio:.2f}",
        )

    # ================================================================
    # 维度7：结构矛盾 — 支撑阻力位突破/假突破
    # ================================================================
    def _dim_structure(self, closes, highs, lows, snapshot) -> ContradictionDimension:
        """结构矛盾：价格在关键位置的表现"""
        if len(closes) < self.STRUCTURE_LOOKBACK:
            return ContradictionDimension("C7_structure", "结构矛盾", "", "", 0.0, "EQUAL")

        window = closes[-self.STRUCTURE_LOOKBACK:]
        resistance = np.max(window[:-1])  # 排除当前K线
        support = np.min(window[:-1])
        current = closes[-1]

        range_size = resistance - support
        if range_size <= 0:
            return ContradictionDimension("C7_structure", "结构矛盾", "", "", 0.0, "EQUAL")

        # 价格在区间中的位置
        position = (current - support) / range_size  # 0=支撑, 1=阻力

        struct_tension = 0.0
        if position > 0.95:
            # 突破阻力
            struct_tension = 0.7
            dominant = "BULL"
            evidence = f"突破阻力位 {resistance:.2f}，当前位置{position:.2f}"
        elif position < 0.05:
            # 跌破支撑
            struct_tension = 0.7
            dominant = "BEAR"
            evidence = f"跌破支撑位 {support:.2f}，当前位置{position:.2f}"
        elif position > 0.85:
            # 接近阻力，假突破风险
            struct_tension = 0.4
            dominant = "BEAR"
            evidence = f"接近阻力位 {resistance:.2f}，假突破风险"
        elif position < 0.15:
            # 接近支撑
            struct_tension = 0.4
            dominant = "BULL"
            evidence = f"接近支撑位 {support:.2f}，可能反弹"
        else:
            struct_tension = 0.1
            dominant = "EQUAL"
            evidence = f"区间中部 position={position:.2f}"

        return ContradictionDimension(
            dim_id="C7_structure",
            name="结构矛盾",
            thesis=f"当前价格{current:.2f}",
            antithesis=f"阻力{resistance:.2f} 支撑{support:.2f}",
            tension=struct_tension,
            dominant_side=dominant,
            evidence=evidence,
        )

    # ================================================================
    # 创伤信号检测（强迫性重复）
    # ================================================================
    def record_decision(self, inst_id: str, direction: str, was_correct: bool, ts: str = ""):
        """记录决策结果，用于强迫性重复检测"""
        if inst_id not in self._trauma_tracker:
            self._trauma_tracker[inst_id] = []
        self._trauma_tracker[inst_id].append({
            "direction": direction,
            "correct": was_correct,
            "ts": ts,
        })
        # 只保留最近20条
        if len(self._trauma_tracker[inst_id]) > 20:
            self._trauma_tracker[inst_id] = self._trauma_tracker[inst_id][-20:]

    def _check_trauma(self, inst_id: str, current_bias: float) -> bool:
        """检测强迫性重复：连续3次同方向错误"""
        if inst_id not in self._trauma_tracker:
            return False

        history = self._trauma_tracker[inst_id]
        if len(history) < 3:
            return False

        recent = history[-3:]
        # 连续3次同方向且都错
        directions = [d["direction"] for d in recent]
        all_wrong = all(not d["correct"] for d in recent)
        same_direction = len(set(directions)) == 1

        if all_wrong and same_direction:
            logger.warning(
                f"[A0] 创伤信号检测: {inst_id} 连续3次{directions[0]}方向错误，"
                f"触发强迫性重复预警"
            )
            return True

        return False

    def _calc_rsi(self, closes: np.ndarray, period: int = 14) -> float:
        """计算RSI"""
        if len(closes) < period + 1:
            return 50.0
        deltas = np.diff(closes)
        gains = np.where(deltas > 0, deltas, 0)
        losses = np.where(deltas < 0, -deltas, 0)
        avg_gain = np.mean(gains[-period:])
        avg_loss = np.mean(losses[-period:])
        if avg_loss == 0:
            return 100.0
        rs = avg_gain / avg_loss
        return 100.0 - (100.0 / (1.0 + rs))
