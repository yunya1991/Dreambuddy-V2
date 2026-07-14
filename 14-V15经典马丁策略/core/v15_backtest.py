#!/usr/bin/env python3
"""
V15 经典马丁策略回测引擎
- 4H周期K线
- 马丁加仓（最多3层）
- 斐波那契+布林带+MACD+ADX入场
- 所有币种: 动态MA200止损（日线/周线）
- 所有币种: 根据30天波动率调整止盈和加仓间距
- 默认只做多模式
"""
import json, os, sys, time, requests, warnings, math
from pathlib import Path
from typing import Dict, List, Tuple, Optional
from datetime import datetime, timezone, timedelta

warnings.filterwarnings("ignore")

BASE_DIR = Path(__file__).parent.parent
CACHE_DIR = BASE_DIR / "data" / "backtest_cache"
CACHE_DIR.mkdir(parents=True, exist_ok=True)

MAX_ADDONS = 3
BASE_ADDON_PCT = 0.08
BASE_TP_PCT = 0.04


# ── 指标计算 ──────────────────────────────────────────────────────────────

def _calc_sma(values, period):
    if len(values) < period:
        return None
    return sum(values[-period:]) / period


def _calc_rsi(prices, period=14):
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


def _determine_position(price, smas):
    valid = {k: v for k, v in smas.items() if v is not None}
    if not valid:
        return 'IN_ZONE'
    if all(price > v for v in valid.values()):
        return 'ABOVE_ALL'
    if all(price < v for v in valid.values()):
        return 'BELOW_ALL'
    return 'IN_ZONE'


def _calc_fibonacci(prices, lookback=30):
    window = prices[-lookback:]
    swing_high = max(window)
    swing_low = min(window)
    rng = swing_high - swing_low
    return {
        'swing_high': round(swing_high),
        'swing_low': round(swing_low),
        'f382': round(swing_low + 0.382 * rng),
        'f500': round(swing_low + 0.500 * rng),
        'f618': round(swing_low + 0.618 * rng),
        'range': rng,
    }


def _calc_bollinger_bands(prices, period=20, num_std=2):
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
        'sma': round(sma, 2),
        'upper': round(upper, 2),
        'lower': round(lower, 2),
        'std': round(std, 2),
        'bandwidth': round(2 * num_std * std / sma * 100, 2),
        'pct_b': round(pct_b, 3),
    }


def _calc_macd(prices, fast=12, slow=26, signal=9):
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


def _calc_adx(prices, period=14):
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


# ── 数据获取 ──────────────────────────────────────────────────────────────

def fetch_klines(coin: str, interval: str = "4h", limit: int = 1000) -> List[Dict]:
    """获取历史K线数据（带缓存）"""
    cache_file = CACHE_DIR / f"{coin}_{interval}_{limit}.json"

    if cache_file.exists():
        try:
            with open(cache_file) as f:
                cached = json.load(f)
            cache_age = time.time() - cached.get("cached_at", 0)
            if cache_age < 86400 * 7:  # 缓存7天
                return cached.get("data", [])
        except Exception:
            pass

    try:
        s = requests.Session()
        s.trust_env = False
        now_ms = int(time.time() * 1000)

        interval_ms_map = {
            "1h": 3600 * 1000,
            "2h": 7200 * 1000,
            "4h": 14400 * 1000,
            "1d": 86400 * 1000,
            "1w": 7 * 86400 * 1000,
        }
        bar_ms = interval_ms_map.get(interval, 14400 * 1000)
        start_ms = now_ms - limit * bar_ms

        r = s.post(
            "https://api.hyperliquid.xyz/info",
            json={
                "type": "candleSnapshot",
                "req": {
                    "coin": coin,
                    "interval": interval,
                    "startTime": start_ms,
                    "endTime": now_ms,
                },
            },
            timeout=60,
        )
        data = r.json()

        if isinstance(data, list) and len(data) > 0:
            with open(cache_file, "w") as f:
                json.dump({"cached_at": time.time(), "data": data}, f)
            return data
        return []
    except Exception as e:
        print(f"获取K线失败 [{coin}/{interval}]: {e}")
        return []


# ── MA200计算 ─────────────────────────────────────────────────────────────

def _timestamp_to_date_str(ts_ms: int) -> str:
    """时间戳转日期字符串 YYYY-MM-DD"""
    return datetime.fromtimestamp(ts_ms / 1000, tz=timezone.utc).strftime("%Y-%m-%d")


def _timestamp_to_week_start_str(ts_ms: int) -> str:
    """时间戳转周开始日期字符串（周一）"""
    dt = datetime.fromtimestamp(ts_ms / 1000, tz=timezone.utc)
    week_start = dt - timedelta(days=dt.weekday())
    return week_start.strftime("%Y-%m-%d")


def calc_ma200_series(closes: List[float]) -> List[Optional[float]]:
    """计算MA200序列"""
    ma200 = []
    for i in range(len(closes)):
        if i >= 199:
            ma200.append(sum(closes[i - 199:i + 1]) / 200)
        else:
            ma200.append(None)
    return ma200


def prepare_daily_sma_for_4h(klines_4h: List[Dict], klines_1d: List[Dict], periods: List[int]) -> Dict[int, List[Optional[float]]]:
    """
    为4H数据准备日线SMA序列（多个周期）
    返回: {period: [ma_values]}，每个列表长度与klines_4h相同
    """
    n = len(klines_4h)
    result = {p: [None] * n for p in periods}

    if len(klines_1d) < max(periods):
        return result

    daily_closes = [float(k["c"]) for k in klines_1d]

    # 计算各周期日线SMA序列
    daily_ma_series = {}
    for p in periods:
        ma_list = []
        for i in range(len(daily_closes)):
            if i >= p - 1:
                ma_list.append(sum(daily_closes[i - p + 1:i + 1]) / p)
            else:
                ma_list.append(None)
        daily_ma_series[p] = ma_list

    # 创建日期->MA映射
    daily_ma_dict = {p: {} for p in periods}
    for p in periods:
        for k, ma in zip(klines_1d, daily_ma_series[p]):
            if ma is not None:
                date_str = _timestamp_to_date_str(k["t"])
                daily_ma_dict[p][date_str] = ma

    # 映射到4H时间点
    for i, k in enumerate(klines_4h):
        date_str = _timestamp_to_date_str(k["t"])
        for p in periods:
            result[p][i] = daily_ma_dict[p].get(date_str)

    return result


def prepare_ma200_for_4h(klines_4h: List[Dict], klines_1d: List[Dict], klines_1w: List[Dict]) -> Tuple[List[Optional[float]], List[Optional[float]]]:
    """
    为4H数据准备日线MA200和周线MA200序列
    返回: (daily_ma200_list, weekly_ma200_list)，长度与klines_4h相同
    """
    n = len(klines_4h)
    daily_ma200_for_4h = [None] * n
    weekly_ma200_for_4h = [None] * n

    # 计算日线MA200
    if len(klines_1d) >= 200:
        daily_closes = [float(k["c"]) for k in klines_1d]
        daily_ma200_series = calc_ma200_series(daily_closes)

        # 创建日期->MA200映射
        daily_ma200_dict = {}
        for k, ma in zip(klines_1d, daily_ma200_series):
            if ma is not None:
                date_str = _timestamp_to_date_str(k["t"])
                daily_ma200_dict[date_str] = ma

        # 映射到4H时间点
        for i, k in enumerate(klines_4h):
            date_str = _timestamp_to_date_str(k["t"])
            daily_ma200_for_4h[i] = daily_ma200_dict.get(date_str)

    # 计算周线MA200
    if len(klines_1w) >= 200:
        weekly_closes = [float(k["c"]) for k in klines_1w]
        weekly_ma200_series = calc_ma200_series(weekly_closes)

        # 创建周开始日期->MA200映射
        weekly_ma200_dict = {}
        for k, ma in zip(klines_1w, weekly_ma200_series):
            if ma is not None:
                week_str = _timestamp_to_week_start_str(k["t"])
                weekly_ma200_dict[week_str] = ma

        # 映射到4H时间点
        for i, k in enumerate(klines_4h):
            week_str = _timestamp_to_week_start_str(k["t"])
            weekly_ma200_for_4h[i] = weekly_ma200_dict.get(week_str)

    return daily_ma200_for_4h, weekly_ma200_for_4h


def prepare_last_close_for_4h(klines_4h: List[Dict], klines_1d: List[Dict], klines_1w: List[Dict]) -> Tuple[List[Optional[float]], List[Optional[float]]]:
    """
    为4H数据准备上一日收盘价和上一周收盘价序列（用于收盘价确认逻辑）
    返回: (last_daily_close_list, last_weekly_close_list)，长度与klines_4h相同
    """
    n = len(klines_4h)
    last_daily_close = [None] * n
    last_weekly_close = [None] * n

    if len(klines_1d) >= 2:
        daily_close_dict = {}
        for i, k in enumerate(klines_1d):
            if i >= 1:
                date_str = _timestamp_to_date_str(k["t"])
                daily_close_dict[date_str] = float(klines_1d[i - 1]["c"])

        for i, k in enumerate(klines_4h):
            date_str = _timestamp_to_date_str(k["t"])
            last_daily_close[i] = daily_close_dict.get(date_str)

    if len(klines_1w) >= 2:
        weekly_close_dict = {}
        for i, k in enumerate(klines_1w):
            if i >= 1:
                week_str = _timestamp_to_week_start_str(k["t"])
                weekly_close_dict[week_str] = float(klines_1w[i - 1]["c"])

        for i, k in enumerate(klines_4h):
            week_str = _timestamp_to_week_start_str(k["t"])
            last_weekly_close[i] = weekly_close_dict.get(week_str)

    return last_daily_close, last_weekly_close


# ── 动态止损 ──────────────────────────────────────────────────────────────

def get_ma200_stop_loss(direction: str, close: float,
                       daily_ma200: Optional[float], weekly_ma200: Optional[float],
                       last_daily_close: Optional[float] = None,
                       last_weekly_close: Optional[float] = None) -> Tuple[Optional[float], bool, str]:
    """
    MA200动态止损逻辑（与实盘strategy_params.py逻辑一致）
    返回: (止损线价格, 是否触发止损, 止损类型)
    
    规则:
    1. 止损线 = 价格下方（做多）/上方（做空）最近的一条MA200
    2. 触发条件 = 对应周期的已收盘价确认（日线看昨收，周线看上周收）
       未收盘的周期不算跌破/突破，即使实时价已在均线另一侧
    3. 如果所有均线都在价格上方（做多）且全部确认跌破 → BELOW_ALL触发
    """
    if daily_ma200 is None and weekly_ma200 is None:
        return None, False, "NONE"

    if direction == "SHORT":
        candidates = []
        if daily_ma200 is not None and daily_ma200 > close:
            dist = daily_ma200 - close
            candidates.append((daily_ma200, dist, "daily"))
        if weekly_ma200 is not None and weekly_ma200 > close:
            dist = weekly_ma200 - close
            candidates.append((weekly_ma200, dist, "weekly"))

        if candidates:
            candidates.sort(key=lambda x: x[1])
            stop_price, _, period = candidates[0]
            stop_type = "日MA200" if period == "daily" else "周MA200"
            triggered = False
            if period == "daily" and last_daily_close is not None:
                triggered = last_daily_close >= stop_price
            elif period == "weekly" and last_weekly_close is not None:
                triggered = last_weekly_close >= stop_price
            return stop_price, triggered, stop_type
        else:
            return None, True, "ABOVE_ALL_MA"

    else:  # LONG
        candidates = []
        if daily_ma200 is not None and daily_ma200 < close:
            dist = close - daily_ma200
            candidates.append((daily_ma200, dist, "daily"))
        if weekly_ma200 is not None and weekly_ma200 < close:
            dist = close - weekly_ma200
            candidates.append((weekly_ma200, dist, "weekly"))

        if candidates:
            candidates.sort(key=lambda x: x[1])
            stop_price, _, period = candidates[0]
            stop_type = "日MA200" if period == "daily" else "周MA200"
            triggered = False
            if period == "daily" and last_daily_close is not None:
                triggered = last_daily_close <= stop_price
            elif period == "weekly" and last_weekly_close is not None:
                triggered = last_weekly_close <= stop_price
            return stop_price, triggered, stop_type
        else:
            all_below_daily = True
            if daily_ma200 is not None and last_daily_close is not None and last_daily_close > daily_ma200:
                all_below_daily = False
            all_below_weekly = True
            if weekly_ma200 is not None and last_weekly_close is not None and last_weekly_close > weekly_ma200:
                all_below_weekly = False

            all_confirmed_below = all_below_daily and all_below_weekly
            return None, all_confirmed_below, "BELOW_ALL_MA"


# ── 波动率参数调整 ────────────────────────────────────────────────────────

def calc_30d_volatility(klines_1d: List[Dict]) -> float:
    """计算30天波动率（日收益率标准差）"""
    closes = [float(k["c"]) for k in klines_1d]
    if len(closes) < 31:
        return 0.02  # 默认2%

    returns = [(closes[i] - closes[i - 1]) / closes[i - 1] for i in range(1, len(closes))]
    recent_returns = returns[-30:]
    avg = sum(recent_returns) / len(recent_returns)
    variance = sum((r - avg) ** 2 for r in recent_returns) / len(recent_returns)
    return variance ** 0.5


def get_vol_adjusted_params(base_tp: float, base_addon: float, coin_vol: float, btc_vol: float) -> Tuple[float, float]:
    """
    根据波动率调整参数
    返回: (调整后的止盈比例, 调整后的加仓间距)
    """
    if btc_vol <= 0:
        ratio = 1.0
    else:
        ratio = coin_vol / btc_vol

    # 限制调整范围 0.5x - 2.0x
    ratio = max(0.5, min(2.0, ratio))

    return base_tp * ratio, base_addon * ratio


# ── 趋势过滤 ──────────────────────────────────────────────────────────────

def calc_sma(prices: List[float], period: int) -> float:
    """计算简单移动平均线"""
    if len(prices) < period:
        return 0.0
    return sum(prices[-period:]) / period


def calc_ma_series(closes: List[float], period: int) -> List[Optional[float]]:
    """计算简单移动平均线序列"""
    result = [None] * len(closes)
    if len(closes) < period:
        return result
    
    for i in range(period - 1, len(closes)):
        result[i] = sum(closes[i - period + 1:i + 1]) / period
    
    return result


def prepare_weekly_ma_for_4h(klines_4h: List[Dict], klines_1w: List[Dict], period: int) -> List[Optional[float]]:
    """为4H K线准备周线MA序列
    
    返回：每个4H K线对应的周线MA值
    """
    n = len(klines_4h)
    result = [None] * n
    
    if len(klines_1w) >= period:
        weekly_closes = [float(k["c"]) for k in klines_1w]
        weekly_ma_series = calc_ma_series(weekly_closes, period)
        
        weekly_ma_dict = {}
        for k, ma in zip(klines_1w, weekly_ma_series):
            if ma is not None:
                week_str = _timestamp_to_week_start_str(k["t"])
                weekly_ma_dict[week_str] = ma
        
        for i, k in enumerate(klines_4h):
            week_str = _timestamp_to_week_start_str(k["t"])
            result[i] = weekly_ma_dict.get(week_str)
    
    return result


def prepare_daily_ma_for_4h(klines_4h: List[Dict], klines_1d: List[Dict], period: int) -> List[Optional[float]]:
    """为4H K线准备日线MA序列"""
    n = len(klines_4h)
    result = [None] * n
    
    if len(klines_1d) >= period:
        daily_closes = [float(k["c"]) for k in klines_1d]
        daily_ma_series = calc_ma_series(daily_closes, period)
        
        daily_ma_dict = {}
        for k, ma in zip(klines_1d, daily_ma_series):
            if ma is not None:
                date_str = _timestamp_to_date_str(k["t"])
                daily_ma_dict[date_str] = ma
        
        for i, k in enumerate(klines_4h):
            date_str = _timestamp_to_date_str(k["t"])
            result[i] = daily_ma_dict.get(date_str)
    
    return result


def check_trend_filter(current_price: float, weekly_ma, daily_ma, 
                        filter_mode: str = "both_bear") -> bool:
    """趋势过滤检查
    
    参数:
        current_price: 当前价格
        weekly_ma: 周线均线值 (可能为None)
        daily_ma: 日线均线值 (可能为None)
        filter_mode: 过滤模式
            - "both_bear": 周线+日线都看空(价格都在均线下方)时禁止开多
            - "weekly_bear": 仅周线看空时禁止开多
            - "none": 不过滤
    
    返回: True=禁止开多, False=允许开多
    """
    if filter_mode == "none":
        return False
    
    if weekly_ma is None and daily_ma is None:
        return False
    
    weekly_bear = current_price < weekly_ma if weekly_ma is not None else None
    daily_bear = current_price < daily_ma if daily_ma is not None else None
    
    if filter_mode == "both_bear":
        if weekly_bear is None or daily_bear is None:
            return False
        return weekly_bear and daily_bear
    elif filter_mode == "weekly_bear":
        if weekly_bear is None:
            return False
        return weekly_bear
    else:
        return False


# ── V15决策 ───────────────────────────────────────────────────────────────

def v15_decision(prices: List[float], override_position: str = None, override_smas: Dict[int, float] = None) -> dict:
    """V15策略决策函数
    
    参数:
        prices: 价格列表
        override_position: 外部传入的位置判定（'ABOVE_ALL'/'IN_ZONE'/'BELOW_ALL'/None），为None时用prices计算
        override_smas: 外部传入的均线值 dict，用于展示
    """
    if len(prices) < 30:
        return {"action": "WAIT", "confidence": 0, "reasons": ["数据不足"], "vol_mult": 1.0}

    current_price = prices[-1]
    if current_price <= 0:
        return {"action": "WAIT", "confidence": 0, "reasons": ["价格异常"], "vol_mult": 1.0}

    smas = {p: _calc_sma(prices, p) for p in [30, 65, 128, 200]}
    rsi = _calc_rsi(prices, 14)

    if override_position is not None:
        position = override_position
        display_smas = override_smas if override_smas else smas
    else:
        position = _determine_position(current_price, smas)
        display_smas = smas
    fib = _calc_fibonacci(prices, 30)
    boll = _calc_bollinger_bands(prices, period=20, num_std=2)
    macd = _calc_macd(prices)
    adx = _calc_adx(prices)

    reasons = []
    action = "WAIT"
    confidence = 30
    size_mult = 1.0
    fib_zone = None
    boll_signal = None
    trend_signal = None

    if position == 'BELOW_ALL':
        in_zone = fib['f382'] <= current_price <= fib['f618']
        reasons.append(f"BELOW_ALL, Fib区: {fib['f382']}-{fib['f618']}, 现价: {current_price:.0f}, RSI: {rsi}")

        boll_near_mid = boll and abs(current_price - boll['sma']) / boll['sma'] < 0.02
        boll_touch_upper = boll and current_price >= boll['upper']

        if in_zone and current_price >= fib['f500'] and rsi > 45 and (boll_near_mid or boll_touch_upper):
            fib_zone = 'golden'
            boll_signal = 'touch_upper' if boll_touch_upper else 'near_mid'
            action = "OPEN_BEAR"
            confidence = 80
            size_mult = 1.0
        elif in_zone and current_price >= fib['f500'] and rsi > 45:
            fib_zone = 'golden'
            action = "OPEN_BEAR"
            confidence = 75
            size_mult = 1.0
        elif in_zone and current_price < fib['f500'] and rsi > 45:
            fib_zone = 'shallow'
            action = "OPEN_BEAR"
            confidence = 60
            size_mult = 0.5
        elif not in_zone and boll_near_mid and rsi > 50:
            boll_signal = 'near_mid'
            action = "OPEN_BEAR"
            confidence = 65
            size_mult = 0.5
        elif rsi > 55 and not in_zone:
            boll_signal = 'rsi_extreme'
            action = "OPEN_BEAR"
            confidence = 60
            size_mult = 0.5
        elif macd and macd['bearish'] and macd['expanding'] and rsi > 45:
            trend_signal = 'macd_bear'
            action = "OPEN_BEAR"
            confidence = 68
            size_mult = 0.6
        elif adx and adx['strong'] and adx['di_minus'] > adx['di_plus'] and rsi > 45:
            trend_signal = 'adx_bear'
            action = "OPEN_BEAR"
            confidence = 70
            size_mult = 0.7

    elif position == 'ABOVE_ALL':
        rng = fib['swing_high'] - fib['swing_low']
        f382_long = round(fib['swing_high'] - 0.382 * rng)
        f500_long = round(fib['swing_high'] - 0.500 * rng)
        f618_long = round(fib['swing_high'] - 0.618 * rng)
        in_zone = f618_long <= current_price <= f382_long

        reasons.append(f"ABOVE_ALL, Fib回调区: {f618_long}-{f382_long}, 现价: {current_price:.0f}, RSI: {rsi}")

        boll_near_mid = boll and abs(current_price - boll['sma']) / boll['sma'] < 0.02
        boll_touch_lower = boll and current_price <= boll['lower']

        if in_zone and current_price <= f500_long and rsi < 55 and (boll_near_mid or boll_touch_lower):
            fib_zone = 'golden'
            boll_signal = 'touch_lower' if boll_touch_lower else 'near_mid'
            action = "OPEN_BULL"
            confidence = 80
            size_mult = 1.0
        elif in_zone and current_price <= f500_long and rsi < 55:
            fib_zone = 'golden'
            action = "OPEN_BULL"
            confidence = 75
            size_mult = 1.0
        elif in_zone and current_price > f500_long and rsi < 55:
            fib_zone = 'shallow'
            action = "OPEN_BULL"
            confidence = 60
            size_mult = 0.5
        elif not in_zone and boll_near_mid and rsi < 50:
            boll_signal = 'near_mid'
            action = "OPEN_BULL"
            confidence = 65
            size_mult = 0.5
        elif rsi < 45 and not in_zone:
            boll_signal = 'rsi_extreme'
            action = "OPEN_BULL"
            confidence = 60
            size_mult = 0.5
        elif macd and macd['bullish'] and macd['expanding'] and rsi < 55:
            trend_signal = 'macd_bull'
            action = "OPEN_BULL"
            confidence = 68
            size_mult = 0.6
        elif adx and adx['strong'] and adx['di_plus'] > adx['di_minus'] and rsi < 55:
            trend_signal = 'adx_bull'
            action = "OPEN_BULL"
            confidence = 70
            size_mult = 0.7

    else:
        reasons.append(f"IN_ZONE, RSI: {rsi}")
        if boll:
            if current_price <= boll['lower'] and rsi < 45:
                action = "OPEN_BULL"
                confidence = 70
                boll_signal = 'touch_lower'
            elif current_price >= boll['upper'] and rsi > 55:
                action = "OPEN_BEAR"
                confidence = 70
                boll_signal = 'touch_upper'
            elif rsi < 35:
                action = "OPEN_BULL"
                confidence = 65
                boll_signal = 'rsi_extreme'
            elif rsi > 65:
                action = "OPEN_BEAR"
                confidence = 65
                boll_signal = 'rsi_extreme'
        else:
            if rsi < 35:
                action = "OPEN_BULL"
                confidence = 65
            elif rsi > 65:
                action = "OPEN_BEAR"
                confidence = 65

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

    return {
        "action": action,
        "confidence": confidence,
        "reasons": reasons,
        "vol_mult": vol_mult,
        "position": position,
        "fib_zone": fib_zone,
        "trend_signal": trend_signal,
        "boll_signal": boll_signal,
        "size_mult": size_mult,
        "rsi": rsi,
    }


# ── 回测引擎 ──────────────────────────────────────────────────────────────

def run_backtest(
    coin: str,
    klines: List[Dict] = None,
    initial_capital: float = 10000.0,
    base_position_pct: float = 0.05,
    max_addons: int = MAX_ADDONS,
    confidence_threshold: int = 0,
    long_only: bool = True,
    position_tf: str = "4h",
    custom_addon_pct: float = None,
    custom_tp_pct: float = None,
    trend_filter_mode: str = "none",
    trend_filter_period: int = 60,
    max_base_holding_hours: float = 48.0,
    max_post_addon_hours: float = 24.0,
    golden_window_hours: float = 12.0,
) -> Dict:
    """
    运行V15策略回测 v4
    
    参数:
        coin: 币种
        klines: 4H K线数据（为None时自动获取）
        initial_capital: 初始资金
        base_position_pct: 基础仓位比例
        max_addons: 最大加仓次数
        confidence_threshold: 入场置信度阈值
        long_only: 是否只做多模式
        position_tf: 位置判定时间框架 - "4h"（4H均线）或 "1d"（日线均线）
        custom_addon_pct: 自定义加仓间距比例（覆盖波动率调整）
        custom_tp_pct: 自定义止盈比例（覆盖波动率调整）
        trend_filter_mode: 趋势过滤模式 - "none"/"both_bear"/"weekly_bear"
        trend_filter_period: 趋势过滤均线周期（默认60）
        max_base_holding_hours: 底仓最大持仓时间（小时），超时触发经典离场评估
        max_post_addon_hours: 加仓后最大持仓时间（小时）
        golden_window_hours: 黑天鹅反弹黄金窗口（小时），窗口内不触发评估
    """
    is_btc = coin.upper() == "BTC"

    # 获取数据
    if klines is None:
        klines = fetch_klines(coin, "4h", 1500)

    if len(klines) < 200:
        return {"error": f"4H K线数据不足({len(klines)}根)，至少需要200根", "trades": [], "metrics": {}}

    for k in klines:
        if "ts" in k and "t" not in k:
            k["t"] = k["ts"]
        if "c" in k and "close" not in k:
            k["close"] = k["c"]

    # 获取日线和周线数据（用于MA200和波动率计算）
    klines_1d = fetch_klines(coin, "1d", 400)
    klines_1w = fetch_klines(coin, "1w", 250)

    # 预计算MA200（所有币种都使用MA200动态止损）
    daily_ma200_list, weekly_ma200_list = None, None
    last_daily_close_list, last_weekly_close_list = None, None
    if len(klines_1d) >= 200:
        daily_ma200_list, weekly_ma200_list = prepare_ma200_for_4h(klines, klines_1d, klines_1w)
        last_daily_close_list, last_weekly_close_list = prepare_last_close_for_4h(klines, klines_1d, klines_1w)

    # 预计算日线均线（用于日线位置判定模式）
    daily_sma_lists = None
    if position_tf == "1d" and len(klines_1d) >= 200:
        daily_sma_periods = [30, 60, 120, 200]
        daily_sma_lists = prepare_daily_sma_for_4h(klines, klines_1d, daily_sma_periods)
    
    # 预计算趋势过滤均线（周线MA + 日线MA）
    trend_weekly_ma = None
    trend_daily_ma = None
    if trend_filter_mode != "none":
        if len(klines_1w) >= trend_filter_period:
            trend_weekly_ma = prepare_weekly_ma_for_4h(klines, klines_1w, trend_filter_period)
        if len(klines_1d) >= trend_filter_period:
            trend_daily_ma = prepare_daily_ma_for_4h(klines, klines_1d, trend_filter_period)

    # 计算波动率（所有币种都按波动率调整参数）
    coin_vol = calc_30d_volatility(klines_1d) if klines_1d else 0.02

    # 获取BTC波动率作为基准
    btc_klines_1d = fetch_klines("BTC", "1d", 400)
    btc_vol = calc_30d_volatility(btc_klines_1d)

    # 根据波动率调整参数（所有币种都适用）
    effective_tp_pct, effective_addon_pct = get_vol_adjusted_params(
        BASE_TP_PCT, BASE_ADDON_PCT, coin_vol, btc_vol
    )
    
    # 使用自定义参数覆盖（用于贝叶斯优化）
    if custom_tp_pct is not None:
        effective_tp_pct = custom_tp_pct
    if custom_addon_pct is not None:
        effective_addon_pct = custom_addon_pct

    closes = [float(k["c"]) for k in klines]
    highs = [float(k["h"]) for k in klines]
    lows = [float(k["l"]) for k in klines]

    capital = initial_capital
    position = None
    trades = []

    for i in range(200, len(closes)):
        price_window = closes[:i + 1]
        current_price = closes[i]
        high = highs[i]
        low = lows[i]

        if position is None:
            if position_tf == "1d" and daily_sma_lists is not None:
                sma_30 = daily_sma_lists[30][i]
                sma_60 = daily_sma_lists[60][i]
                sma_120 = daily_sma_lists[120][i]
                sma_200 = daily_sma_lists[200][i]

                if sma_30 is None or sma_60 is None or sma_120 is None or sma_200 is None:
                    continue

                daily_smas = {30: sma_30, 60: sma_60, 120: sma_120, 200: sma_200}
                daily_position = _determine_position(current_price, daily_smas)
                decision = v15_decision(price_window, override_position=daily_position, override_smas=daily_smas)
            else:
                decision = v15_decision(price_window)

            action = decision.get("action", "WAIT")
            conf = decision.get("confidence", 0)
            vol_mult = decision.get("vol_mult", 1.0)

            if action in ("OPEN_BULL", "OPEN_BEAR") and conf >= confidence_threshold:
                # 只做多模式：忽略做空信号
                if long_only and action == "OPEN_BEAR":
                    continue
                
                # 趋势过滤：下跌趋势中禁止做多马丁
                if "BULL" in action and trend_filter_mode != "none":
                    w_ma = trend_weekly_ma[i] if trend_weekly_ma and i < len(trend_weekly_ma) else 0
                    d_ma = trend_daily_ma[i] if trend_daily_ma and i < len(trend_daily_ma) else 0
                    if check_trend_filter(current_price, w_ma, d_ma, trend_filter_mode):
                        continue

                direction = "LONG" if "BULL" in action else "SHORT"
                addon_pct = effective_addon_pct * vol_mult
                tp_pct = effective_tp_pct * vol_mult

                if direction == "LONG":
                    tp_price = current_price * (1 + tp_pct)
                    addon_prices = [current_price * (1 - addon_pct * j) for j in range(1, max_addons + 1)]
                else:
                    tp_price = current_price * (1 - tp_pct)
                    addon_prices = [current_price * (1 + addon_pct * j) for j in range(1, max_addons + 1)]

                position_size = capital * base_position_pct / current_price
                position = {
                    "direction": direction,
                    "entry_idx": i,
                    "last_addon_idx": i,
                    "entry_price": current_price,
                    "current_level": 0,
                    "total_size": position_size,
                    "avg_entry": current_price,
                    "total_cost": position_size * current_price,
                    "tp_price": tp_price,
                    "addon_prices": addon_prices,
                    "vol_mult": vol_mult,
                    "confidence": conf,
                    "entry_reason": decision.get("position", ""),
                    "long_only": long_only,
                }
        else:
            direction = position["direction"]
            tp_price = position["tp_price"]

            hit_tp = False
            hit_sl = False
            exit_price = None

            if direction == "LONG":
                if high >= tp_price:
                    hit_tp = True
                    exit_price = tp_price
            else:
                if low <= tp_price:
                    hit_tp = True
                    exit_price = tp_price

            # MA200动态止损（所有币种都使用）
            if not hit_tp and not hit_sl and daily_ma200_list is not None:
                daily_ma200 = daily_ma200_list[i]
                weekly_ma200 = weekly_ma200_list[i] if weekly_ma200_list else None
                last_d_close = last_daily_close_list[i] if last_daily_close_list else None
                last_w_close = last_weekly_close_list[i] if last_weekly_close_list else None

                if daily_ma200 is not None or weekly_ma200 is not None:
                    stop_line, triggered, sl_type = get_ma200_stop_loss(
                        direction, current_price, daily_ma200, weekly_ma200,
                        last_d_close, last_w_close
                    )
                    if triggered:
                        hit_sl = True
                        position["sl_type"] = sl_type
                        if stop_line is not None:
                            exit_price = stop_line
                        else:
                            exit_price = current_price

            # 加仓检查
            if not hit_tp and not hit_sl:
                next_level = position["current_level"] + 1
                if next_level <= max_addons:
                    next_addon_price = position["addon_prices"][next_level - 1]
                    should_add = False

                    if direction == "LONG" and low <= next_addon_price:
                        should_add = True
                        addon_exec_price = next_addon_price
                    elif direction == "SHORT" and high >= next_addon_price:
                        should_add = True
                        addon_exec_price = next_addon_price

                    if should_add:
                        addon_size = capital * base_position_pct / addon_exec_price
                        position["total_cost"] += addon_size * addon_exec_price
                        position["total_size"] += addon_size
                        position["avg_entry"] = position["total_cost"] / position["total_size"]
                        position["current_level"] = next_level
                        position["last_addon_idx"] = i

            # ── 超时触发经典离场系统评估 ──────────────────────────────
            if not hit_tp and not hit_sl:
                hit_time_exit = False
                time_exit_action = None

                current_level = position["current_level"]
                HOURS_PER_BAR = 4.0

                if current_level > 0:
                    # 有加仓：从最后加仓计时
                    bars_since_addon = i - position["last_addon_idx"]
                    hold_hours = bars_since_addon * HOURS_PER_BAR
                    if hold_hours >= golden_window_hours and hold_hours >= max_post_addon_hours:
                        time_exit_action = "evaluate"
                else:
                    # 无加仓：从开仓计时
                    bars_held = i - position["entry_idx"]
                    hold_hours = bars_held * HOURS_PER_BAR
                    if hold_hours >= max_base_holding_hours:
                        time_exit_action = "evaluate"

                if time_exit_action == "evaluate":
                    try:
                        classic_path = str(Path(__file__).parent.parent.parent / "10-经典指标系统")
                        if classic_path not in sys.path:
                            sys.path.insert(0, classic_path)
                        from classic_exit_system import ClassicExitSystem, PositionState as ExitPosState, ExitConfig
                        if not hasattr(run_backtest, '_exit_system'):
                            exit_cfg = ExitConfig()
                            exit_cfg.l0_max_hold_sec = 999999  # 禁用L0持仓时间硬退出（马丁策略有自己的超时逻辑）
                            run_backtest._exit_system = ClassicExitSystem(config=exit_cfg)
                        system = run_backtest._exit_system

                        avg_entry = position["avg_entry"]
                        if direction == "LONG":
                            unrealized_pnl_pct = (current_price - avg_entry) / avg_entry
                        else:
                            unrealized_pnl_pct = (avg_entry - current_price) / avg_entry

                        pos_state = ExitPosState(
                            coin=coin,
                            side="long" if direction == "LONG" else "short",
                            entry_price=avg_entry,
                            current_price=current_price,
                            position_age_sec=hold_hours * 3600.0,
                            unrealized_pnl_pct=unrealized_pnl_pct,
                            leverage=1.0,
                            atr_pct=coin_vol if coin_vol > 0 else 0.02,
                        )

                        # 将4H klines 转换为 evaluate_full 可用的 candles 格式
                        # _compute_features 期望 List[Dict]，每条含 c/h/l/o/v 字段
                        # 回测使用 4H 数据（klines 字段为 c/h/l/o/t），i>=200 保证 ≥201 根足够计算特征
                        candles_for_exit = klines[:i+1]
                        decision = system.evaluate_full(pos_state, candles_1h=candles_for_exit, regime="trend")
                        action_val = decision.action.value if hasattr(decision.action, 'value') else str(decision.action)

                        if action_val == "close":
                            hit_time_exit = True
                            exit_price = current_price
                            position["sl_type"] = f"time_exit:{decision.reason[:30]}"
                        elif action_val == "raise_tp":
                            new_tp_pct = decision.new_tp_pct
                            original_tp_pct = tp_pct
                            capped_tp = min(new_tp_pct, original_tp_pct * 2.0)
                            if direction == "LONG":
                                position["tp_price"] = current_price * (1 + capped_tp)
                            else:
                                position["tp_price"] = current_price * (1 - capped_tp)
                            tp_price = position["tp_price"]
                        elif action_val == "reduce":
                            reduce_frac = decision.reduce_frac if decision.reduce_frac > 0 else 0.3
                            reduce_cost = position["total_cost"] * reduce_frac
                            position["total_cost"] -= reduce_cost
                            position["total_size"] *= (1 - reduce_frac)
                        # hold: 不做任何操作

                    except Exception:
                        # 降级：超时直接平仓
                        hit_time_exit = True
                        exit_price = current_price
                        position["sl_type"] = "time_exit:fallback"

                if hit_time_exit:
                    hit_sl = True

            if hit_tp or hit_sl:
                avg_entry = position["avg_entry"]

                if direction == "LONG":
                    pnl_pct = (exit_price - avg_entry) / avg_entry
                else:
                    pnl_pct = (avg_entry - exit_price) / avg_entry

                pnl_usd = pnl_pct * position["total_cost"]
                capital += pnl_usd

                trade = {
                    "entry_idx": position["entry_idx"],
                    "exit_idx": i,
                    "entry_price": round(position["entry_price"], 2),
                    "avg_entry": round(avg_entry, 2),
                    "exit_price": round(exit_price, 2),
                    "side": direction,
                    "pnl_pct": round(pnl_pct * 100, 2),
                    "pnl_usd": round(pnl_usd, 2),
                    "exit_reason": "take_profit" if hit_tp else ("time_exit" if position.get("sl_type", "").startswith("time_exit") else "ma200_stop"),
                    "sl_type": position.get("sl_type", "") if hit_sl else "",
                    "bars_held": i - position["entry_idx"],
                    "levels_used": position["current_level"] + 1,
                    "confidence": position["confidence"],
                    "vol_mult": position["vol_mult"],
                    "entry_reason": position["entry_reason"],
                    "long_only": position.get("long_only", False),
                }
                trades.append(trade)
                position = None

    final_capital = capital
    total_return = (final_capital - initial_capital) / initial_capital * 100

    if trades:
        wins = [t for t in trades if t["pnl_pct"] > 0]
        losses = [t for t in trades if t["pnl_pct"] <= 0]
        win_rate = len(wins) / len(trades) if trades else 0

        avg_win = sum(t["pnl_pct"] for t in wins) / len(wins) if wins else 0
        avg_loss = abs(sum(t["pnl_pct"] for t in losses) / len(losses)) if losses else 0
        profit_factor = avg_win / avg_loss if avg_loss > 0 else 0

        equity_curve = [initial_capital]
        current_eq = initial_capital
        peak_eq = initial_capital
        max_drawdown = 0

        for t in trades:
            current_eq += t["pnl_usd"]
            equity_curve.append(current_eq)
            peak_eq = max(peak_eq, current_eq)
            dd = (peak_eq - current_eq) / peak_eq * 100
            max_drawdown = max(max_drawdown, dd)

        returns = [t["pnl_pct"] / 100 for t in trades]
        if len(returns) > 1:
            avg_return = sum(returns) / len(returns)
            variance = sum((r - avg_return) ** 2 for r in returns) / len(returns)
            std_return = variance ** 0.5
            sharpe = (avg_return / std_return) * (len(trades) ** 0.5) if std_return > 0 else 0
        else:
            sharpe = 0

        max_consecutive_wins = 0
        max_consecutive_losses = 0
        cur_wins = 0
        cur_losses = 0
        for t in trades:
            if t["pnl_pct"] > 0:
                cur_wins += 1
                cur_losses = 0
                max_consecutive_wins = max(max_consecutive_wins, cur_wins)
            else:
                cur_losses += 1
                cur_wins = 0
                max_consecutive_losses = max(max_consecutive_losses, cur_losses)

        level_dist = {}
        for t in trades:
            lv = t["levels_used"]
            level_dist[lv] = level_dist.get(lv, 0) + 1

        reason_dist = {}
        for t in trades:
            r = t.get("entry_reason", "unknown")
            reason_dist[r] = reason_dist.get(r, 0) + 1

        ma200_trades = sum(1 for t in trades if t.get("use_ma200"))

        metrics = {
            "total_trades": len(trades),
            "win_rate": round(win_rate, 4),
            "profit_factor": round(profit_factor, 4),
            "avg_win_pct": round(avg_win, 2),
            "avg_loss_pct": round(avg_loss, 2),
            "total_return_pct": round(total_return, 2),
            "final_capital": round(final_capital, 2),
            "max_drawdown_pct": round(max_drawdown, 2),
            "sharpe_ratio": round(sharpe, 4),
            "avg_bars_held": round(sum(t["bars_held"] for t in trades) / len(trades), 1),
            "max_consecutive_wins": max_consecutive_wins,
            "max_consecutive_losses": max_consecutive_losses,
            "level_distribution": level_dist,
            "entry_reason_dist": reason_dist,
            "ma200_stop_trades": ma200_trades,
            "coin_volatility": round(coin_vol * 100, 2),
            "btc_volatility": round(btc_vol * 100, 2),
            "vol_ratio": round(coin_vol / btc_vol, 2) if btc_vol > 0 else 1.0,
            "effective_tp_pct": round(effective_tp_pct * 100, 2),
            "effective_addon_pct": round(effective_addon_pct * 100, 2),
        }
    else:
        metrics = {
            "total_trades": 0,
            "win_rate": 0,
            "profit_factor": 0,
            "avg_win_pct": 0,
            "avg_loss_pct": 0,
            "total_return_pct": round(total_return, 2),
            "final_capital": round(final_capital, 2),
            "max_drawdown_pct": 0,
            "sharpe_ratio": 0,
            "avg_bars_held": 0,
            "max_consecutive_wins": 0,
            "max_consecutive_losses": 0,
            "level_distribution": {},
            "entry_reason_dist": {},
            "ma200_stop_trades": 0,
            "coin_volatility": round(coin_vol * 100, 2),
            "btc_volatility": round(btc_vol * 100, 2),
            "vol_ratio": 1.0,
            "effective_tp_pct": round(effective_tp_pct * 100, 2),
            "effective_addon_pct": round(effective_addon_pct * 100, 2),
        }

    return {
        "coin": coin,
        "initial_capital": initial_capital,
        "base_position_pct": base_position_pct,
        "max_addons": max_addons,
        "confidence_threshold": confidence_threshold,
        "klines_count": len(closes),
        "long_only": long_only,
        "position_tf": position_tf,
        "trades": trades,
        "metrics": metrics,
    }


# ── 报告输出 ──────────────────────────────────────────────────────────────

def print_report(result: Dict):
    """打印回测报告"""
    if "error" in result:
        print(f"❌ 回测错误: {result['error']}")
        return

    m = result["metrics"]
    print("\n" + "=" * 70)
    print(f"  V15策略回测报告 — {result['coin']} (4H周期)")
    print("=" * 70)
    print(f"  回测周期: {result['klines_count']} 根K线 ({result['klines_count'] * 4 / 24:.0f}天)")
    print(f"  初始资金: ${result['initial_capital']:,.2f}")
    print(f"  最终资金: ${m['final_capital']:,.2f}")
    print(f"  基础仓位: {result['base_position_pct'] * 100:.1f}%")
    print(f"  最大加仓: {result['max_addons']} 层")
    print(f"  止损模式: MA200动态止损 (日线+周线)")
    print(f"  位置判定: {'日线均线(SMA30/60/120/200)' if result.get('position_tf') == '1d' else '4H均线(SMA30/65/128/200)'}")
    print(f"  交易方向: {'只做多' if result.get('long_only') else '多空双向'}")
    if m.get("effective_tp_pct") != 4.0:
        print(f"  波动调整: 止盈{m['effective_tp_pct']:.1f}% / 加仓间距{m['effective_addon_pct']:.1f}% (比率{m['vol_ratio']:.2f}x)")
    print("-" * 70)
    print(f"  📊 总收益率: {m['total_return_pct']:+.2f}%")
    print(f"  📈 总交易次数: {m['total_trades']}")
    print(f"  🎯 胜率: {m['win_rate'] * 100:.2f}%")
    print(f"  ⚖️  盈亏比: {m['profit_factor']:.2f}")
    print(f"  📈 平均盈利: +{m['avg_win_pct']:.2f}%")
    print(f"  📉 平均亏损: -{m['avg_loss_pct']:.2f}%")
    print(f"  ⚠️  最大回撤: {m['max_drawdown_pct']:.2f}%")
    print(f"  📊 夏普比率: {m['sharpe_ratio']:.4f}")
    print(f"  ⏱️  平均持仓: {m['avg_bars_held']:.1f} 根K线 ({m['avg_bars_held'] * 4:.0f}小时)")
    print("-" * 70)
    print(f"  🔥 最大连盈: {m['max_consecutive_wins']} 次")
    print(f"  💧 最大连亏: {m['max_consecutive_losses']} 次")
    print(f"  📊 加仓层级分布: {m['level_distribution']}")
    print(f"  🎯 入场原因分布: {m['entry_reason_dist']}")
    if m.get("ma200_stop_trades"):
        print(f"  📈 MA200止损交易: {m['ma200_stop_trades']} 笔")
    print("=" * 70)

    if result["trades"]:
        print("\n  最近10笔交易:")
        print("-" * 70)
        print(f"  {'#':>3} {'方向':>6} {'入场价':>10} {'均价':>10} {'出场价':>10} "
              f"{'收益率':>8} {'层级':>4} {'原因':>12} {'持仓':>5} {'出场':>8}")
        print("-" * 70)
        for idx, t in enumerate(result["trades"][-10:]):
            exit_reason = "止盈" if t.get("exit_reason") == "take_profit" else "MA200"
            print(f"  {idx + 1:>3} {t['side']:>6} {t['entry_price']:>10.2f} {t['avg_entry']:>10.2f} "
                  f"{t['exit_price']:>10.2f} {t['pnl_pct']:>+7.2f}% {t['levels_used']:>4} "
                  f"{t['entry_reason']:>12} {t['bars_held']:>4} {exit_reason:>8}")
        print("=" * 70)


# ── CLI ───────────────────────────────────────────────────────────────────

def main():
    import argparse
    parser = argparse.ArgumentParser(description="V15经典马丁策略回测引擎")
    parser.add_argument("--coin", default="BTC", help="交易币种 (默认: BTC)")
    parser.add_argument("--capital", type=float, default=10000, help="初始资金 (默认: 10000)")
    parser.add_argument("--position", type=float, default=0.05, help="基础仓位比例 (默认: 0.05)")
    parser.add_argument("--addons", type=int, default=3, help="最大加仓层数 (默认: 3)")
    parser.add_argument("--threshold", type=int, default=0, help="入场置信度阈值 (默认: 0)")
    parser.add_argument("--limit", type=int, default=1500, help="4H K线数量 (默认: 1500)")
    parser.add_argument("--multi", action="store_true", help="多币种回测")
    parser.add_argument("--allow-short", action="store_true", help="允许做空（默认只做多）")
    parser.add_argument("--compare", action="store_true", help="对比多空双向 vs 只做多")
    parser.add_argument("--compare-position", action="store_true", help="对比4H均线 vs 日线均线位置判定")
    parser.add_argument("--position-tf", default="4h", choices=["4h", "1d"], help="位置判定时间框架 (默认: 4h)")
    args = parser.parse_args()

    if args.compare_position:
        coin = args.coin
        print("🚀 V15策略回测 - 4H均线 vs 日线均线 位置判定对比")
        klines = fetch_klines(coin, "4h", args.limit)
        all_results = []

        for tf in ["4h", "1d"]:
            tf_label = "4H均线" if tf == "4h" else "日线均线"
            print(f"\n  --- {tf_label} ---")
            result = run_backtest(
                coin=coin,
                klines=klines,
                initial_capital=args.capital,
                base_position_pct=args.position,
                max_addons=args.addons,
                confidence_threshold=args.threshold,
                long_only=not args.allow_short,
                position_tf=tf,
            )
            print_report(result)
            all_results.append((tf, result))

        print("\n" + "=" * 80)
        print(f"  📊 4H均线 vs 日线均线 对比汇总 — {coin}")
        print("=" * 80)
        print(f"  {'模式':>12} {'总收益':>10} {'交易数':>6} {'胜率':>8} {'盈亏比':>8} "
              f"{'最大回撤':>10} {'夏普':>8} {'连盈':>5} {'连亏':>5}")
        print("-" * 80)
        for tf, r in all_results:
            if "error" not in r:
                m = r["metrics"]
                tf_str = "4H均线" if tf == "4h" else "日线均线"
                print(f"  {tf_str:>12} {m['total_return_pct']:>+8.2f}% {m['total_trades']:>6} "
                      f"{m['win_rate']*100:>7.2f}% {m['profit_factor']:>8.2f} "
                      f"{m['max_drawdown_pct']:>9.2f}% {m['sharpe_ratio']:>8.4f} "
                      f"{m['max_consecutive_wins']:>5} {m['max_consecutive_losses']:>5}")
        print("=" * 80)

    elif args.compare:
        coins = ["BTC", "ETH", "SOL", "ARB", "OP"]
        print("🚀 多币种V15策略回测 - 多空双向 vs 只做多对比")
        all_results = []
        for coin in coins:
            print(f"\n{'='*60}")
            print(f"  回测 {coin}...")
            klines = fetch_klines(coin, "4h", args.limit)

            print(f"\n  --- 多空双向 ---")
            result_both = run_backtest(
                coin=coin,
                klines=klines,
                initial_capital=args.capital,
                base_position_pct=args.position,
                max_addons=args.addons,
                confidence_threshold=args.threshold,
                long_only=False,
            )
            print_report(result_both)
            all_results.append(("both", result_both))

            print(f"\n  --- 只做多 ---")
            result_long = run_backtest(
                coin=coin,
                klines=klines,
                initial_capital=args.capital,
                base_position_pct=args.position,
                max_addons=args.addons,
                confidence_threshold=args.threshold,
                long_only=True,
            )
            print_report(result_long)
            all_results.append(("long", result_long))

        print("\n" + "=" * 80)
        print("  📊 多空双向 vs 只做多 对比汇总")
        print("=" * 80)
        print(f"  {'币种':>6} {'模式':>8} {'总收益':>10} {'交易数':>6} {'胜率':>8} {'盈亏比':>8} "
              f"{'最大回撤':>10} {'夏普':>8}")
        print("-" * 80)
        for mode, r in all_results:
            if "error" not in r:
                m = r["metrics"]
                mode_str = "只做多" if mode == "long" else "多空"
                print(f"  {r['coin']:>6} {mode_str:>8} {m['total_return_pct']:>+8.2f}% {m['total_trades']:>6} "
                      f"{m['win_rate']*100:>7.2f}% {m['profit_factor']:>8.2f} "
                      f"{m['max_drawdown_pct']:>9.2f}% {m['sharpe_ratio']:>8.4f}")
        print("=" * 80)

    elif args.multi:
        coins = ["BTC", "ETH", "SOL", "ARB", "OP"]
        mode_str = "多空双向" if args.allow_short else "只做多"
        print(f"🚀 多币种V15策略回测 v3 ({mode_str})")
        all_results = []
        for coin in coins:
            print(f"\n{'='*60}")
            print(f"  回测 {coin}...")
            klines = fetch_klines(coin, "4h", args.limit)
            result = run_backtest(
                coin=coin,
                klines=klines,
                initial_capital=args.capital,
                base_position_pct=args.position,
                max_addons=args.addons,
                confidence_threshold=args.threshold,
                long_only=not args.allow_short,
            )
            print_report(result)
            all_results.append(result)

        print("\n" + "=" * 70)
        print("  📊 多币种汇总")
        print("=" * 70)
        print(f"  {'币种':>6} {'总收益':>10} {'交易数':>6} {'胜率':>8} {'盈亏比':>8} "
              f"{'最大回撤':>10} {'夏普':>8} {'波动率':>8}")
        print("-" * 70)
        total_return = 0
        total_trades = 0
        for r in all_results:
            if "error" not in r:
                m = r["metrics"]
                total_return += m["total_return_pct"]
                total_trades += m["total_trades"]
                vol_str = f"{m['vol_ratio']:.2f}x" if m.get("vol_ratio") else "1.00x"
                print(f"  {r['coin']:>6} {m['total_return_pct']:>+8.2f}% {m['total_trades']:>6} "
                      f"{m['win_rate']*100:>7.2f}% {m['profit_factor']:>8.2f} "
                      f"{m['max_drawdown_pct']:>9.2f}% {m['sharpe_ratio']:>8.4f} {vol_str:>8}")
        print("-" * 70)
        print(f"  {'平均':>6} {total_return/len(all_results):>+8.2f}% {total_trades:>6}")
        print("=" * 70)
    else:
        klines = fetch_klines(args.coin, "4h", args.limit)
        result = run_backtest(
            coin=args.coin,
            klines=klines,
            initial_capital=args.capital,
            base_position_pct=args.position,
            max_addons=args.addons,
            confidence_threshold=args.threshold,
            long_only=not args.allow_short,
            position_tf=args.position_tf,
        )
        print_report(result)


if __name__ == "__main__":
    main()
