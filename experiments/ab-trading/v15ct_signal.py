#!/usr/bin/env python3
"""
V15-CT 技术策略信号模块（独立于三屏系统）
基于斐波那契回调区 + 布林带均值回归 + RSI/MACD/ADX 的纯技术分析马丁策略

本模块从 screen_executor.py 剥离，确保三屏趋势策略与 V15-CT 马丁策略完全解耦。
"""
import sys
from pathlib import Path

BASE_DIR = Path(__file__).parent


def _fetch_candles_wrapper(spot_inst: str, timeframe: str = "4H", limit: int = 200):
    """获取K线数据（通过 screen_engine 的 _fetch_candles）"""
    sys.path.insert(0, str(BASE_DIR))
    from screen_engine import _fetch_candles
    return _fetch_candles(spot_inst, timeframe, limit)


# ── 技术指标计算 ──────────────────────────────────────────────────────────

def calc_sma(values, period):
    if len(values) < period:
        return None
    return sum(values[-period:]) / period


def calc_rsi(prices, period=14):
    if len(prices) < period + 1:
        return 50.0
    deltas = [prices[i] - prices[i - 1] for i in range(1, len(prices))]
    recent = deltas[-period:]
    gains = [max(d, 0) for d in recent]
    losses = [max(-d, 0) for d in recent]
    avg_g = sum(gains) / period
    avg_l = sum(losses) / period
    if avg_l == 0:
        return 100.0
    rs = avg_g / avg_l
    return round(100 - 100 / (1 + rs), 2)


def determine_position(price, smas):
    valid = {k: v for k, v in smas.items() if v is not None}
    if not valid:
        return 'IN_ZONE'
    if all(price > v for v in valid.values()):
        return 'ABOVE_ALL'
    if all(price < v for v in valid.values()):
        return 'BELOW_ALL'
    return 'IN_ZONE'


def calc_fibonacci(prices, lookback=30):
    window = prices[-lookback:]
    swing_high = max(window)
    swing_low = min(window)
    rng = swing_high - swing_low
    return {
        'swing_high': swing_high,
        'swing_low': swing_low,
        'f382': swing_low + 0.382 * rng,
        'f500': swing_low + 0.500 * rng,
        'f618': swing_low + 0.618 * rng,
        'range': rng,
    }


def calc_bollinger_bands(prices, period=20, num_std=2):
    if len(prices) < period:
        return None
    sma = sum(prices[-period:]) / period
    if sma == 0:
        return None
    variance = sum((p - sma) ** 2 for p in prices[-period:]) / period
    std = variance ** 0.5
    upper = sma + num_std * std
    lower = sma - num_std * std
    pct_b = (prices[-1] - lower) / (upper - lower) if upper != lower else 0.5
    return {
        'sma': sma,
        'upper': upper,
        'lower': lower,
        'std': std,
        'bandwidth': round(2 * num_std * std / sma * 100, 2),
        'pct_b': round(pct_b, 3),
    }


def calc_macd(prices, fast=12, slow=26, signal=9):
    """计算MACD: macd_line, signal_line, hist, hist_prev, 金叉/死叉"""
    if len(prices) < slow + signal:
        return None
    alpha_f = 2 / (fast + 1)
    alpha_s = 2 / (slow + 1)
    ema_f = prices[0]
    ema_s = prices[0]
    macd_line = []
    for p in prices:
        ema_f = p * alpha_f + ema_f * (1 - alpha_f)
        ema_s = p * alpha_s + ema_s * (1 - alpha_s)
        macd_line.append(ema_f - ema_s)
    alpha_sig = 2 / (signal + 1)
    sig = macd_line[0]
    signal_line = []
    for m in macd_line:
        sig = m * alpha_sig + sig * (1 - alpha_sig)
        signal_line.append(sig)
    hist = [macd_line[i] - signal_line[i] for i in range(len(macd_line))]
    cross = 'none'
    if len(hist) >= 2:
        if hist[-1] > 0 and hist[-2] <= 0:
            cross = 'golden'
        elif hist[-1] < 0 and hist[-2] >= 0:
            cross = 'death'
    expanding = len(hist) >= 2 and abs(hist[-1]) > abs(hist[-2])
    return {
        'macd': round(macd_line[-1], 4),
        'signal': round(signal_line[-1], 4),
        'hist': round(hist[-1], 4),
        'hist_prev': round(hist[-2], 4) if len(hist) >= 2 else 0,
        'cross': cross,
        'expanding': expanding,
        'bearish': hist[-1] < 0,
        'bullish': hist[-1] > 0,
    }


def calc_adx(prices, period=14):
    """简化ADX: 衡量趋势强度，>25=强趋势"""
    if len(prices) < period * 2 + 1:
        return None
    plus_dm = []
    minus_dm = []
    tr = []
    for i in range(1, len(prices)):
        up = prices[i] - prices[i - 1]
        down = prices[i - 1] - prices[i]
        plus_dm.append(up if up > 0 and up > down else 0)
        minus_dm.append(down if down > 0 and down > up else 0)
        tr.append(abs(prices[i] - prices[i - 1]))

    def wilder_smooth(data, n):
        if len(data) < n:
            return data
        smoothed = [sum(data[:n])]
        for i in range(n, len(data)):
            smoothed.append(smoothed[-1] - smoothed[-1] / n + data[i])
        return smoothed

    pdm = wilder_smooth(plus_dm, period)
    mdm = wilder_smooth(minus_dm, period)
    atr = wilder_smooth(tr, period)
    dx = []
    for i in range(min(len(pdm), len(mdm), len(atr))):
        if atr[i] > 0:
            di_plus = 100 * pdm[i] / atr[i]
            di_minus = 100 * mdm[i] / atr[i]
            denom = di_plus + di_minus
            dx.append(100 * abs(di_plus - di_minus) / denom if denom > 0 else 0)
        else:
            dx.append(0)
    if len(dx) < period:
        adx = sum(dx) / len(dx) if dx else 0
    else:
        adx = sum(dx[-period:]) / period
    return {
        'adx': round(adx, 2),
        'strong': adx > 25,
        'very_strong': adx > 40,
        'di_plus': round(100 * pdm[-1] / atr[-1], 2) if atr and atr[-1] > 0 else 0,
        'di_minus': round(100 * mdm[-1] / atr[-1], 2) if atr and atr[-1] > 0 else 0,
    }


def calc_pivot_points(highs, lows, closes, period=1):
    """计算枢纽点指标（Pivot Points）"""
    if len(closes) < period + 1:
        return None
    recent_high = max(highs[-period:]) if highs else closes[-1]
    recent_low = min(lows[-period:]) if lows else closes[-1]
    recent_close = closes[-1]
    
    pivot = (recent_high + recent_low + recent_close) / 3
    r1 = 2 * pivot - recent_low
    r2 = pivot + (recent_high - recent_low)
    r3 = recent_high + 2 * (pivot - recent_low)
    s1 = 2 * pivot - recent_high
    s2 = pivot - (recent_high - recent_low)
    s3 = recent_low - 2 * (recent_high - pivot)
    
    price = closes[-1]
    support_zone = s1 <= price <= pivot
    resistance_zone = pivot <= price <= r1
    
    return {
        'pivot': round(pivot, 2),
        'r1': round(r1, 2),
        'r2': round(r2, 2),
        'r3': round(r3, 2),
        's1': round(s1, 2),
        's2': round(s2, 2),
        's3': round(s3, 2),
        'support_zone': support_zone,
        'resistance_zone': resistance_zone,
        'near_s1': abs(price - s1) / s1 < 0.01 if s1 > 0 else False,
        'near_pivot': abs(price - pivot) / pivot < 0.01 if pivot > 0 else False,
        'near_r1': abs(price - r1) / r1 < 0.01 if r1 > 0 else False,
    }


def calc_obv(prices, volumes):
    """计算OBV（On-Balance Volume）"""
    if len(prices) < 2 or len(volumes) != len(prices):
        return None
    
    obv = [0]
    for i in range(1, len(prices)):
        if prices[i] > prices[i - 1]:
            obv.append(obv[-1] + volumes[i])
        elif prices[i] < prices[i - 1]:
            obv.append(obv[-1] - volumes[i])
        else:
            obv.append(obv[-1])
    
    obv_ma = sum(obv[-10:]) / 10 if len(obv) >= 10 else obv[-1]
    obv_trend = 'BULL' if obv[-1] > obv_ma else 'BEAR'
    
    obv_change = obv[-1] - obv[-2] if len(obv) >= 2 else 0
    obv_prev_change = obv[-2] - obv[-3] if len(obv) >= 3 else 0
    obv_accelerating = obv_change > obv_prev_change > 0 if obv_prev_change != 0 else False
    
    return {
        'obv': obv[-1],
        'obv_ma': obv_ma,
        'trend': obv_trend,
        'bullish': obv_trend == 'BULL',
        'accelerating': obv_accelerating,
        'divergence': (obv[-1] > obv_ma) != (prices[-1] > prices[-2]),
    }


def calc_supertrend(prices, period=10, multiplier=3.0):
    """计算SuperTrend指标"""
    if len(prices) < period:
        return None
    
    atr_values = []
    for i in range(1, len(prices)):
        atr_values.append(abs(prices[i] - prices[i - 1]))
    atr = sum(atr_values[-period:]) / period if atr_values else 0
    
    upper_band = sum(prices[-period:]) / period + multiplier * atr
    lower_band = sum(prices[-period:]) / period - multiplier * atr
    
    price = prices[-1]
    trend_direction = 'BULL' if price > lower_band else 'BEAR'
    trend_reversal = False
    
    if len(prices) >= period + 1:
        prev_price = prices[-period - 1] if len(prices) > period + 1 else prices[-2]
        prev_trend = 'BULL' if prev_price > (sum(prices[-period - 1:-1]) / period - multiplier * atr) else 'BEAR'
        trend_reversal = trend_direction != prev_trend
    
    return {
        'upper_band': round(upper_band, 2),
        'lower_band': round(lower_band, 2),
        'trend': trend_direction,
        'bullish': trend_direction == 'BULL',
        'reversal': trend_reversal,
        'atr': round(atr, 4),
        'distance_pct': round(abs(price - lower_band) / lower_band * 100, 2) if lower_band > 0 else 0,
    }


def calc_keltner_channel(prices, period=20, multiplier=2.0):
    """计算Keltner Channel（基于EMA+ATR）"""
    if len(prices) < period:
        return None
    
    alpha = 2 / (period + 1)
    ema = prices[0]
    for p in prices[1:]:
        ema = p * alpha + ema * (1 - alpha)
    
    tr_values = []
    for i in range(1, len(prices)):
        tr_values.append(abs(prices[i] - prices[i - 1]))
    atr = sum(tr_values[-period:]) / period if tr_values else 0
    
    upper = ema + multiplier * atr
    lower = ema - multiplier * atr
    middle = ema
    
    price = prices[-1]
    position = (price - lower) / (upper - lower) if upper != lower else 0.5
    
    return {
        'upper': round(upper, 2),
        'middle': round(middle, 2),
        'lower': round(lower, 2),
        'position': round(position, 3),
        'near_lower': position < 0.2,
        'near_middle': 0.4 < position < 0.6,
        'near_upper': position > 0.8,
        'bandwidth': round(2 * multiplier * atr / ema * 100, 2) if ema > 0 else 0,
    }


def calc_stochrsi(prices, period=14, fastk=3, fastd=3):
    """计算StochRSI指标"""
    if len(prices) < period + fastk + fastd:
        return None
    
    rsi_values = []
    for i in range(period, len(prices)):
        deltas = [prices[j] - prices[j - 1] for j in range(i - period + 1, i + 1)]
        gains = [max(d, 0) for d in deltas]
        losses = [max(-d, 0) for d in deltas]
        avg_g = sum(gains) / period
        avg_l = sum(losses) / period
        rs = avg_g / avg_l if avg_l > 0 else float('inf')
        rsi = 100 - 100 / (1 + rs)
        rsi_values.append(rsi)
    
    if len(rsi_values) < fastk:
        return None
    
    stoch_k = []
    for i in range(fastk - 1, len(rsi_values)):
        window = rsi_values[i - fastk + 1:i + 1]
        lowest = min(window)
        highest = max(window)
        if highest == lowest:
            stoch_k.append(50.0)
        else:
            stoch_k.append(100 * (rsi_values[i] - lowest) / (highest - lowest))
    
    stoch_d = []
    for i in range(fastd - 1, len(stoch_k)):
        stoch_d.append(sum(stoch_k[i - fastd + 1:i + 1]) / fastd)
    
    if not stoch_d:
        return None
    
    k = stoch_k[-1]
    d = stoch_d[-1]
    cross = 'none'
    if len(stoch_d) >= 2:
        prev_k = stoch_k[-2] if len(stoch_k) >= 2 else k
        prev_d = stoch_d[-2]
        if k > d and prev_k <= prev_d:
            cross = 'golden'
        elif k < d and prev_k >= prev_d:
            cross = 'death'
    
    return {
        'k': round(k, 2),
        'd': round(d, 2),
        'cross': cross,
        'oversold': k < 20,
        'overbought': k > 80,
        'bullish': cross == 'golden' or k < 20,
    }


def calc_vortex(highs, lows, prices, period=14):
    """计算Vortex指标（趋势反转信号）"""
    if len(prices) < period + 1 or len(highs) != len(prices) or len(lows) != len(prices):
        return None
    
    plus_vi = []
    minus_vi = []
    tr_sum = []
    
    for i in range(1, len(prices)):
        tr = max(highs[i] - lows[i], highs[i] - prices[i-1], prices[i-1] - lows[i])
        plus_vi_val = abs(highs[i] - lows[i-1])
        minus_vi_val = abs(lows[i] - highs[i-1])
        plus_vi.append(plus_vi_val)
        minus_vi.append(minus_vi_val)
        tr_sum.append(tr)
    
    if len(tr_sum) < period:
        return None
    
    vi_plus_list = []
    vi_minus_list = []
    
    for i in range(period - 1, len(tr_sum)):
        tr_window = sum(tr_sum[i - period + 1:i + 1])
        if tr_window == 0:
            vi_plus_list.append(0)
            vi_minus_list.append(0)
        else:
            vi_plus_list.append(sum(plus_vi[i - period + 1:i + 1]) / tr_window)
            vi_minus_list.append(sum(minus_vi[i - period + 1:i + 1]) / tr_window)
    
    if not vi_plus_list:
        return None
    
    vi_plus = vi_plus_list[-1]
    vi_minus = vi_minus_list[-1]
    direction = 'BULL' if vi_plus > vi_minus else 'BEAR'
    
    reversal = False
    if len(vi_plus_list) >= 2:
        prev_vi_plus = vi_plus_list[-2]
        prev_vi_minus = vi_minus_list[-2]
        prev_dir = 'BULL' if prev_vi_plus > prev_vi_minus else 'BEAR'
        reversal = direction != prev_dir
    
    return {
        'vi_plus': round(vi_plus, 4),
        'vi_minus': round(vi_minus, 4),
        'direction': direction,
        'bullish': direction == 'BULL',
        'reversal': reversal,
        'strength': round(abs(vi_plus - vi_minus) * 100, 2),
    }


def calc_tema(prices, period=30):
    """计算TEMA（三重指数移动平均线）"""
    if len(prices) < period:
        return None
    
    alpha = 2 / (period + 1)
    
    ema1 = prices[0]
    ema2 = prices[0]
    ema3 = prices[0]
    
    for p in prices[1:]:
        ema1 = p * alpha + ema1 * (1 - alpha)
        ema2 = ema1 * alpha + ema2 * (1 - alpha)
        ema3 = ema2 * alpha + ema3 * (1 - alpha)
    
    tema = 3 * ema1 - 3 * ema2 + ema3
    
    price = prices[-1]
    direction = 'BULL' if tema > price else 'BEAR'
    
    if len(prices) >= period + 2:
        prev_price = prices[-2]
        prev_tema = tema
        for p in prices[:-1]:
            ema1 = p * alpha + ema1 * (1 - alpha)
            ema2 = ema1 * alpha + ema2 * (1 - alpha)
            ema3 = ema2 * alpha + ema3 * (1 - alpha)
        prev_tema = 3 * ema1 - 3 * ema2 + ema3
        slope = (tema - prev_tema) / prev_tema * 100 if prev_tema != 0 else 0
    else:
        slope = 0
    
    return {
        'tema': round(tema, 4),
        'direction': direction,
        'bullish': direction == 'BULL',
        'slope': round(slope, 4),
        'distance_pct': round(abs(tema - price) / price * 100, 2) if price > 0 else 0,
    }


def calc_golden_cross(prices, fast_period=50, slow_period=200):
    """计算GoldenCross（金叉/死叉信号）"""
    if len(prices) < slow_period:
        return None
    
    alpha_fast = 2 / (fast_period + 1)
    alpha_slow = 2 / (slow_period + 1)
    
    ema_fast = prices[0]
    ema_slow = prices[0]
    
    for p in prices[1:]:
        ema_fast = p * alpha_fast + ema_fast * (1 - alpha_fast)
        ema_slow = p * alpha_slow + ema_slow * (1 - alpha_slow)
    
    prev_ema_fast = prices[0]
    prev_ema_slow = prices[0]
    
    for p in prices[1:-1]:
        prev_ema_fast = p * alpha_fast + prev_ema_fast * (1 - alpha_fast)
        prev_ema_slow = p * alpha_slow + prev_ema_slow * (1 - alpha_slow)
    
    cross = 'none'
    if ema_fast > ema_slow and prev_ema_fast <= prev_ema_slow:
        cross = 'golden'
    elif ema_fast < ema_slow and prev_ema_fast >= prev_ema_slow:
        cross = 'death'
    
    direction = 'BULL' if ema_fast > ema_slow else 'BEAR'
    distance_pct = abs(ema_fast - ema_slow) / ema_slow * 100 if ema_slow > 0 else 0
    
    return {
        'ema_fast': round(ema_fast, 4),
        'ema_slow': round(ema_slow, 4),
        'cross': cross,
        'direction': direction,
        'bullish': direction == 'BULL' or cross == 'golden',
        'distance_pct': round(distance_pct, 2),
    }


def calc_ema_align(prices, periods=[20, 50, 200]):
    """计算EMA排列（20/50/200均线对齐）"""
    max_period = max(periods)
    if len(prices) < max_period:
        return None
    
    emas = {}
    for period in periods:
        alpha = 2 / (period + 1)
        ema = prices[0]
        for p in prices[1:]:
            ema = p * alpha + ema * (1 - alpha)
        emas[period] = ema
    
    aligned_bull = emas[20] > emas[50] > emas[200]
    aligned_bear = emas[20] < emas[50] < emas[200]
    
    if aligned_bull:
        direction = 'BULL'
    elif aligned_bear:
        direction = 'BEAR'
    else:
        direction = 'NEUTRAL'
    
    ma_values = [emas[p] for p in periods]
    ma_mean = sum(ma_values) / len(ma_values)
    ma_std = sum((v - ma_mean) ** 2 for v in ma_values) / len(ma_values) ** 0.5
    alignment_score = 1 - (ma_std / ma_mean) if ma_mean > 0 else 0
    
    return {
        'emas': {k: round(v, 4) for k, v in emas.items()},
        'direction': direction,
        'bullish': aligned_bull,
        'aligned': aligned_bull or aligned_bear,
        'alignment_score': round(alignment_score, 4),
    }


# ── V15-CT 核心决策 ──────────────────────────────────────────────────────

def v15_real_decision(screen1: dict, screen2: dict, price: float = None, test_mode: bool = False) -> dict:
    """
    V15-CT 技术策略：马丁策略 + 斐波那契入场 + 布林带均值回归（只做多模式）

    入场条件（只做多）：
    - ABOVE_ALL: price在Fib回调区[38.2%-61.8%] + RSI<55 → LONG马丁
    - BELOW_ALL: 等待（不做空）
    - IN_ZONE: RSI<35 → LONG单层; RSI>65 → 等待（不做空）
    
    参数:
        test_mode: 测试模式，降低入场标准用于系统验证
    """
    spot_inst = screen1.get("spot_inst", "BTC-USDT")
    daily_candles = _fetch_candles_wrapper(spot_inst, "4H", 200)
    if not daily_candles:
        return {"action": "WAIT", "confidence": 0, "reasons": ["无法获取K线数据"], "mode": "v15_ct", "vol_mult": 1.0}

    prices = [float(c["c"]) for c in daily_candles]
    highs = [float(c.get("h", c["c"])) for c in daily_candles]
    lows = [float(c.get("l", c["c"])) for c in daily_candles]
    volumes = [float(c.get("v", 1)) for c in daily_candles]
    current_price = price or prices[-1]

    if current_price <= 0 or len(prices) < 30:
        return {"action": "WAIT", "confidence": 0, "reasons": ["价格数据异常"], "mode": "v15_ct", "vol_mult": 1.0}

    smas = {p: calc_sma(prices, p) for p in [30, 65, 128, 200]}
    rsi = calc_rsi(prices, 14)
    position = determine_position(current_price, smas)
    fib = calc_fibonacci(prices, 30)
    boll = calc_bollinger_bands(prices, period=20, num_std=2)
    macd = calc_macd(prices)
    adx = calc_adx(prices)
    
    pivot = calc_pivot_points(highs, lows, prices, period=1)
    obv = calc_obv(prices, volumes)
    supertrend = calc_supertrend(prices, period=10, multiplier=3.0)
    keltner = calc_keltner_channel(prices, period=20, multiplier=2.0)
    stochrsi = calc_stochrsi(prices, period=14, fastk=3, fastd=3)
    
    vortex = calc_vortex(highs, lows, prices, period=14)
    tema = calc_tema(prices, period=30)
    golden_cross = calc_golden_cross(prices, fast_period=50, slow_period=200)
    ema_align = calc_ema_align(prices, periods=[20, 50, 200])

    reasons = []
    action = "WAIT"
    confidence = 30
    size_mult = 1.0
    fib_zone = None
    boll_signal = None
    trend_signal = None

    if position == 'BELOW_ALL':
        reasons.append(f"价格在所有均线下方(BELOW_ALL)")
        reasons.append(f"RSI14: {rsi}")
        reasons.append("只做多模式: 价格在均线下, 等待做多机会")

    elif position == 'ABOVE_ALL':
        rng = fib['swing_high'] - fib['swing_low']
        f382_long = fib['swing_high'] - 0.382 * rng
        f500_long = fib['swing_high'] - 0.500 * rng
        f618_long = fib['swing_high'] - 0.618 * rng
        in_zone = f618_long <= current_price <= f382_long

        reasons.append(f"价格在所有均线上方(ABOVE_ALL)")
        reasons.append(f"Fib回调区: {f618_long}-{f382_long}, 当前价: {current_price}")
        reasons.append(f"RSI14: {rsi}")
        if boll:
            reasons.append(f"布林带: 上轨{boll['upper']} 中轨{boll['sma']} 下轨{boll['lower']}")

        boll_near_mid = boll and boll['sma'] > 0 and abs(current_price - boll['sma']) / boll['sma'] < 0.02
        boll_touch_lower = boll and current_price <= boll['lower']

        # Tier 1: Fib黄金区 + 布林中轨/下轨 = 双重确认（最高置信）
        if in_zone and current_price <= f500_long and rsi < 55 and (boll_near_mid or boll_touch_lower):
            fib_zone = 'golden'
            boll_signal = 'touch_lower' if boll_touch_lower else 'near_mid'
            action = "OPEN_BULL"
            confidence = 80
            size_mult = 1.0
            reasons.append(f"Fib黄金区+布林{'下轨' if boll_touch_lower else '中轨'}双重确认, 仓位倍数{size_mult}")

        # Tier 2: Fib黄金区（当前主入场）
        elif in_zone and current_price <= f500_long and rsi < 55:
            fib_zone = 'golden'
            action = "OPEN_BULL"
            confidence = 75
            size_mult = 1.0
            reasons.append(f"Fib黄金区入场, 仓位倍数{size_mult}")

        # Tier 3: Fib浅区
        elif in_zone and current_price > f500_long and rsi < 55:
            fib_zone = 'shallow'
            action = "OPEN_BULL"
            confidence = 60
            size_mult = 0.5
            reasons.append(f"Fib浅区入场, 仓位倍数{size_mult}")

        # Tier 4: Fib区外 + 布林中轨回调（趋势中继入场）
        elif not in_zone and boll_near_mid and rsi < 50:
            boll_signal = 'near_mid'
            action = "OPEN_BULL"
            confidence = 65
            size_mult = 0.5
            reasons.append("Fib区外但价格回调至布林中轨+RSI<50, 趋势中继LONG")

        # Tier 5: RSI偏低（动能仍在多头侧）
        elif rsi < 45 and not in_zone:
            boll_signal = 'rsi_extreme'
            action = "OPEN_BULL"
            confidence = 60
            size_mult = 0.5
            reasons.append("RSI<50多头动能持续, 轻仓LONG")

        # Tier 6: MACD金叉 + hist扩张 = 顺势做多信号
        elif macd and macd['bullish'] and macd['expanding'] and rsi < 55:
            trend_signal = 'macd_bull'
            action = "OPEN_BULL"
            confidence = 68
            size_mult = 0.6
            reasons.append(f"MACD多头柱扩张(hist={macd['hist']}), 顺势LONG")

        # Tier 7: ADX强趋势 + +DI > -DI = 多头趋势确认
        elif adx and adx['strong'] and adx['di_plus'] > adx['di_minus'] and rsi < 55:
            trend_signal = 'adx_bull'
            action = "OPEN_BULL"
            confidence = 70
            size_mult = 0.7
            reasons.append(f"ADX={adx['adx']}>25, +DI={adx['di_plus']}>-DI={adx['di_minus']}, 强多头趋势")

        # Tier 8: Pivot Points 支撑区 + RSI中性 = 支撑位做多
        elif pivot and pivot['support_zone'] and 40 < rsi < 65:
            trend_signal = 'pivot_support'
            action = "OPEN_BULL"
            confidence = 62
            size_mult = 0.5
            reasons.append(f"Pivot支撑区(S1={pivot['s1']}~Pivot={pivot['pivot']}), 支撑位LONG")

        # Tier 9: OBV多头趋势 + 量能加速 = 资金流入确认
        elif obv and obv['bullish'] and obv['accelerating'] and rsi < 60:
            trend_signal = 'obv_bull'
            action = "OPEN_BULL"
            confidence = 66
            size_mult = 0.6
            reasons.append(f"OBV多头趋势加速(OBV={obv['obv']} > MA={obv['obv_ma']}), 资金流入确认LONG")

        # Tier 10: SuperTrend多头 + 趋势反转 = 趋势启动信号
        elif supertrend and supertrend['bullish'] and rsi < 60:
            trend_signal = 'supertrend_bull'
            action = "OPEN_BULL"
            confidence = 64
            size_mult = 0.5
            reasons.append(f"SuperTrend多头趋势(下轨={supertrend['lower_band']}), 顺势LONG")

        # Tier 11: Keltner Channel 下沿/中线 = 均值回归机会
        elif keltner and (keltner['near_lower'] or keltner['near_middle']) and rsi < 60:
            trend_signal = 'keltner_bull'
            action = "OPEN_BULL"
            confidence = 61
            size_mult = 0.5
            reasons.append(f"Keltner Channel{'下沿' if keltner['near_lower'] else '中线'}入场(position={keltner['position']}), 均值回归LONG")

        # Tier 12: StochRSI金叉/超卖 = 动量反转信号
        elif stochrsi and stochrsi['bullish'] and rsi < 60:
            trend_signal = 'stochrsi_bull'
            action = "OPEN_BULL"
            confidence = 63
            size_mult = 0.5
            reasons.append(f"StochRSI{'金叉' if stochrsi['cross']=='golden' else '超卖'}(K={stochrsi['k']} D={stochrsi['d']}), 动量反转LONG")

        # Tier 13: Vortex多头反转 = 趋势反转确认（三屏周线指标）
        elif vortex and vortex['bullish'] and vortex['reversal'] and rsi < 65:
            trend_signal = 'vortex_bull'
            action = "OPEN_BULL"
            confidence = 65
            size_mult = 0.5
            reasons.append(f"Vortex多头反转(VI+={vortex['vi_plus']}>VI-={vortex['vi_minus']}), 趋势反转确认LONG")

        # Tier 14: TEMA多头趋势 = 三重EMA确认（三屏日线指标）
        elif tema and tema['bullish'] and tema['slope'] > 0 and rsi < 65:
            trend_signal = 'tema_bull'
            action = "OPEN_BULL"
            confidence = 64
            size_mult = 0.5
            reasons.append(f"TEMA多头趋势(tema={tema['tema']}>price, slope={tema['slope']}%), 三重EMA确认LONG")

        # Tier 15: GoldenCross金叉 = 长期趋势启动信号（三屏日线指标）
        elif golden_cross and golden_cross['bullish'] and rsi < 65:
            trend_signal = 'goldencross_bull'
            action = "OPEN_BULL"
            confidence = 72
            size_mult = 0.7
            reasons.append(f"GoldenCross金叉(EMA50={golden_cross['ema_fast']}>EMA200={golden_cross['ema_slow']}), 长期趋势启动LONG")

        # Tier 16: EMA排列多头 = 均线完美对齐（三屏日线指标）
        elif ema_align and ema_align['bullish'] and ema_align['aligned'] and rsi < 65:
            trend_signal = 'ema_align_bull'
            action = "OPEN_BULL"
            confidence = 75
            size_mult = 0.8
            reasons.append(f"EMA排列多头(EMA20>EMA50>EMA200, 对齐度={ema_align['alignment_score']}), 完美多头排列LONG")

        else:
            if not in_zone:
                reasons.append("未在Fib回调区[38.2%-61.8%]")
            elif test_mode and rsi < 70:
                action = "OPEN_BULL"
                confidence = 45
                reasons.append("[测试模式] RSI<70, 降低标准入场")
            else:
                reasons.append("RSI>=55, 等待")

    else:
        reasons.append(f"震荡区(IN_ZONE), RSI14: {rsi}")
        if boll:
            reasons.append(f"布林带: 上轨{boll['upper']} 中轨{boll['sma']} 下轨{boll['lower']} 带宽{boll['bandwidth']}%")

            if current_price <= boll['lower'] and rsi < 45:
                action = "OPEN_BULL"
                confidence = 70
                boll_signal = 'touch_lower'
                reasons.append("价格触及布林下轨+RSI<45, 均值回归LONG")
            elif rsi < 35:
                action = "OPEN_BULL"
                confidence = 65
                boll_signal = 'rsi_extreme'
                reasons.append("RSI<35超卖, LONG单层")
            elif pivot and pivot['support_zone'] and 40 < rsi < 65:
                trend_signal = 'pivot_support'
                action = "OPEN_BULL"
                confidence = 62
                size_mult = 0.5
                reasons.append(f"Pivot支撑区入场(S1={pivot['s1']}~Pivot={pivot['pivot']})")
            elif obv and obv['bullish'] and obv['accelerating'] and rsi < 60:
                trend_signal = 'obv_bull'
                action = "OPEN_BULL"
                confidence = 64
                size_mult = 0.5
                reasons.append(f"OBV多头加速确认LONG")
            elif supertrend and supertrend['bullish'] and rsi < 60:
                trend_signal = 'supertrend_bull'
                action = "OPEN_BULL"
                confidence = 62
                size_mult = 0.5
                reasons.append(f"SuperTrend多头趋势LONG")
            elif keltner and keltner['near_lower'] and rsi < 60:
                trend_signal = 'keltner_bull'
                action = "OPEN_BULL"
                confidence = 60
                size_mult = 0.5
                reasons.append(f"Keltner下沿入场(position={keltner['position']})")
            elif stochrsi and stochrsi['bullish'] and rsi < 60:
                trend_signal = 'stochrsi_bull'
                action = "OPEN_BULL"
                confidence = 61
                size_mult = 0.5
                reasons.append(f"StochRSI{'金叉' if stochrsi['cross']=='golden' else '超卖'}LONG")
            elif vortex and vortex['bullish'] and vortex['reversal'] and rsi < 65:
                trend_signal = 'vortex_bull'
                action = "OPEN_BULL"
                confidence = 63
                size_mult = 0.5
                reasons.append(f"Vortex多头反转(VI+={vortex['vi_plus']}>VI-={vortex['vi_minus']}), 趋势反转LONG")
            elif tema and tema['bullish'] and tema['slope'] > 0 and rsi < 65:
                trend_signal = 'tema_bull'
                action = "OPEN_BULL"
                confidence = 62
                size_mult = 0.5
                reasons.append(f"TEMA多头趋势(slope={tema['slope']}%), 三重EMA确认LONG")
            elif golden_cross and golden_cross['bullish'] and rsi < 65:
                trend_signal = 'goldencross_bull'
                action = "OPEN_BULL"
                confidence = 70
                size_mult = 0.6
                reasons.append(f"GoldenCross金叉(EMA50>EMA200), 长期趋势启动LONG")
            elif ema_align and ema_align['bullish'] and ema_align['aligned'] and rsi < 65:
                trend_signal = 'ema_align_bull'
                action = "OPEN_BULL"
                confidence = 72
                size_mult = 0.7
                reasons.append(f"EMA排列多头(EMA20>EMA50>EMA200), 完美多头排列LONG")
            elif test_mode and rsi < 60:
                action = "OPEN_BULL"
                confidence = 45
                boll_signal = 'test_mode'
                reasons.append("[测试模式] RSI<60, 降低标准入场")
            elif current_price >= boll['upper'] and rsi > 55:
                reasons.append("只做多模式: 布林上轨+RSI>55, 不做空")
            elif rsi > 65:
                reasons.append("只做多模式: RSI>65超买, 不做空")
            else:
                reasons.append("布林带+RSI均未触发, 等待")
        else:
            if rsi < 35:
                action = "OPEN_BULL"
                confidence = 65
                reasons.append("RSI<35超卖, LONG单层")
            elif pivot and pivot['support_zone'] and 40 < rsi < 65:
                trend_signal = 'pivot_support'
                action = "OPEN_BULL"
                confidence = 60
                size_mult = 0.5
                reasons.append(f"Pivot支撑区入场")
            elif obv and obv['bullish'] and obv['accelerating'] and rsi < 60:
                trend_signal = 'obv_bull'
                action = "OPEN_BULL"
                confidence = 62
                size_mult = 0.5
                reasons.append(f"OBV多头加速确认LONG")
            elif supertrend and supertrend['bullish'] and rsi < 60:
                trend_signal = 'supertrend_bull'
                action = "OPEN_BULL"
                confidence = 60
                size_mult = 0.5
                reasons.append(f"SuperTrend多头趋势LONG")
            elif stochrsi and stochrsi['bullish'] and rsi < 60:
                trend_signal = 'stochrsi_bull'
                action = "OPEN_BULL"
                confidence = 60
                size_mult = 0.5
                reasons.append(f"StochRSI{'金叉' if stochrsi['cross']=='golden' else '超卖'}LONG")
            elif vortex and vortex['bullish'] and vortex['reversal'] and rsi < 65:
                trend_signal = 'vortex_bull'
                action = "OPEN_BULL"
                confidence = 61
                size_mult = 0.5
                reasons.append(f"Vortex多头反转(VI+={vortex['vi_plus']}>VI-={vortex['vi_minus']}), 趋势反转LONG")
            elif tema and tema['bullish'] and tema['slope'] > 0 and rsi < 65:
                trend_signal = 'tema_bull'
                action = "OPEN_BULL"
                confidence = 60
                size_mult = 0.5
                reasons.append(f"TEMA多头趋势(slope={tema['slope']}%), 三重EMA确认LONG")
            elif golden_cross and golden_cross['bullish'] and rsi < 65:
                trend_signal = 'goldencross_bull'
                action = "OPEN_BULL"
                confidence = 68
                size_mult = 0.6
                reasons.append(f"GoldenCross金叉(EMA50>EMA200), 长期趋势启动LONG")
            elif ema_align and ema_align['bullish'] and ema_align['aligned'] and rsi < 65:
                trend_signal = 'ema_align_bull'
                action = "OPEN_BULL"
                confidence = 70
                size_mult = 0.7
                reasons.append(f"EMA排列多头(EMA20>EMA50>EMA200), 完美多头排列LONG")
            elif test_mode and rsi < 60:
                action = "OPEN_BULL"
                confidence = 45
                reasons.append("[测试模式] RSI<60, 降低标准入场")
            elif rsi > 65:
                reasons.append("只做多模式: RSI>65超买, 不做空")
            else:
                reasons.append("RSI中性, 等待")

    vol_mult = 1.0
    if fib_zone == 'golden' and boll_signal in ('touch_upper', 'touch_lower'):
        vol_mult = 1.3
    elif fib_zone == 'golden':
        vol_mult = 1.2
    elif fib_zone == 'shallow':
        vol_mult = 0.8
    elif trend_signal == 'adx_bull' or trend_signal == 'adx_bear':
        vol_mult = 0.9
    elif trend_signal == 'macd_bull' or trend_signal == 'macd_bear':
        vol_mult = 0.8
    elif boll_signal in ('touch_upper', 'touch_lower'):
        vol_mult = 1.0
    elif boll_signal == 'rsi_extreme':
        vol_mult = 0.7

    result = {
        "action": action,
        "confidence": confidence,
        "reasons": reasons,
        "mode": "v15_ct",
        "vol_mult": vol_mult,
        "position": position,
        "fib_zone": fib_zone,
        "trend_signal": trend_signal,
        "boll_signal": boll_signal,
        "rsi": rsi,
        "smas": {k: round(v, 2) if v else None for k, v in smas.items()},
        "fib": fib,
    }
    if boll:
        result["boll"] = boll
    if macd:
        result["macd"] = macd
    if adx:
        result["adx"] = adx
    if pivot:
        result["pivot"] = pivot
    if obv:
        result["obv"] = obv
    if supertrend:
        result["supertrend"] = supertrend
    if keltner:
        result["keltner"] = keltner
    if stochrsi:
        result["stochrsi"] = stochrsi
    if vortex:
        result["vortex"] = vortex
    if tema:
        result["tema"] = tema
    if golden_cross:
        result["golden_cross"] = golden_cross
    if ema_align:
        result["ema_align"] = ema_align
    return result
