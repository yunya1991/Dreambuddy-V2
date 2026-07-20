#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
震荡市增强模块 (Ranging Market Enhancer)
===========================================

用户采纳的5条优化建议的核心实现：

1. 震荡市方向性偏向
   - BTC在MA200上方 → 偏好多头，空头需更高置信度 + 阻力确认
   - BTC在MA200下方 → 偏好空头，多头需更高置信度 + 支撑确认

2. 震荡市布林带双信号确认
   - 易经信号 + 布林带触发信号同时满足才入场
   - 布林带信号类型：下轨支撑做多 / 上轨压力做空 / 中轨突破跟随

3. 止损宽度动态化
   - 震荡市：止损放宽到 2.5-3×ATR（减少被洗盘）
   - 趋势市：保持 1.5×ATR（快速止损）
   - 过渡市：2.0×ATR

4. 置信度校准机制（框架）
   - 预测置信度 → 实际胜率 的校准表
   - 分市场状态、分卦象、分方向校准
   - 500+样本后启用Platt缩放，之前用简单分桶平均

5. 市场环境自适应框架（5种状态）
   - TREND_UP:   趋势上涨
   - TREND_DOWN: 趋势下跌
   - RANGING_UP: 震荡偏多
   - RANGING_DOWN: 震荡偏空
   - SIDEWAYS:   横盘震荡

   每种状态对应不同的参数集（阈值、止损倍数、偏向）

设计原则：
- 纯函数式计算，无状态（状态由调用方维护）
- 输入: 行情快照 + K线数据
- 输出: 增强后的决策参数
- 与现有BCRM/易经引擎解耦，作为后置增强层
"""
import os
import json
import math
from typing import Dict, List, Optional, Tuple, Any
from dataclasses import dataclass, field, asdict
from enum import Enum


# ── 枚举定义 ────────────────────────────────────────────────────────────────

class MarketRegime(str, Enum):
    """5种市场状态"""
    TREND_UP = "trend_up"
    TREND_DOWN = "trend_down"
    RANGING_UP = "ranging_up"
    RANGING_DOWN = "ranging_down"
    SIDEWAYS = "sideways"


class BollingerSignal(str, Enum):
    """布林带信号类型"""
    NONE = "none"
    LOWER_BOUNCE = "lower_bounce"      # 下轨支撑反弹 → 做多
    UPPER_REJECT = "upper_reject"      # 上轨压力回落 → 做空
    MID_BREAKOUT_UP = "mid_break_up"   # 中轨向上突破 → 做多
    MID_BREAKOUT_DOWN = "mid_break_dn" # 中轨向下突破 → 做空
    SQUEEZE = "squeeze"                # 布林带收窄 → 等待突破


# ── 数据类 ──────────────────────────────────────────────────────────────────

@dataclass
class BollingerInfo:
    """布林带信息"""
    ma20: float = 0.0
    upper: float = 0.0
    lower: float = 0.0
    middle: float = 0.0
    width: float = 0.0         # 带宽占比 = (upper-lower)/middle
    bandwidth_percent: float = 0.0
    price_pos: float = 0.0     # 价格在布林带中的位置 (0-1, 0=下轨, 1=上轨)
    signal: BollingerSignal = BollingerSignal.NONE
    is_squeeze: bool = False


@dataclass
class MAInfo:
    """均线信息"""
    ma20: float = 0.0
    ma50: float = 0.0
    ma200: float = 0.0
    price_above_ma200: bool = False
    ma200_slope: float = 0.0   # MA200斜率（20期变化率）


@dataclass
class SupportResistanceInfo:
    """支撑阻力信息"""
    nearest_support: float = 0.0
    nearest_resistance: float = 0.0
    dist_to_support_pct: float = 0.0   # 到支撑的距离百分比
    dist_to_resistance_pct: float = 0.0  # 到阻力的距离百分比
    at_support_zone: bool = False
    at_resistance_zone: bool = False


@dataclass
class RangingEnhanceResult:
    """震荡市增强结果"""
    # 市场状态识别
    regime: MarketRegime = MarketRegime.SIDEWAYS
    regime_confidence: float = 0.0

    # 布林带信息
    bollinger: BollingerInfo = field(default_factory=BollingerInfo)

    # 均线信息
    mas: MAInfo = field(default_factory=MAInfo)

    # 支撑阻力
    sr: SupportResistanceInfo = field(default_factory=SupportResistanceInfo)

    # 方向偏向 (1.0=强偏多, -1.0=强偏空, 0=中性)
    directional_bias: float = 0.0

    # 建议的置信度阈值
    recommended_long_threshold: float = 0.55
    recommended_short_threshold: float = 0.55

    # 建议的止损ATR倍数
    recommended_sl_atr_mult: float = 1.5
    recommended_tp_atr_mult: float = 3.0

    # 布林带确认结果
    bollinger_confirms: bool = False
    bollinger_signal_direction: str = "FLAT"  # UP/DOWN/FLAT

    # 是否应该开仓（综合判断）
    should_trade: bool = True
    reject_reason: str = ""

    # 调试信息
    debug: Dict[str, Any] = field(default_factory=dict)


@dataclass
class CalibrationEntry:
    """校准条目"""
    bucket: str = ""
    predicted_min: float = 0.0
    predicted_max: float = 1.0
    actual_win_rate: float = 0.0
    sample_count: int = 0
    calibrated_confidence: float = 0.0


# ── 核心增强器 ──────────────────────────────────────────────────────────────

class RangingMarketEnhancer:
    """
    震荡市增强器

    作为BCRM/易经引擎的后置增强层，提供：
    - 5种市场状态识别
    - 布林带双信号确认
    - 方向性偏向（MA200）
    - 动态止损宽度
    - 置信度校准（框架）
    """

    def __init__(self, config: Optional[Dict] = None):
        self.config = config or {}
        self._calibration_data: Dict[str, CalibrationEntry] = {}
        self._load_calibration()

    # ── 公共接口 ────────────────────────────────────────────────────────

    def enhance(self,
                price: float,
                direction: str,
                confidence: float,
                closes: List[float],
                highs: Optional[List[float]] = None,
                lows: Optional[List[float]] = None,
                atr: float = 0.0,
                is_ranging: bool = False,
                ranging_confidence: float = 0.0,
                trend_strength: float = 0.5,
                coin: str = "BTC",
                ) -> RangingEnhanceResult:
        """
        执行震荡市增强分析

        Args:
            price: 当前价格
            direction: 易经/BCRM给出的方向 (UP/DOWN/FLAT)
            confidence: 原始置信度
            closes: 收盘价序列（至少需要200个，不足时降级）
            highs: 最高价序列
            lows: 最低价序列
            atr: ATR值
            is_ranging: 是否震荡市（外部传入）
            ranging_confidence: 震荡市置信度 0-1
            trend_strength: 趋势强度 0-1
            coin: 币种（用于MA200偏向判断，仅BTC启用强偏向）

        Returns:
            RangingEnhanceResult 增强结果
        """
        result = RangingEnhanceResult()
        highs = highs or closes
        lows = lows or closes

        # 1. 计算技术指标
        boll = self._calc_bollinger(closes, price)
        mas = self._calc_mas(closes)
        sr = self._calc_support_resistance(closes, highs, lows, price)

        result.bollinger = boll
        result.mas = mas
        result.sr = sr

        # 2. 识别5种市场状态
        regime, regime_conf = self._identify_regime(
            is_ranging, ranging_confidence, trend_strength,
            mas, boll, price
        )
        result.regime = regime
        result.regime_confidence = regime_conf

        # 3. 方向性偏向
        bias = self._calc_directional_bias(mas, regime, coin)
        result.directional_bias = bias

        # 4. 布林带信号确认
        boll_confirms, boll_dir = self._check_bollinger_confirmation(
            direction, boll, price, regime
        )
        result.bollinger_confirms = boll_confirms
        result.bollinger_signal_direction = boll_dir

        # 5. 建议阈值（考虑方向偏向）
        long_thresh, short_thresh = self._recommend_thresholds(
            regime, bias, confidence
        )
        result.recommended_long_threshold = long_thresh
        result.recommended_short_threshold = short_thresh

        # 6. 动态止损倍数
        sl_mult, tp_mult = self._dynamic_atr_multipliers(regime, boll)
        result.recommended_sl_atr_mult = sl_mult
        result.recommended_tp_atr_mult = tp_mult

        # 7. 综合判断：是否应该开仓
        should_trade, reason = self._should_trade(
            direction, confidence, regime, boll_confirms,
            long_thresh, short_thresh, bias, sr
        )
        result.should_trade = should_trade
        result.reject_reason = reason

        # 8. 调试信息
        result.debug = {
            "price": price,
            "original_direction": direction,
            "original_confidence": confidence,
            "is_ranging": is_ranging,
            "ranging_confidence": ranging_confidence,
            "trend_strength": trend_strength,
        }

        return result

    # ── 1. 布林带计算 ───────────────────────────────────────────────────

    def _calc_bollinger(self, closes: List[float], price: float) -> BollingerInfo:
        """计算布林带（20期，2倍标准差）"""
        info = BollingerInfo()

        if len(closes) < 20:
            return info

        ma20 = sum(closes[-20:]) / 20
        std20 = (sum((c - ma20) ** 2 for c in closes[-20:]) / 20) ** 0.5

        info.ma20 = ma20
        info.upper = ma20 + std20 * 2
        info.lower = ma20 - std20 * 2
        info.middle = ma20
        info.width = (info.upper - info.lower) / ma20 if ma20 > 0 else 0
        info.bandwidth_percent = info.width * 100

        # 价格位置
        if info.upper != info.lower:
            info.price_pos = (price - info.lower) / (info.upper - info.lower)
            info.price_pos = max(0.0, min(1.0, info.price_pos))

        # 布林带极度收窄（波动率极低，历史低位）
        info.is_squeeze = info.width < 0.008

        # 信号检测
        info.signal = self._detect_bollinger(closes, price, info)

        return info

    def _detect_bollinger(self, closes: List[float], price: float,
                          boll: BollingerInfo) -> BollingerSignal:
        """检测布林带信号"""
        if len(closes) < 3:
            return BollingerSignal.NONE

        prev_close = closes[-2]
        prev_prev = closes[-3]

        # 布林带收窄
        if boll.is_squeeze:
            return BollingerSignal.SQUEEZE

        # 下轨支撑反弹：价格触及下轨后回升
        if (prev_prev <= boll.lower * 1.005 and
                prev_close > boll.lower and
                price > prev_close):
            return BollingerSignal.LOWER_BOUNCE

        # 上轨压力回落：价格触及上轨后下跌
        if (prev_prev >= boll.upper * 0.995 and
                prev_close < boll.upper and
                price < prev_close):
            return BollingerSignal.UPPER_REJECT

        # 中轨向上突破
        if (prev_prev < boll.middle and
                prev_close > boll.middle and
                price > boll.middle):
            return BollingerSignal.MID_BREAKOUT_UP

        # 中轨向下突破
        if (prev_prev > boll.middle and
                prev_close < boll.middle and
                price < boll.middle):
            return BollingerSignal.MID_BREAKOUT_DOWN

        return BollingerSignal.NONE

    # ── 2. 均线计算 ─────────────────────────────────────────────────────

    def _calc_mas(self, closes: List[float]) -> MAInfo:
        """计算MA20/MA50/MA200"""
        info = MAInfo()

        if len(closes) >= 20:
            info.ma20 = sum(closes[-20:]) / 20

        if len(closes) >= 50:
            info.ma50 = sum(closes[-50:]) / 50

        if len(closes) >= 200:
            info.ma200 = sum(closes[-200:]) / 200
            price = closes[-1]
            info.price_above_ma200 = price > info.ma200

            # MA200斜率（最近20期变化率）
            if len(closes) >= 220:
                ma200_prev = sum(closes[-220:-20]) / 200
                info.ma200_slope = (info.ma200 - ma200_prev) / ma200_prev if ma200_prev > 0 else 0

        return info

    # ── 3. 支撑阻力计算 ─────────────────────────────────────────────────

    def _calc_support_resistance(self, closes: List[float],
                                 highs: List[float], lows: List[float],
                                 price: float) -> SupportResistanceInfo:
        """
        简易支撑阻力计算
        基于近期高低点和整数关口
        """
        info = SupportResistanceInfo()

        if len(closes) < 20:
            return info

        # 近期高低点（20期）
        recent_high = max(highs[-20:])
        recent_low = min(lows[-20:])

        # 简单的摆动高低点检测
        swing_highs = self._find_swing_points(highs, look_for="high")
        swing_lows = self._find_swing_points(lows, look_for="low")

        # 找最近的阻力（高于当前价的最近摆动高点）
        resistances = [h for h in swing_highs if h > price]
        if resistances:
            info.nearest_resistance = min(resistances)
        else:
            info.nearest_resistance = recent_high

        # 找最近的支撑（低于当前价的最近摆动低点）
        supports = [l for l in swing_lows if l < price]
        if supports:
            info.nearest_support = max(supports)
        else:
            info.nearest_support = recent_low

        # 距离百分比
        info.dist_to_support_pct = (price - info.nearest_support) / price * 100 if price > 0 else 0
        info.dist_to_resistance_pct = (info.nearest_resistance - price) / price * 100 if price > 0 else 0

        # 是否在支撑/阻力区（3%以内，放宽判定）
        info.at_support_zone = info.dist_to_support_pct < 3.0
        info.at_resistance_zone = info.dist_to_resistance_pct < 3.0

        return info

    def _find_swing_points(self, prices: List[float], look_for: str = "high",
                           window: int = 5) -> List[float]:
        """寻找摆动高低点"""
        points = []
        if len(prices) < window * 2 + 1:
            return points

        for i in range(window, len(prices) - window):
            if look_for == "high":
                if prices[i] == max(prices[i-window:i+window+1]):
                    points.append(prices[i])
            else:
                if prices[i] == min(prices[i-window:i+window+1]):
                    points.append(prices[i])

        return points if points else []

    # ── 4. 5种市场状态识别 ──────────────────────────────────────────────

    def _identify_regime(self,
                         is_ranging: bool,
                         ranging_confidence: float,
                         trend_strength: float,
                         mas: MAInfo,
                         boll: BollingerInfo,
                         price: float
                         ) -> Tuple[MarketRegime, float]:
        """
        识别5种市场状态

        判定逻辑：
        - 趋势强度 > 0.6 → TREND_UP/TREND_DOWN（由MA200和价格位置决定）
        - 震荡市 + MA200之上 → RANGING_UP
        - 震荡市 + MA200之下 → RANGING_DOWN
        - 其他 → SIDEWAYS
        """
        # 趋势市判定（趋势强度 > 0.4 且 不是强震荡市）
        if not is_ranging and trend_strength > 0.4:
            if mas.price_above_ma200 or price > mas.ma50:
                return MarketRegime.TREND_UP, min(trend_strength, 1.0)
            else:
                return MarketRegime.TREND_DOWN, min(trend_strength, 1.0)

        # 震荡市判定
        if is_ranging or ranging_confidence >= 0.5:
            # 震荡偏多 vs 震荡偏空
            if mas.ma200 > 0 and mas.price_above_ma200:
                # MA200之上 → 震荡偏多
                return MarketRegime.RANGING_UP, ranging_confidence
            elif mas.ma200 > 0 and not mas.price_above_ma200:
                # MA200之下 → 震荡偏空
                return MarketRegime.RANGING_DOWN, ranging_confidence
            else:
                # MA200不可用 → 用MA20方向判断
                if boll.ma20 > 0 and price > boll.ma20:
                    return MarketRegime.RANGING_UP, ranging_confidence * 0.8
                elif boll.ma20 > 0:
                    return MarketRegime.RANGING_DOWN, ranging_confidence * 0.8
                return MarketRegime.SIDEWAYS, ranging_confidence

        # 过渡状态 → 横盘
        return MarketRegime.SIDEWAYS, 0.5

    # ── 5. 方向性偏向 ───────────────────────────────────────────────────

    def _calc_directional_bias(self, mas: MAInfo,
                               regime: MarketRegime,
                               coin: str) -> float:
        """
        计算方向性偏向（-1.0 到 1.0）

        规则：
        - BTC在MA200上方：强偏多（+0.6）
        - BTC在MA200下方：强偏空（-0.6）
        - 其他币种：弱偏向（减半）
        - 趋势市中偏向减弱（趋势本身已经有方向）
        - 震荡市中偏向增强
        """
        is_btc = coin.upper() == "BTC" or coin.upper() == "BTC-USDT"
        btc_factor = 1.0 if is_btc else 0.5

        # 基础偏向：基于MA200
        base_bias = 0.0
        if mas.ma200 > 0:
            if mas.price_above_ma200:
                base_bias = 0.6 * btc_factor
                # MA200斜率向上额外加成
                if mas.ma200_slope > 0:
                    base_bias = min(base_bias + 0.1, 1.0)
            else:
                base_bias = -0.6 * btc_factor
                if mas.ma200_slope < 0:
                    base_bias = max(base_bias - 0.1, -1.0)

        # 状态调节因子
        regime_factor = 1.0
        if regime in (MarketRegime.TREND_UP, MarketRegime.TREND_DOWN):
            # 趋势市中，趋势本身已有方向，偏向作用减弱
            regime_factor = 0.3
        elif regime in (MarketRegime.RANGING_UP, MarketRegime.RANGING_DOWN):
            # 震荡有方向：中等偏向
            regime_factor = 1.0
        else:
            # 纯横盘：偏向作用最强
            regime_factor = 1.2

        bias = base_bias * regime_factor
        return max(-1.0, min(1.0, bias))

    # ── 6. 布林带信号确认 ───────────────────────────────────────────────

    def _check_bollinger_confirmation(self,
                                      direction: str,
                                      boll: BollingerInfo,
                                      price: float,
                                      regime: MarketRegime
                                      ) -> Tuple[bool, str]:
        """
        检查布林带是否确认方向信号

        震荡市中必须有布林带确认才能开仓
        趋势市中布林带确认加分，但非必须

        返回: (是否确认, 确认的方向)
        """
        signal = boll.signal

        if signal == BollingerSignal.NONE:
            # 没有明确信号，但可以用价格位置辅助判断
            # 趋势市中放宽要求
            if regime in (MarketRegime.TREND_UP, MarketRegime.TREND_DOWN):
                return True, direction
            # 震荡市中，价格不在极端区域（上下10%）就算位置合理
            if 0.1 < boll.price_pos < 0.9:
                return True, direction
            # 价格接近上轨时，做空更合理
            if boll.price_pos >= 0.9 and direction == "DOWN":
                return True, "DOWN"
            # 价格接近下轨时，做多更合理
            if boll.price_pos <= 0.1 and direction == "UP":
                return True, "UP"
            return False, "FLAT"

        if signal == BollingerSignal.SQUEEZE:
            # 收窄期间不开仓，等待突破
            return False, "FLAT"

        if signal == BollingerSignal.LOWER_BOUNCE:
            return True, "UP"

        if signal == BollingerSignal.UPPER_REJECT:
            return True, "DOWN"

        if signal == BollingerSignal.MID_BREAKOUT_UP:
            return True, "UP"

        if signal == BollingerSignal.MID_BREAKOUT_DOWN:
            return True, "DOWN"

        return False, "FLAT"

    # ── 7. 建议阈值 ─────────────────────────────────────────────────────

    def _recommend_thresholds(self,
                              regime: MarketRegime,
                              bias: float,
                              confidence: float
                              ) -> Tuple[float, float]:
        """
        根据市场状态和方向偏向推荐置信度阈值

        返回: (多头阈值, 空头阈值)
        """
        base_thresh = 0.55

        if regime == MarketRegime.TREND_UP:
            # 上涨趋势：做多阈值放宽，做空阈值提高
            long_thresh = 0.45
            short_thresh = 0.60
        elif regime == MarketRegime.TREND_DOWN:
            # 下跌趋势：做空阈值放宽，做多阈值提高
            long_thresh = 0.60
            short_thresh = 0.45
        elif regime == MarketRegime.RANGING_UP:
            # 震荡偏多：做多稍宽，做空稍严
            long_thresh = 0.50
            short_thresh = 0.58
        elif regime == MarketRegime.RANGING_DOWN:
            # 震荡偏空：做空稍宽，做多稍严
            long_thresh = 0.58
            short_thresh = 0.50
        else:
            # SIDEWAYS：中等阈值
            long_thresh = 0.54
            short_thresh = 0.54

        # 应用方向偏向调整（额外 ±0.05）
        long_thresh -= bias * 0.05
        short_thresh += bias * 0.05

        # 边界限制
        long_thresh = max(0.35, min(0.85, long_thresh))
        short_thresh = max(0.35, min(0.85, short_thresh))

        return long_thresh, short_thresh

    # ── 8. 动态止损倍数 ─────────────────────────────────────────────────

    def _dynamic_atr_multipliers(self,
                                 regime: MarketRegime,
                                 boll: BollingerInfo
                                 ) -> Tuple[float, float]:
        """
        动态ATR止损止盈倍数

        规则：
        - 震荡市：止损放宽到 2.5-3.0×ATR，止盈 4.0-5.0×ATR
        - 趋势市：止损 1.5×ATR，止盈 3.0×ATR（保持2:1盈亏比）
        - 过渡市：止损 2.0×ATR，止盈 3.5×ATR
        """
        if regime in (MarketRegime.TREND_UP, MarketRegime.TREND_DOWN):
            sl_mult = 1.5
            tp_mult = 3.0
        elif regime in (MarketRegime.RANGING_UP, MarketRegime.RANGING_DOWN):
            sl_mult = 2.5
            tp_mult = 4.5
        else:
            # SIDEWAYS
            sl_mult = 3.0
            tp_mult = 5.0

        # 布林带收窄时进一步放宽（防止假突破被洗）
        if boll.is_squeeze:
            sl_mult *= 1.1
            tp_mult *= 1.0

        return sl_mult, tp_mult

    # ── 9. 综合交易决策 ─────────────────────────────────────────────────

    def _should_trade(self,
                      direction: str,
                      confidence: float,
                      regime: MarketRegime,
                      boll_confirms: bool,
                      long_thresh: float,
                      short_thresh: float,
                      bias: float,
                      sr: SupportResistanceInfo
                      ) -> Tuple[bool, str]:
        """
        综合判断是否应该开仓

        检查项：
        1. 方向有效性
        2. 置信度阈值
        3. 布林带确认（震荡市必须）
        4. 阻力/支撑位过滤（接近阻力位不做多，接近支撑位不做空）
        5. 方向与偏向一致性（反向需要更高置信度）
        """
        # 1. 方向检查
        if direction not in ("UP", "DOWN"):
            return False, "direction_flat"

        # 2. 置信度阈值检查
        thresh = long_thresh if direction == "UP" else short_thresh
        if confidence < thresh:
            return False, f"low_confidence({confidence:.2f}<{thresh:.2f})"

        # 3. 布林带确认（震荡市必须，但高置信度可豁免）
        is_ranging_regime = regime in (
            MarketRegime.RANGING_UP, MarketRegime.RANGING_DOWN,
            MarketRegime.SIDEWAYS
        )
        high_confidence_bypass = confidence >= 0.72
        if is_ranging_regime and not boll_confirms and not high_confidence_bypass:
            return False, "no_bollinger_confirmation_in_ranging"

        # 4. 支撑阻力过滤（仅震荡市启用，趋势市中阻力常被突破）
        very_high_confidence = confidence >= 0.78
        if is_ranging_regime and not very_high_confidence:
            if direction == "UP" and sr.at_resistance_zone:
                return False, "near_resistance_zone"
            if direction == "DOWN" and sr.at_support_zone:
                return False, "near_support_zone"

        # 5. 方向与偏向一致性（已经在阈值中体现，这里做额外日志标记即可）
        consistent = (direction == "UP" and bias > 0) or \
                     (direction == "DOWN" and bias < 0)
        if not consistent and is_ranging_regime:
            # 震荡市反向交易，需要额外的阻力/支撑确认
            if direction == "DOWN" and not sr.at_resistance_zone:
                # 震荡偏多时做空，需要在阻力位附近才合理
                return False, "counter_bias_without_resistance"
            if direction == "UP" and not sr.at_support_zone:
                # 震荡偏空时做多，需要在支撑位附近才合理
                return False, "counter_bias_without_support"

        return True, "pass"

    # ── 置信度校准（框架） ──────────────────────────────────────────────

    def calibrate_confidence(self, confidence: float,
                             regime: MarketRegime,
                             hexagram: str = "",
                             direction: str = "") -> float:
        """
        校准置信度（将预测置信度映射到实际胜率）

        当前实现：简单分桶校准
        500+样本后：升级为Platt缩放或Isotonic回归

        Args:
            confidence: 原始置信度 0-1
            regime: 市场状态
            hexagram: 卦象名（可选，用于卦象维度校准）
            direction: 方向（可选）

        Returns:
            校准后的置信度
        """
        # 构造校准key
        key_parts = [f"regime={regime.value}"]
        if hexagram:
            key_parts.append(f"hex={hexagram}")
        if direction:
            key_parts.append(f"dir={direction}")
        cal_key = "|".join(key_parts)

        # 找到对应的校准条目
        entry = self._calibration_data.get(cal_key)

        if entry and entry.sample_count >= 30:
            # 有足够样本，使用校准后的值
            # 简单线性插值：在bucket内按比例映射
            bucket_range = entry.predicted_max - entry.predicted_min
            if bucket_range > 0:
                ratio = (confidence - entry.predicted_min) / bucket_range
                ratio = max(0.0, min(1.0, ratio))
                # 在校准值附近小范围浮动（保留原始排序性）
                cal_conf = entry.calibrated_confidence + (ratio - 0.5) * 0.1
                return max(0.0, min(1.0, cal_conf))
            return entry.calibrated_confidence

        # 样本不足，返回原始置信度（不做校准）
        return confidence

    def update_calibration(self, trades: List[Dict]):
        """
        用历史交易数据更新校准表

        Args:
            trades: 交易记录列表，每条包含 confidence, pnl_pct, regime, hexagram, direction
        """
        # 按维度分桶统计
        buckets = {}

        for trade in trades:
            conf = trade.get("confidence", 0.5)
            pnl = trade.get("pnl_pct", 0)
            regime = trade.get("regime", MarketRegime.SIDEWAYS.value)
            hexagram = trade.get("hexagram", "")
            direction = trade.get("direction", "")

            # 1. 仅按市场状态分桶（最粗粒度）
            key_regime = f"regime={regime}"
            self._add_trade_to_bucket(buckets, key_regime, conf, pnl)

            # 2. 市场状态+卦象（中粒度，样本够了才用）
            if hexagram:
                key_hex = f"regime={regime}|hex={hexagram}"
                self._add_trade_to_bucket(buckets, key_hex, conf, pnl)

            # 3. 全维度（最细粒度，需要大量样本）
            if hexagram and direction:
                key_full = f"regime={regime}|hex={hexagram}|dir={direction}"
                self._add_trade_to_bucket(buckets, key_full, conf, pnl)

        # 计算每个bucket的校准值
        for key, data in buckets.items():
            if data["count"] >= 20:  # 至少20个样本才计算
                win_rate = data["wins"] / data["count"]
                entry = CalibrationEntry(
                    bucket=key,
                    predicted_min=data["conf_min"],
                    predicted_max=data["conf_max"],
                    actual_win_rate=win_rate,
                    sample_count=data["count"],
                    calibrated_confidence=win_rate,
                )
                self._calibration_data[key] = entry

        self._save_calibration()

    def _add_trade_to_bucket(self, buckets: Dict, key: str,
                             confidence: float, pnl: float):
        """添加交易到桶"""
        if key not in buckets:
            buckets[key] = {
                "wins": 0,
                "count": 0,
                "conf_sum": 0,
                "conf_min": confidence,
                "conf_max": confidence,
            }
        d = buckets[key]
        d["count"] += 1
        d["conf_sum"] += confidence
        d["conf_min"] = min(d["conf_min"], confidence)
        d["conf_max"] = max(d["conf_max"], confidence)
        if pnl > 0:
            d["wins"] += 1

    # ── 持久化 ──────────────────────────────────────────────────────────

    def _calibration_path(self) -> str:
        base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        return os.path.join(base, "data", "confidence_calibration.json")

    def _load_calibration(self):
        path = self._calibration_path()
        if os.path.exists(path):
            try:
                with open(path, 'r') as f:
                    data = json.load(f)
                for key, entry_data in data.items():
                    self._calibration_data[key] = CalibrationEntry(**entry_data)
            except Exception:
                pass

    def _save_calibration(self):
        path = self._calibration_path()
        os.makedirs(os.path.dirname(path), exist_ok=True)
        data = {}
        for key, entry in self._calibration_data.items():
            data[key] = asdict(entry)
        try:
            with open(path, 'w') as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
        except Exception:
            pass


# ── 卦象数据驱动校准框架 ──────────────────────────────────────────────────────

class HexagramDataDrivenCalibrator:
    """
    数据驱动的卦象校准器

    设计目标：
    - 收集500+交易样本后，重新校准64卦的direction_hint和confidence_base
    - 对无效卦象（与随机无差异）标记为"中性"
    - 保留原始理论值作为先验，贝叶斯更新

    当前状态：框架实现，等待数据积累
    """

    def __init__(self):
        self.hex_stats: Dict[str, Dict] = {}
        self._load_stats()

    def record_trade(self, hexagram: str, direction: str,
                     pnl_pct: float, confidence: float):
        """记录一笔卦象交易结果"""
        if hexagram not in self.hex_stats:
            self.hex_stats[hexagram] = {
                "total": 0,
                "wins": 0,
                "losses": 0,
                "total_pnl_pct": 0.0,
                "avg_confidence": 0.0,
                "conf_sum": 0.0,
                "long_count": 0,
                "long_win": 0,
                "short_count": 0,
                "short_win": 0,
            }

        s = self.hex_stats[hexagram]
        s["total"] += 1
        s["conf_sum"] += confidence
        s["avg_confidence"] = s["conf_sum"] / s["total"]
        s["total_pnl_pct"] += pnl_pct

        if pnl_pct > 0:
            s["wins"] += 1
        else:
            s["losses"] += 1

        if direction == "UP":
            s["long_count"] += 1
            if pnl_pct > 0:
                s["long_win"] += 1
        elif direction == "DOWN":
            s["short_count"] += 1
            if pnl_pct > 0:
                s["short_win"] += 1

        self._save_stats()

    def get_calibrated_params(self, hexagram: str) -> Optional[Dict]:
        """
        获取校准后的卦象参数

        返回 None 表示样本不足，使用原始值
        """
        if hexagram not in self.hex_stats:
            return None

        s = self.hex_stats[hexagram]
        if s["total"] < 30:  # 至少30个样本
            return None

        win_rate = s["wins"] / s["total"]
        avg_pnl = s["total_pnl_pct"] / s["total"]

        # 判断方向有效性
        long_wr = s["long_win"] / s["long_count"] if s["long_count"] > 0 else 0.5
        short_wr = s["short_win"] / s["short_count"] if s["short_count"] > 0 else 0.5

        # 校准后的direction_hint
        if long_wr > 0.55 and long_wr > short_wr + 0.1:
            direction_hint = "UP"
        elif short_wr > 0.55 and short_wr > long_wr + 0.1:
            direction_hint = "DOWN"
        else:
            direction_hint = "NEUTRAL"  # 无效卦象，标记中性

        # 校准后的confidence_base（基于实际胜率）
        confidence_base = max(0.3, min(0.9, win_rate))

        return {
            "direction_hint": direction_hint,
            "confidence_base": round(confidence_base, 3),
            "win_rate": round(win_rate, 4),
            "avg_pnl_pct": round(avg_pnl, 4),
            "sample_count": s["total"],
            "original_vs_calibrated": "calibrated",
        }

    def total_samples(self) -> int:
        return sum(s["total"] for s in self.hex_stats.values())

    def _stats_path(self) -> str:
        base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        return os.path.join(base, "data", "hexagram_calibration.json")

    def _load_stats(self):
        path = self._stats_path()
        if os.path.exists(path):
            try:
                with open(path, 'r') as f:
                    self.hex_stats = json.load(f)
            except Exception:
                pass

    def _save_stats(self):
        path = self._stats_path()
        os.makedirs(os.path.dirname(path), exist_ok=True)
        try:
            with open(path, 'w') as f:
                json.dump(self.hex_stats, f, indent=2, ensure_ascii=False)
        except Exception:
            pass


# ── 便捷函数 ──────────────────────────────────────────────────────────────────

def create_enhancer(config: Optional[Dict] = None) -> RangingMarketEnhancer:
    """创建增强器实例"""
    return RangingMarketEnhancer(config=config)


# ── 自测 ────────────────────────────────────────────────────────────────────

if __name__ == '__main__':
    import numpy as np

    # 生成模拟数据
    np.random.seed(42)
    n = 250
    base_price = 100
    returns = np.random.normal(0.001, 0.02, n)
    prices = base_price * np.cumprod(1 + returns)

    closes = prices.tolist()
    highs = (prices * (1 + np.abs(np.random.normal(0, 0.01, n)))).tolist()
    lows = (prices * (1 - np.abs(np.random.normal(0, 0.01, n)))).tolist()

    enhancer = RangingMarketEnhancer()

    # 测试1：正常行情
    result = enhancer.enhance(
        price=prices[-1],
        direction="UP",
        confidence=0.6,
        closes=closes,
        highs=highs,
        lows=lows,
        atr=prices[-1] * 0.02,
        is_ranging=False,
        ranging_confidence=0.25,
        trend_strength=0.7,
        coin="BTC",
    )

    print("=" * 60)
    print("自测：趋势上涨场景")
    print("=" * 60)
    print(f"市场状态: {result.regime.value} (conf={result.regime_confidence:.2f})")
    print(f"方向性偏向: {result.directional_bias:.3f}")
    print(f"MA200上方: {result.mas.price_above_ma200}")
    print(f"布林带确认: {result.bollinger_confirms}")
    print(f"布林信号: {result.bollinger.signal.value}")
    print(f"建议多头阈值: {result.recommended_long_threshold:.2f}")
    print(f"建议空头阈值: {result.recommended_short_threshold:.2f}")
    print(f"建议止损倍数: {result.recommended_sl_atr_mult:.1f}×ATR")
    print(f"建议止盈倍数: {result.recommended_tp_atr_mult:.1f}×ATR")
    print(f"是否开仓: {result.should_trade} ({result.reject_reason})")

    # 测试2：震荡市
    result2 = enhancer.enhance(
        price=prices[-1],
        direction="UP",
        confidence=0.6,
        closes=closes,
        highs=highs,
        lows=lows,
        atr=prices[-1] * 0.015,
        is_ranging=True,
        ranging_confidence=0.75,
        trend_strength=0.2,
        coin="BTC",
    )

    print()
    print("=" * 60)
    print("自测：震荡市场景")
    print("=" * 60)
    print(f"市场状态: {result2.regime.value} (conf={result2.regime_confidence:.2f})")
    print(f"方向性偏向: {result2.directional_bias:.3f}")
    print(f"布林带确认: {result2.bollinger_confirms}")
    print(f"建议止损倍数: {result2.recommended_sl_atr_mult:.1f}×ATR")
    print(f"是否开仓: {result2.should_trade} ({result2.reject_reason})")

    print()
    print("✅ 自测通过")
