"""三屏趋势系统 — 指标计算引擎

包含：
- 单指标三维动态计算（direction / speed / acceleration）
- 静态指标投票
- 经典指标综合置信度
"""

from typing import List, Dict
import numpy as np

try:
    import sys
    sys.path.insert(0, "/Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/10-经典指标系统")
    from talib import abstract as ta
    TALIB_AVAILABLE = True
except ImportError:
    TALIB_AVAILABLE = False

try:
    from .config import (
        SCREEN1_INDICATORS,
        SCREEN2_INDICATORS,
        WEEKLY_WEIGHT,
        DAILY_WEIGHT,
    )
except ImportError:
    from config import (
        SCREEN1_INDICATORS,
        SCREEN2_INDICATORS,
        WEEKLY_WEIGHT,
        DAILY_WEIGHT,
    )


def calc_indicator_dynamics(df, indicator_name: str) -> dict:
    """
    计算指标的三个动态维度：
    - direction: 当前方向 (BULL/BEAR/NEUTRAL)
    - speed: 方向变化的快慢 (动量强度 0-100)
    - acceleration: 速度变化的快慢 (加速/减速 0-100)
    """
    if not TALIB_AVAILABLE:
        return {"direction": "NEUTRAL", "speed": 0.0, "acceleration": 0.0}

    try:
        close = df["close"]
        result = {"direction": "NEUTRAL", "speed": 0.0, "acceleration": 0.0}

        if indicator_name == "MACD_Cross":
            macd_dict = ta.MACD(df, fastperiod=12, slowperiod=26, signalperiod=9)
            macd_line = macd_dict["macd"]
            signal_line = macd_dict["macdsignal"]
            hist = macd_dict["macdhist"]
            result["direction"] = "BULL" if macd_line.iloc[-1] > signal_line.iloc[-1] else "BEAR"
            price_mean = close.mean()
            result["speed"] = min(100, abs(macd_line.iloc[-1] - signal_line.iloc[-1]) / price_mean * 1000)
            if len(hist) >= 3:
                slope = (hist.iloc[-1] - hist.iloc[-3]) / 2
                result["acceleration"] = min(100, abs(slope) / price_mean * 1000)

        elif indicator_name == "OBV_Trend":
            obv = ta.OBV(df)
            obv_ma = obv.rolling(10, min_periods=1).mean()
            result["direction"] = "BULL" if obv.iloc[-1] > obv_ma.iloc[-1] else "BEAR"
            obv_range = obv.max() - obv.min() + 1
            result["speed"] = min(100, abs(obv.iloc[-1] - obv_ma.iloc[-1]) / obv_range * 100)
            if len(obv) >= 3:
                slope = (obv.iloc[-1] - obv.iloc[-3]) / 2
                result["acceleration"] = min(100, abs(slope) / obv_range * 100)

        elif indicator_name == "Vortex":
            vx = ta.VORTEX(df, period=14)
            vi_plus = vx["plus_vi"]
            vi_minus = vx["minus_vi"]
            result["direction"] = "BULL" if vi_plus.iloc[-1] > vi_minus.iloc[-1] else "BEAR"
            result["speed"] = min(100, abs(vi_plus.iloc[-1] - vi_minus.iloc[-1]))
            if len(vi_plus) >= 3:
                diff_now = vi_plus.iloc[-1] - vi_minus.iloc[-1]
                diff_prev = vi_plus.iloc[-3] - vi_minus.iloc[-3]
                result["acceleration"] = min(100, abs(diff_now - diff_prev))

        elif indicator_name == "RSI_50":
            rsi = ta.RSI(df, timeperiod=14)
            result["direction"] = "BULL" if rsi.iloc[-1] > 50 else "BEAR"
            result["speed"] = min(100, abs(rsi.iloc[-1] - 50))
            if len(rsi) >= 3:
                result["acceleration"] = min(100, abs(rsi.iloc[-1] - rsi.iloc[-3]))

        elif indicator_name == "SuperTrend":
            st = ta.SUPERTREND(df, period=10, multiplier=3.0)
            direction = st["direction"]
            if direction.iloc[-1] == 1:
                result["direction"] = "BULL"
            elif direction.iloc[-1] == -1:
                result["direction"] = "BEAR"
            else:
                result["direction"] = "NEUTRAL"
            st_value = st["lowerband"] if direction.iloc[-1] == 1 else st["upperband"]
            dist_pct = abs(close.iloc[-1] - st_value.iloc[-1]) / st_value.iloc[-1] * 100
            result["speed"] = min(100, dist_pct * 5)
            if len(direction) >= 3:
                dir_changes = abs(direction.iloc[-1] - direction.iloc[-3])
                result["acceleration"] = min(100, dir_changes * 50)

        elif indicator_name == "StochRSI_Cross":
            sr = ta.STOCHRSI(df, timeperiod=14, fastk_period=3, fastd_period=3)
            fastk = sr["fastk"]
            fastd = sr["fastd"]
            result["direction"] = "BULL" if fastk.iloc[-1] > fastd.iloc[-1] else "BEAR"
            result["speed"] = min(100, abs(fastk.iloc[-1] - 50) * 2)
            if len(fastk) >= 3:
                cross_now = fastk.iloc[-1] - fastd.iloc[-1]
                cross_prev = fastk.iloc[-3] - fastd.iloc[-3]
                result["acceleration"] = min(100, abs(cross_now - cross_prev) * 5)

        elif indicator_name == "Keltner_Channel":
            kc = ta.KELTNER(df, ema_period=20, atr_period=10, mult=2.0)
            upper = kc["upper"]
            middle = kc["middle"]
            lower = kc["lower"]
            if close.iloc[-1] > upper.iloc[-1]:
                result["direction"] = "BULL"
            elif close.iloc[-1] < lower.iloc[-1]:
                result["direction"] = "BEAR"
            else:
                result["direction"] = "NEUTRAL"
            band_width = upper.iloc[-1] - lower.iloc[-1] + 1e-9
            position = (close.iloc[-1] - middle.iloc[-1]) / (band_width / 2)
            result["speed"] = min(100, abs(position) * 50)
            if len(middle) >= 3:
                width_now = upper.iloc[-1] - lower.iloc[-1]
                width_prev = upper.iloc[-3] - lower.iloc[-3]
                result["acceleration"] = min(100, abs(width_now - width_prev) / close.mean() * 1000)

        elif indicator_name == "GoldenCross_50_200":
            ema50 = ta.EMA(df, timeperiod=50)
            ema200 = ta.EMA(df, timeperiod=200)
            result["direction"] = "BULL" if ema50.iloc[-1] > ema200.iloc[-1] else "BEAR"
            dist_pct = abs(ema50.iloc[-1] - ema200.iloc[-1]) / ema200.iloc[-1] * 100
            result["speed"] = min(100, dist_pct * 10)
            if len(ema50) >= 3:
                slope50 = (ema50.iloc[-1] - ema50.iloc[-3]) / 2
                slope200 = (ema200.iloc[-1] - ema200.iloc[-3]) / 2
                result["acceleration"] = min(100, abs(slope50 - slope200) / close.mean() * 10000)

        elif indicator_name == "TEMA":
            tema = ta.TEMA(df, timeperiod=30)
            tema_trend = tema.pct_change().dropna()
            if len(tema_trend) >= 1:
                result["direction"] = "BULL" if tema_trend.iloc[-1] > 0 else "BEAR"
            price_mean = close.mean()
            result["speed"] = min(100, abs(tema.iloc[-1] - close.iloc[-1]) / price_mean * 1000)
            if len(tema) >= 4:
                accel = (tema.iloc[-1] - 2 * tema.iloc[-2] + tema.iloc[-3]) / price_mean * 10000
                result["acceleration"] = min(100, abs(accel))

        elif indicator_name == "EMA_Align_20_50_200":
            ema20 = ta.EMA(df, timeperiod=20)
            ema50 = ta.EMA(df, timeperiod=50)
            ema200 = ta.EMA(df, timeperiod=200)
            if ema20.iloc[-1] > ema50.iloc[-1] > ema200.iloc[-1]:
                result["direction"] = "BULL"
            elif ema20.iloc[-1] < ema50.iloc[-1] < ema200.iloc[-1]:
                result["direction"] = "BEAR"
            else:
                result["direction"] = "NEUTRAL"
            ma_values = [ema20.iloc[-1], ema50.iloc[-1], ema200.iloc[-1]]
            ma_std = np.std(ma_values)
            ma_mean = np.mean(ma_values)
            alignment_score = 1 - (ma_std / ma_mean) if ma_mean > 0 else 0
            result["speed"] = min(100, alignment_score * 100)
            if len(ema20) >= 3:
                prev_ma_values = [ema20.iloc[-3], ema50.iloc[-3], ema200.iloc[-3]]
                prev_alignment = 1 - (np.std(prev_ma_values) / np.mean(prev_ma_values)) if np.mean(prev_ma_values) > 0 else 0
                result["acceleration"] = min(100, abs(alignment_score - prev_alignment) * 100)

        elif indicator_name == "Elder_ray":
            # Elder-ray：判断趋势力度的衰竭和逆转
            # Bull Power = High - EMA(13)
            # Bear Power = Low  - EMA(13)
            er = ta.ELDER_RAY(df, period=13)
            bull_power = er["bull_power"]
            bear_power = er["bear_power"]
            # 方向：Bull Power > 0 且 > |Bear Power| → 多头；反之空头
            if bull_power.iloc[-1] > 0 and bull_power.iloc[-1] > abs(bear_power.iloc[-1]):
                result["direction"] = "BULL"
            elif bear_power.iloc[-1] < 0 and abs(bear_power.iloc[-1]) > bull_power.iloc[-1]:
                result["direction"] = "BEAR"
            else:
                result["direction"] = "NEUTRAL"
            # 速度：力量强度（绝对值归一化）
            power_range = max(bull_power.max() - bull_power.min(),
                              bear_power.max() - bear_power.min(), 1e-9)
            power_abs = max(abs(bull_power.iloc[-1]), abs(bear_power.iloc[-1]))
            result["speed"] = min(100, power_abs / power_range * 100)
            # 加速度：力量变化率（衰竭/增强）—— 高speed+低accel=衰竭预警
            if len(bull_power) >= 3:
                bull_change = bull_power.iloc[-1] - bull_power.iloc[-3]
                bear_change = bear_power.iloc[-1] - bear_power.iloc[-3]
                result["acceleration"] = min(100, abs(bull_change - bear_change) / power_range * 100)

        # ============================================================
        # 反方指标（Phase 2：平衡确认偏误）
        # ============================================================

        elif indicator_name == "Bollinger_Bands":
            # 布林带均值回归：价格触及下轨=超卖(BULL)，触及上轨=超买(BEAR)
            # 与趋势指标相反：趋势BULL时布林带可能发出BEAR（超买）信号
            upper, middle, lower = ta.BBANDS(close, timeperiod=20, nbdevup=2, nbdevdn=2)
            price = close.iloc[-1]
            upper_val = upper.iloc[-1]
            lower_val = lower.iloc[-1]
            middle_val = middle.iloc[-1]
            band_width = upper_val - lower_val

            if band_width > 0:
                position_ratio = (price - lower_val) / band_width  # 0=下轨, 1=上轨
                if position_ratio < 0.2:
                    result["direction"] = "BULL"  # 超卖，均值回归看涨
                elif position_ratio > 0.8:
                    result["direction"] = "BEAR"  # 超买，均值回归看跌
                else:
                    result["direction"] = "NEUTRAL"
                result["speed"] = min(100, abs(position_ratio - 0.5) * 200)
                if len(close) >= 5:
                    prev_ratio = (close.iloc[-5] - lower.iloc[-5]) / (upper.iloc[-5] - lower.iloc[-5] + 1e-9)
                    result["acceleration"] = min(100, abs(position_ratio - prev_ratio) * 100)

        elif indicator_name == "RSI_Divergence":
            # 量价背离：价格创新高但RSI没有创新高 → 顶背离(BEAR)
            #           价格创新低但RSI没有创新低 → 底背离(BULL)
            rsi = ta.RSI(close, timeperiod=14)
            lookback = 20
            if len(close) > lookback and not rsi.isna().iloc[-1]:
                price_recent = close.iloc[-lookback:]
                rsi_recent = rsi.iloc[-lookback:]

                price_high = price_recent.max()
                price_low = price_recent.min()
                price_current = close.iloc[-1]

                rsi_at_price_high = rsi_recent.loc[price_recent.idxmax()]
                rsi_at_price_low = rsi_recent.loc[price_recent.idxmin()]
                rsi_current = rsi.iloc[-1]

                # 顶背离：价格接近高点但RSI低于前高
                if price_current > price_recent.quantile(0.75):
                    if rsi_current < rsi_at_price_high - 5:
                        result["direction"] = "BEAR"
                        result["speed"] = min(100, (rsi_at_price_high - rsi_current) * 5)
                # 底背离：价格接近低点但RSI高于前低
                elif price_current < price_recent.quantile(0.25):
                    if rsi_current > rsi_at_price_low + 5:
                        result["direction"] = "BULL"
                        result["speed"] = min(100, (rsi_current - rsi_at_price_low) * 5)

                if len(rsi) >= 10:
                    rsi_change = abs(rsi.iloc[-1] - rsi.iloc[-5])
                    result["acceleration"] = min(100, rsi_change * 3)

        elif indicator_name == "ATR_Volatility":
            # 波动率突变：ATR飙升 = 市场不确定性增加 → NEUTRAL或反转预警
            # 高波动率环境降低趋势信号可靠性（反方作用）
            atr = ta.ATR(df["high"], df["low"], close, timeperiod=14)
            if len(atr) >= 30 and not atr.isna().iloc[-1]:
                atr_current = atr.iloc[-1]
                atr_mean = atr.iloc[-30:].mean()
                atr_ratio = atr_current / (atr_mean + 1e-9)

                if atr_ratio > 2.0:
                    # 波动率飙升>2倍均值 → 极端行情，趋势可能失效
                    result["direction"] = "NEUTRAL"  # 中和趋势信号
                    result["speed"] = min(100, (atr_ratio - 1.0) * 50)
                elif atr_ratio > 1.5:
                    # 波动率上升 → 趋势可能衰竭
                    result["direction"] = "BEAR" if close.iloc[-1] < close.iloc[-5] else "BULL"
                    result["speed"] = min(100, (atr_ratio - 1.0) * 40)
                else:
                    result["direction"] = "NEUTRAL"
                    result["speed"] = min(100, atr_ratio * 30)

                if len(atr) >= 5:
                    atr_change = atr.iloc[-1] - atr.iloc[-5]
                    result["acceleration"] = min(100, abs(atr_change / (atr_mean + 1e-9)) * 50)

        return result

    except Exception:
        return {"direction": "NEUTRAL", "speed": 0.0, "acceleration": 0.0}


def calc_indicator_signal(df, indicator_name: str) -> str:
    """便捷函数：只返回方向信号"""
    return calc_indicator_dynamics(df, indicator_name)["direction"]


def calc_trend_direction_static(df, indicators: List[str]) -> str:
    """计算静态指标的方向（投票法）"""
    bull_count = sum(1 for ind in indicators if calc_indicator_signal(df, ind) == "BULL")
    bear_count = sum(1 for ind in indicators if calc_indicator_signal(df, ind) == "BEAR")
    if bull_count > bear_count:
        return "BULL"
    elif bear_count > bull_count:
        return "BEAR"
    return "NEUTRAL"


def calc_classic_indicator_confidence(weekly_df, daily_df) -> dict:
    """
    计算经典指标综合置信度

    算法：
      - 单一指标命中可信度: 50%
      - 多个指标共振: 50% + N×10% (N=同向指标数)
      - 速度/加速度加成：同向指标的速度+加速度均值 × 5 上限加分
      - Screen1(周线)置信度权重 60%，Screen2(日线) 40%
    """
    def _calc_group(indicators, df):
        bull_count = 0
        bear_count = 0
        neutral_count = 0
        signals = {}
        dynamics_list = []
        for ind in indicators:
            dyn = calc_indicator_dynamics(df, ind)
            signals[ind] = dyn
            if dyn["direction"] == "BULL":
                bull_count += 1
            elif dyn["direction"] == "BEAR":
                bear_count += 1
            else:
                neutral_count += 1
            dynamics_list.append(dyn)

        total = len(indicators)
        if bull_count > bear_count:
            direction = "BULL"
            count = bull_count
        elif bear_count > bull_count:
            direction = "BEAR"
            count = bear_count
        else:
            direction = "NEUTRAL"
            count = max(bull_count, bear_count)

        base_conf = 50 + count * 10

        same_dir = [d for d in dynamics_list if d["direction"] == direction]
        if same_dir:
            avg_speed = sum(d["speed"] for d in same_dir) / len(same_dir)
            avg_accel = sum(d["acceleration"] for d in same_dir) / len(same_dir)
            dynamics_bonus = min(5, (avg_speed + avg_accel) / 100 * 5)
        else:
            dynamics_bonus = 0

        confidence = min(100, base_conf + dynamics_bonus)

        return {
            "bull_count": bull_count,
            "bear_count": bear_count,
            "neutral_count": neutral_count,
            "direction": direction,
            "confidence": round(confidence, 1),
            "signals": signals,
            "dynamics_bonus": round(dynamics_bonus, 2),
        }

    s1 = _calc_group(SCREEN1_INDICATORS, weekly_df)
    s2 = _calc_group(SCREEN2_INDICATORS, daily_df)

    trend_consistent = s1["direction"] == s2["direction"] and s1["direction"] != "NEUTRAL"

    if trend_consistent:
        overall_direction = s1["direction"]
        overall_confidence = round(s1["confidence"] * WEEKLY_WEIGHT + s2["confidence"] * DAILY_WEIGHT, 1)
    else:
        overall_direction = "NEUTRAL"
        overall_confidence = round(min(s1["confidence"], s2["confidence"]) * 0.5, 1)

    return {
        "screen1_weekly": s1,
        "screen2_daily": s2,
        "overall_direction": overall_direction,
        "overall_confidence": overall_confidence,
        "trend_consistent": trend_consistent,
        "weights": {"weekly": WEEKLY_WEIGHT, "daily": DAILY_WEIGHT},
    }
