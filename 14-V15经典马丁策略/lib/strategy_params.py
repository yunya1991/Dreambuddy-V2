#!/usr/bin/env python3
"""
V15-CT 策略参数计算模块
- 动态止损：日线MA200 + EMA200
- 动态止盈：根据30天波动率调整（比特币基准）
- 动态加仓间距：根据30天波动率调整
- 三屏趋势过滤：周线+日线双周期趋势一致性检查（both_bear + MA104）
- 资金计算：基于保证金和名义价值
"""
import math
from typing import List, Optional, Tuple, Dict
from datetime import datetime, timezone, timedelta
from pathlib import Path
import sys

BASE_DIR = Path(__file__).parent.parent
sys.path.insert(0, str(BASE_DIR / "lib"))

try:
    from config_loader import load_config, get_config, get_config_float, get_config_int, get_config_list
    load_config("v15")
except Exception:
    pass

# 统一交易对适配层
try:
    from symbol_mapper import to_swap, is_supported as _coin_supported
except Exception:
    def to_swap(coin, exchange="okx"): return f"{coin}-USDT-SWAP"
    def _coin_supported(coin, exchange="okx"): return True


def _calc_sma(closes: List[float], period: int) -> Optional[float]:
    if len(closes) < period:
        return None
    return sum(closes[-period:]) / period


def _calc_ema(closes: List[float], period: int) -> Optional[float]:
    if len(closes) < period:
        return None
    k = 2 / (period + 1)
    ema = closes[0]
    for p in closes[1:]:
        ema = p * k + ema * (1 - k)
    return ema


def calc_daily_ma200(klines_1d: List[Dict]) -> Optional[float]:
    closes = [float(k["c"]) for k in klines_1d if "c" in k]
    return _calc_sma(closes, 200)


def calc_daily_ma128(klines_1d: List[Dict]) -> Optional[float]:
    closes = [float(k["c"]) for k in klines_1d if "c" in k]
    return _calc_sma(closes, 128)


def calc_daily_ema200(klines_1d: List[Dict]) -> Optional[float]:
    closes = [float(k["c"]) for k in klines_1d if "c" in k]
    return _calc_ema(closes, 200)


def calc_weekly_ma200(klines_1w: List[Dict]) -> Optional[float]:
    closes = [float(k["c"]) for k in klines_1w if "c" in k]
    return _calc_sma(closes, 200)


def calc_weekly_ema200(klines_1w: List[Dict]) -> Optional[float]:
    closes = [float(k["c"]) for k in klines_1w if "c" in k]
    return _calc_ema(closes, 200)


def calc_30d_volatility(klines_1d: List[Dict]) -> float:
    closes = [float(k["c"]) for k in klines_1d if "c" in k]
    if len(closes) < 31:
        return 0.02
    returns = [(closes[i] - closes[i - 1]) / closes[i - 1] for i in range(1, len(closes))]
    recent_returns = returns[-30:]
    avg = sum(recent_returns) / len(recent_returns)
    variance = sum((r - avg) ** 2 for r in recent_returns) / len(recent_returns)
    return variance ** 0.5


def calc_atr(klines: List[Dict], period: int = 14) -> Optional[float]:
    """计算ATR（平均真实波幅）

    TR = max(high - low, |high - prev_close|, |low - prev_close|)
    ATR = SMA(TR, period)

    返回ATR值（绝对价格），数据不足返回None
    """
    if len(klines) < period + 1:
        return None

    trs = []
    for i in range(1, len(klines)):
        h = float(klines[i].get("h", klines[i].get("c", 0)))
        l = float(klines[i].get("l", klines[i].get("c", 0)))
        prev_c = float(klines[i - 1].get("c", 0))
        tr = max(h - l, abs(h - prev_c), abs(l - prev_c))
        trs.append(tr)

    if len(trs) < period:
        return None

    return sum(trs[-period:]) / period


def calc_atr_pct(klines: List[Dict], period: int = 14) -> Optional[float]:
    """计算ATR占价格百分比

    返回 ATR / 当前价格 × 100，用于跨币种比较
    """
    atr = calc_atr(klines, period)
    if atr is None or not klines:
        return None
    current_price = float(klines[-1].get("c", 0))
    if current_price <= 0:
        return None
    return (atr / current_price) * 100


def get_dynamic_stop_loss(direction: str, current_price: float,
                          daily_ma200: Optional[float], daily_ema200: Optional[float],
                          weekly_ma200: Optional[float] = None, weekly_ema200: Optional[float] = None,
                          last_daily_close: Optional[float] = None,
                          last_weekly_close: Optional[float] = None) -> Dict:
    """
    动态止损计算：
    1. 止损线 = 价格下方最近的一条均线（日MA200、日EMA200、周MA200、周EMA200）
    2. 是否触发 = 对应周期的已收盘价确认跌破（日线看昨收，周线看上周收）
       未收盘的周期不算跌破，即使实时价已在均线下方
    """
    result = {
        "stop_loss_price": None,
        "stop_loss_pct": None,
        "stop_type": None,
        "is_triggered": False,
        "daily_ma200": daily_ma200,
        "daily_ema200": daily_ema200,
        "weekly_ma200": weekly_ma200,
        "weekly_ema200": weekly_ema200,
        "last_daily_close": last_daily_close,
        "last_weekly_close": last_weekly_close,
        "above_daily_ma200_close": None,
        "above_daily_ema200_close": None,
        "above_weekly_ma200_close": None,
        "above_weekly_ema200_close": None,
    }

    if daily_ma200 is None and daily_ema200 is None and weekly_ma200 is None and weekly_ema200 is None:
        return result

    if last_daily_close is not None:
        result["above_daily_ma200_close"] = last_daily_close > daily_ma200 if daily_ma200 else None
        result["above_daily_ema200_close"] = last_daily_close > daily_ema200 if daily_ema200 else None
    if last_weekly_close is not None:
        result["above_weekly_ma200_close"] = last_weekly_close > weekly_ma200 if weekly_ma200 else None
        result["above_weekly_ema200_close"] = last_weekly_close > weekly_ema200 if weekly_ema200 else None

    if direction.upper() == "LONG":
        candidates = []
        if daily_ma200 is not None and daily_ma200 < current_price:
            dist = (current_price - daily_ma200) / current_price
            candidates.append(("日MA200", daily_ma200, dist, "daily"))
        if daily_ema200 is not None and daily_ema200 < current_price:
            dist = (current_price - daily_ema200) / current_price
            candidates.append(("日EMA200", daily_ema200, dist, "daily"))
        if weekly_ma200 is not None and weekly_ma200 < current_price:
            dist = (current_price - weekly_ma200) / current_price
            candidates.append(("周MA200", weekly_ma200, dist, "weekly"))
        if weekly_ema200 is not None and weekly_ema200 < current_price:
            dist = (current_price - weekly_ema200) / current_price
            candidates.append(("周EMA200", weekly_ema200, dist, "weekly"))

        if candidates:
            candidates.sort(key=lambda x: x[2])
            stop_type, stop_price, _, period = candidates[0]
            result["stop_loss_price"] = round(stop_price, 4)
            result["stop_loss_pct"] = round((current_price - stop_price) / current_price * 100, 2)
            result["stop_type"] = stop_type

            if period == "daily" and last_daily_close is not None:
                result["is_triggered"] = last_daily_close <= stop_price
            elif period == "weekly" and last_weekly_close is not None:
                result["is_triggered"] = last_weekly_close <= stop_price
            else:
                result["is_triggered"] = False
        else:
            all_below_daily = True
            if daily_ma200 is not None and last_daily_close is not None and last_daily_close > daily_ma200:
                all_below_daily = False
            if daily_ema200 is not None and last_daily_close is not None and last_daily_close > daily_ema200:
                all_below_daily = False
            all_below_weekly = True
            if weekly_ma200 is not None and last_weekly_close is not None and last_weekly_close > weekly_ma200:
                all_below_weekly = False
            if weekly_ema200 is not None and last_weekly_close is not None and last_weekly_close > weekly_ema200:
                all_below_weekly = False

            has_any_above = (not all_below_daily) or (not all_below_weekly)

            result["stop_loss_price"] = None
            result["stop_loss_pct"] = None
            result["stop_type"] = "BELOW_ALL_MA_INTRADAY" if has_any_above else "BELOW_ALL_MA_CONFIRMED"
            result["is_triggered"] = not has_any_above

    elif direction.upper() == "SHORT":
        candidates = []
        if daily_ma200 is not None and daily_ma200 > current_price:
            dist = (daily_ma200 - current_price) / current_price
            candidates.append(("日MA200", daily_ma200, dist, "daily"))
        if daily_ema200 is not None and daily_ema200 > current_price:
            dist = (daily_ema200 - current_price) / current_price
            candidates.append(("日EMA200", daily_ema200, dist, "daily"))
        if weekly_ma200 is not None and weekly_ma200 > current_price:
            dist = (weekly_ma200 - current_price) / current_price
            candidates.append(("周MA200", weekly_ma200, dist, "weekly"))
        if weekly_ema200 is not None and weekly_ema200 > current_price:
            dist = (weekly_ema200 - current_price) / current_price
            candidates.append(("周EMA200", weekly_ema200, dist, "weekly"))

        if candidates:
            candidates.sort(key=lambda x: x[2])
            stop_type, stop_price, _, period = candidates[0]
            result["stop_loss_price"] = round(stop_price, 4)
            result["stop_loss_pct"] = round((stop_price - current_price) / current_price * 100, 2)
            result["stop_type"] = stop_type

            if period == "daily" and last_daily_close is not None:
                result["is_triggered"] = last_daily_close >= stop_price
            elif period == "weekly" and last_weekly_close is not None:
                result["is_triggered"] = last_weekly_close >= stop_price
            else:
                result["is_triggered"] = False
        else:
            result["stop_loss_price"] = None
            result["stop_loss_pct"] = None
            result["stop_type"] = "ABOVE_ALL_MA"
            result["is_triggered"] = True

    return result


def calc_elder_ray(klines: List[Dict], period: int = 13) -> Dict:
    """Elder-ray 趋势强度检测（Alexander Elder 三重滤网系统）

    Bull Power = High - EMA(13)  : 买方将价格推升至共识价值之上的能力
    Bear Power = Low - EMA(13)   : 卖方将价格打压至共识价值之下的能力

    核心逻辑（三重滤网第一重：趋势判断）：
    1. 用 EMA(13) 斜率判断整体趋势方向
       - 斜率向上 → 上升趋势 → 只寻找做多机会
       - 斜率向下 → 下降趋势 → 只寻找做空机会

    2. 寻找做多机会（前提：EMA斜率向上）：
       - Bear Power < 0（负值），且出现看涨背离（价格创新低，但 Bear Power 未创新低）
       - Bear Power 柱状图开始稳步上升 → 做多信号

    3. 寻找做空机会（前提：EMA斜率向下）：
       - Bull Power > 0（正值），且出现看跌背离（价格创新高，但 Bull Power 未创新高）
       - Bull Power 柱状图开始下降 → 做空信号

    4. 趋势力度衰竭与逆转：
       - 多头失控：Bull Power 转为负值 → 空头完全凌驾，可能逆转
       - 空头失控：Bear Power 转为正值 → 多头完全主控
       - 力量减弱：Bull Power > 0 且上升 + Bear Power < 0 且上升 → 多空均减弱，可能变盘
    """
    highs = [float(k["h"]) for k in klines if "h" in k]
    lows = [float(k["l"]) for k in klines if "l" in k]
    closes = [float(k["c"]) for k in klines if "c" in k]

    if len(closes) < period + 5 or len(highs) != len(closes) or len(lows) != len(closes):
        return None

    n = len(closes)
    alpha = 2 / (period + 1)

    # 逐根计算 EMA 和 Bull/Bear Power
    emas = []
    bull_powers = []
    bear_powers = []

    ema = closes[0]
    for i in range(n):
        if i > 0:
            ema = closes[i] * alpha + ema * (1 - alpha)
        emas.append(ema)
        bull_powers.append(highs[i] - ema)
        bear_powers.append(lows[i] - ema)

    current_ema = emas[-1]
    current_bull = bull_powers[-1]
    current_bear = bear_powers[-1]

    # 归一化为价格百分比
    bull_pct = current_bull / current_ema * 100 if current_ema > 0 else 0
    bear_pct = current_bear / current_ema * 100 if current_ema > 0 else 0

    # ── 1. EMA(13) 斜率判断（趋势方向核心）──
    # 用最近 3 根 EMA 的变化判断斜率
    if len(emas) >= 4 and emas[-4] != 0:
        ema_slope = (emas[-1] - emas[-4]) / emas[-4] * 100
    else:
        ema_slope = 0

    ema_trend_up = ema_slope > 0.01  # 斜率 > 0.01% 视为上升
    ema_trend_down = ema_slope < -0.01  # 斜率 < -0.01% 视为下降
    ema_trend_flat = not ema_trend_up and not ema_trend_down

    # ── 2. 背离检测 ──
    # 看涨背离（做多信号）：价格创最近N日新低，但 Bear Power 未创新低
    # 看跌背离（做空信号）：价格创最近N日新高，但 Bull Power 未创新高
    lookback = min(20, n - 1)
    bearish_divergence = False
    bullish_divergence = False

    if lookback >= 5:
        # 价格新高 + Bull Power 未新高 → 看跌背离
        recent_high_idx = n - lookback + closes[-lookback:].index(max(closes[-lookback:]))
        if closes[-1] >= closes[recent_high_idx] and bull_powers[-1] < bull_powers[recent_high_idx]:
            bearish_divergence = True

        # 价格新低 + Bear Power 未新低 → 看涨背离
        recent_low_idx = n - lookback + closes[-lookback:].index(min(closes[-lookback:]))
        if closes[-1] <= closes[recent_low_idx] and bear_powers[-1] > bear_powers[recent_low_idx]:
            bullish_divergence = True

    # ── 3. 力量趋势（柱状图变化）──
    # Bull Power 最近 3 根的变化方向
    if len(bull_powers) >= 4:
        bull_rising = bull_powers[-1] > bull_powers[-2] > bull_powers[-3]
        bull_falling = bull_powers[-1] < bull_powers[-2] < bull_powers[-3]
    else:
        bull_rising = bull_falling = False

    if len(bear_powers) >= 4:
        bear_rising = bear_powers[-1] > bear_powers[-2] > bear_powers[-3]  # 上升=空头减弱
        bear_falling = bear_powers[-1] < bear_powers[-2] < bear_powers[-3]  # 下降=空头增强
    else:
        bear_rising = bear_falling = False

    # ── 4. 趋势力度衰竭与逆转判断 ──
    bull_out_of_control = current_bull < 0  # 多头失控：Bull转负
    bear_out_of_control = current_bear > 0  # 空头失控：Bear转正

    # 力量减弱：Bull>0上升 + Bear<0上升 → 多空都在减弱，可能变盘
    both_weakening = (current_bull > 0 and bull_rising) and (current_bear < 0 and bear_rising)

    # ── 5. 趋势方向分类（基于三重滤网）──
    if ema_trend_up and current_bull > 0 and current_bear > 0:
        direction = 'STRONG_BULL'
        strength_base = 80
    elif ema_trend_up and current_bull > 0 and current_bear <= 0:
        direction = 'BULL_TREND'
        strength_base = 65
    elif ema_trend_up and current_bull <= 0:
        direction = 'BULL_REVERSAL'  # 上升趋势中Bull转负→可能逆转
        strength_base = 35
    elif ema_trend_down and current_bear < 0 and current_bull < 0:
        direction = 'STRONG_BEAR'
        strength_base = 20
    elif ema_trend_down and current_bear < 0 and current_bull >= 0:
        direction = 'BEAR_TREND'
        strength_base = 35
    elif ema_trend_down and current_bear >= 0:
        direction = 'BEAR_REVERSAL'  # 下降趋势中Bear转正→可能逆转
        strength_base = 60
    else:  # 震荡
        if current_bull > 0 and current_bear > 0:
            direction = 'SIDEWAYS_BULLISH'
            strength_base = 55
        elif current_bull < 0 and current_bear < 0:
            direction = 'SIDEWAYS_BEARISH'
            strength_base = 45
        else:
            direction = 'SIDEWAYS'
            strength_base = 50

    # 调整强度：加入斜率、背离、力量变化
    slope_bonus = min(20, abs(ema_slope) * 50) if ema_trend_up else -min(10, abs(ema_slope) * 30)
    if bullish_divergence and ema_trend_up:
        slope_bonus += 10  # 看涨背离 + 上升趋势 = 强信号
    if bearish_divergence and ema_trend_down:
        slope_bonus -= 10  # 看跌背离 + 下降趋势 = 弱信号
    if both_weakening:
        strength_base = 50  # 多空都减弱 → 中性

    strength = max(0, min(100, strength_base + slope_bonus))

    # ── 6. 综合交易信号 ──
    long_signal = False
    short_signal = False
    long_reason = ""
    short_reason = ""

    # 做多信号（前提：EMA斜率向上）
    if ema_trend_up:
        if current_bear < 0 and bear_rising and bullish_divergence:
            long_signal = True
            long_reason = "EMA上升+Bear<0+看涨背离+Bear回升"
        elif current_bear < 0 and bear_rising:
            long_reason = "EMA上升+Bear<0+Bear回升（弱信号）"
        elif current_bear > 0:
            long_reason = "EMA上升+Bear>0（空头失控，多头主控）"

    # 做空信号（前提：EMA斜率向下）
    if ema_trend_down:
        if current_bull > 0 and bull_falling and bearish_divergence:
            short_signal = True
            short_reason = "EMA下降+Bull>0+看跌背离+Bull下降"
        elif current_bull > 0 and bull_falling:
            short_reason = "EMA下降+Bull>0+Bull下降（弱信号）"
        elif current_bull < 0:
            short_reason = "EMA下降+Bull<0（多头失控，空头主控）"

    return {
        "bull_power": round(current_bull, 6),
        "bear_power": round(current_bear, 6),
        "ema13": round(current_ema, 6),
        "bull_pct": round(bull_pct, 2),
        "bear_pct": round(bear_pct, 2),
        "ema_slope_pct": round(ema_slope, 4),
        "ema_trend": "up" if ema_trend_up else ("down" if ema_trend_down else "flat"),
        "direction": direction,
        "strength": round(strength, 2),
        "bullish_divergence": bullish_divergence,
        "bearish_divergence": bearish_divergence,
        "bull_rising": bull_rising,
        "bull_falling": bull_falling,
        "bear_rising": bear_rising,
        "bear_falling": bear_falling,
        "bull_out_of_control": bull_out_of_control,
        "bear_out_of_control": bear_out_of_control,
        "both_weakening": both_weakening,
        "long_signal": long_signal,
        "short_signal": short_signal,
        "long_reason": long_reason,
        "short_reason": short_reason,
    }


def get_vol_adjusted_params(coin_vol: float, btc_vol: float,
                            base_tp_pct: float = None,
                            base_addon_pct: float = None,
                            coin_atr_pct: Optional[float] = None,
                            btc_atr_pct: Optional[float] = None) -> Dict:
    if base_tp_pct is None:
        base_tp_pct = get_config_float("BASE_TP_PCT", 0.04)
    if base_addon_pct is None:
        base_addon_pct = get_config_float("ADDON_PCT", 0.08)

    if btc_vol <= 0:
        ratio = 1.0
    else:
        ratio = coin_vol / btc_vol

    ratio = max(0.5, min(2.5, ratio))

    # ATR动态因子：当前市场波幅与BTC波幅的比值
    # 高波动币种 → 放宽止盈空间；低波动币种 → 收窄止盈空间
    atr_factor = 1.0
    if coin_atr_pct is not None and btc_atr_pct is not None and btc_atr_pct > 0:
        atr_factor = coin_atr_pct / btc_atr_pct
        atr_factor = max(0.7, min(1.5, atr_factor))

    tp_pct = base_tp_pct * ratio * atr_factor
    addon_pct = base_addon_pct * ratio * atr_factor

    return {
        "btc_volatility": round(btc_vol * 100, 4),
        "coin_volatility": round(coin_vol * 100, 4),
        "vol_ratio": round(ratio, 4),
        "atr_factor": round(atr_factor, 4),
        "coin_atr_pct": round(coin_atr_pct, 4) if coin_atr_pct else None,
        "btc_atr_pct": round(btc_atr_pct, 4) if btc_atr_pct else None,
        "take_profit_pct": round(tp_pct * 100, 2),
        "addon_pct": round(addon_pct * 100, 2),
        "base_tp_pct": round(base_tp_pct * 100, 2),
        "base_addon_pct": round(base_addon_pct * 100, 2),
    }


# ── 三屏趋势过滤 ──────────────────────────────────────────────────────────

TREND_FILTER_MODE = "none"
TREND_FILTER_PERIOD = 200


def calc_sma_value(closes: List[float], period: int) -> Optional[float]:
    """计算SMA"""
    if len(closes) < period:
        return None
    return sum(closes[-period:]) / period


def check_trend_filter(current_price: float,
                       daily_klines: List[Dict],
                       weekly_klines: List[Dict],
                       mode: str = None,
                       period: int = None) -> Dict:
    """三屏趋势过滤检查
    
    借用三屏策略的周线/日线趋势一致性思路：
    - both_bear: 周线+日线都看空（价格在均线下方）时禁止做多
    - weekly_bear: 仅周线看空时禁止做多
    - none: 不过滤
    
    返回:
        {
            "blocked": bool,          # 是否禁止开多
            "mode": str,              # 过滤模式
            "period": int,            # 均线周期
            "weekly_ma": float/None,  # 周线MA值
            "daily_ma": float/None,   # 日线MA值
            "weekly_bear": bool,      # 周线是否看空
            "daily_bear": bool,       # 日线是否看空
            "reason": str,            # 原因说明
        }
    """
    if mode is None:
        mode = get_config("TREND_FILTER_MODE", TREND_FILTER_MODE)
    if period is None:
        period = get_config_int("TREND_FILTER_PERIOD", TREND_FILTER_PERIOD)
    
    result = {
        "blocked": False,
        "mode": mode,
        "period": period,
        "weekly_ma": None,
        "daily_ma": None,
        "weekly_bear": False,
        "daily_bear": False,
        "reason": "",
    }
    
    if mode is None or str(mode).lower() == "none":
        result["reason"] = "趋势过滤未启用"
        return result
    
    # 计算周线MA
    weekly_closes = [float(k["c"]) for k in weekly_klines if "c" in k]
    weekly_ma = calc_sma_value(weekly_closes, period)
    result["weekly_ma"] = weekly_ma
    
    # 计算日线MA
    daily_closes = [float(k["c"]) for k in daily_klines if "c" in k]
    daily_ma = calc_sma_value(daily_closes, period)
    result["daily_ma"] = daily_ma
    
    weekly_bear = weekly_ma is not None and current_price < weekly_ma
    daily_bear = daily_ma is not None and current_price < daily_ma
    result["weekly_bear"] = weekly_bear
    result["daily_bear"] = daily_bear
    
    if mode == "both_bear":
        if weekly_bear and daily_bear:
            result["blocked"] = True
            result["reason"] = f"周线+日线均看空(价格<MA{period})，禁止做多"
        else:
            result["reason"] = f"周线{'看空' if weekly_bear else '看多'} + 日线{'看空' if daily_bear else '看多'}，允许做多"
    elif mode == "weekly_bear":
        if weekly_bear:
            result["blocked"] = True
            result["reason"] = f"周线看空(价格<MA{period})，禁止做多"
        else:
            result["reason"] = f"周线看多(价格≥MA{period})，允许做多"
    else:
        result["reason"] = f"未知过滤模式: {mode}"
    
    return result


def _get_okx_client():
    try:
        from okx_client import OKXSimulatedClient
        from config_loader import get_config
        config = {
            "api_key": get_config("OKX_API_KEY", ""),
            "secret_key": get_config("OKX_SECRET_KEY", ""),
            "passphrase": get_config("OKX_PASSPHRASE", ""),
            "simulated": False,
            "dry_run": False,
            "base_url": "https://www.okx.com",
            "default_inst_id": "BTC-USDT-SWAP",
            "default_usdt_amount": 100,
            "default_leverage": 5.0,
        }
        return OKXSimulatedClient(config=config)
    except Exception:
        return None


def fetch_daily_klines(client, inst_id: str, limit: int = 250) -> List[Dict]:
    try:
        r = client._get(
            "/api/v5/market/candles",
            {"instId": inst_id, "bar": "1D", "limit": str(limit)},
            auth=False
        )
        if r.get("code") == "0" and r.get("data"):
            data = r["data"]
            klines = []
            for k in data:
                klines.append({
                    "t": int(k[0]),
                    "o": float(k[1]),
                    "h": float(k[2]),
                    "l": float(k[3]),
                    "c": float(k[4]),
                    "vol": float(k[5]) if len(k) > 5 else 0,
                })
            klines.reverse()
            return klines
    except Exception:
        pass
    return []


def fetch_weekly_klines(client, inst_id: str, limit: int = 200) -> List[Dict]:
    try:
        r = client._get(
            "/api/v5/market/candles",
            {"instId": inst_id, "bar": "1W", "limit": str(limit)},
            auth=False
        )
        if r.get("code") == "0" and r.get("data"):
            data = r["data"]
            klines = []
            for k in data:
                klines.append({
                    "t": int(k[0]),
                    "o": float(k[1]),
                    "h": float(k[2]),
                    "l": float(k[3]),
                    "c": float(k[4]),
                    "vol": float(k[5]) if len(k) > 5 else 0,
                })
            klines.reverse()
            return klines
    except Exception:
        pass
    return []


def fetch_klines(client, inst_id: str, bar: str = "4H", limit: int = 200) -> List[Dict]:
    try:
        r = client._get(
            "/api/v5/market/candles",
            {"instId": inst_id, "bar": bar, "limit": str(limit)},
            auth=False
        )
        if r.get("code") == "0" and r.get("data"):
            data = r["data"]
            klines = []
            for k in data:
                klines.append({
                    "t": int(k[0]),
                    "o": float(k[1]),
                    "h": float(k[2]),
                    "l": float(k[3]),
                    "c": float(k[4]),
                    "v": float(k[5]) if len(k) > 5 else 0,
                    "vol": float(k[5]) if len(k) > 5 else 0,
                })
            klines.reverse()
            return klines
    except Exception:
        pass
    return []


def get_coin_strategy_params(symbol: str, direction: str = "LONG") -> Dict:
    client = _get_okx_client()
    if not client:
        return {"error": "OKX客户端不可用"}

    inst_id = to_swap(symbol)

    btc_daily_raw = fetch_daily_klines(client, "BTC-USDT-SWAP", 251)
    coin_daily_raw = fetch_daily_klines(client, inst_id, 251)
    coin_weekly_raw = fetch_weekly_klines(client, inst_id, 201)
    coin_4h_raw = fetch_klines(client, inst_id, "4H", 200)

    btc_daily = btc_daily_raw[:-1] if len(btc_daily_raw) > 1 else btc_daily_raw
    coin_daily = coin_daily_raw[:-1] if len(coin_daily_raw) > 1 else coin_daily_raw
    coin_weekly = coin_weekly_raw[:-1] if len(coin_weekly_raw) > 1 else coin_weekly_raw
    coin_4h = coin_4h_raw[:-1] if len(coin_4h_raw) > 1 else coin_4h_raw

    btc_vol = calc_30d_volatility(btc_daily)
    coin_vol = calc_30d_volatility(coin_daily)

    # ATR动态止盈：使用4H K线计算ATR百分比
    coin_atr_pct = calc_atr_pct(coin_4h) if coin_4h else None
    btc_4h_raw = fetch_klines(client, "BTC-USDT-SWAP", "4H", 200)
    btc_atr_pct = calc_atr_pct(btc_4h_raw) if btc_4h_raw else None

    daily_ma200 = calc_daily_ma200(coin_daily)
    daily_ma128 = calc_daily_ma128(coin_daily)
    daily_ema200 = calc_daily_ema200(coin_daily)
    weekly_ma200 = calc_weekly_ma200(coin_weekly)
    weekly_ema200 = calc_weekly_ema200(coin_weekly)

    last_daily_close = float(coin_daily[-1]["c"]) if coin_daily else None
    last_weekly_close = float(coin_weekly[-1]["c"]) if coin_weekly else None

    ticker = client.get_ticker(inst_id)
    current_price = float(ticker.get("last", 0)) if ticker.get("ok") else 0

    vol_params = get_vol_adjusted_params(coin_vol, btc_vol,
                                          coin_atr_pct=coin_atr_pct,
                                          btc_atr_pct=btc_atr_pct)
    stop_loss = get_dynamic_stop_loss(direction, current_price,
                                       daily_ma200, daily_ema200,
                                       weekly_ma200, weekly_ema200,
                                       last_daily_close, last_weekly_close)

    # 三屏趋势过滤
    trend_filter = check_trend_filter(current_price, coin_daily, coin_weekly)

    # Elder-ray 趋势强度检测
    elder_ray = calc_elder_ray(coin_daily_raw, period=13)

    tp_pct_decimal = vol_params["take_profit_pct"] / 100
    addon_pct_decimal = vol_params["addon_pct"] / 100

    take_profit_price = round(current_price * (1 + tp_pct_decimal), 4) if direction == "LONG" else round(current_price * (1 - tp_pct_decimal), 4)

    return {
        "symbol": symbol,
        "direction": direction,
        "current_price": current_price,
        "last_daily_close": last_daily_close,
        "last_weekly_close": last_weekly_close,
        "volatility": vol_params,
        "stop_loss": stop_loss,
        "trend_filter": trend_filter,
        "elder_ray": elder_ray,
        "take_profit_price": take_profit_price,
        "take_profit_pct": vol_params["take_profit_pct"],
        "addon_pct": vol_params["addon_pct"],
        "klines_4h": coin_4h,
        "klines_1d": coin_daily,
        "klines_1w": coin_weekly,
        "daily_ma200": daily_ma200,
        "daily_ma128": daily_ma128,
        "daily_ema200": daily_ema200,
        "weekly_ma200": weekly_ma200,
        "weekly_ema200": weekly_ema200,
    }


def get_all_coins_params() -> Dict:
    _raw = get_config_list("V15_COINS", default=["BTC", "ETH", "SOL", "ARB", "OP", "UNI", "HYPE", "OKB"])
    coins = [c for c in _raw if _coin_supported(c, "okx")] or _raw
    result = {}
    for coin in coins:
        try:
            result[coin] = get_coin_strategy_params(coin, "LONG")
        except Exception as e:
            result[coin] = {"error": str(e)}
    return result


if __name__ == "__main__":
    import json
    params = get_all_coins_params()
    print(json.dumps(params, indent=2, ensure_ascii=False))
