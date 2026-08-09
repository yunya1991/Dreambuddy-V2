#!/usr/bin/env python3
"""
V15 经典马丁策略回测引擎
- 4H周期K线
- 马丁加仓（最多3层）
- 斐波那契+布林带+MACD+ADX入场
- 所有币种: 动态MA200止损（日线/周线）
- 所有币种: 根据30天波动率调整止盈和加仓间距
- 支持多空双向：DirectionGate根据日/周MA200控制方向开关
"""
import copy
import json
import sys
import time
import warnings
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import requests

# DirectionGate 多空方向控制
sys.path.insert(0, str(Path(__file__).parent.parent / "lib"))
try:
    from direction_gate import DirectionGate, MarketRegime

    _DIRECTION_GATE_AVAILABLE = True
except ImportError:
    _DIRECTION_GATE_AVAILABLE = False

# Phase 4: TimingGate（波浪+斐波那契时机软调控，基于三浪结构识别+fib回撤质量）
try:
    from timing_gate import TimingGate

    _TIMING_GATE_AVAILABLE = True
except ImportError:
    _TIMING_GATE_AVAILABLE = False

try:
    from strategy_params import calc_elder_ray

    _ELDER_RAY_AVAILABLE = True
except ImportError:
    _ELDER_RAY_AVAILABLE = False

warnings.filterwarnings("ignore")

BASE_DIR = Path(__file__).parent.parent
CACHE_DIR = BASE_DIR / "data" / "backtest_cache"
CACHE_DIR.mkdir(parents=True, exist_ok=True)

# ELDER-RAY 资金调度范围（贝叶斯优化最优值，可被优化器动态修改）
_elder_ray_floor = 0.9
_elder_ray_ceil = 1.5

MAX_ADDONS = 4  # 1首单 + 4加仓 = 最多5单（实盘验证版本，按用户要求开启5档）
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
        return "IN_ZONE"
    if all(price > v for v in valid.values()):
        return "ABOVE_ALL"
    if all(price < v for v in valid.values()):
        return "BELOW_ALL"
    return "IN_ZONE"


def _calc_fibonacci(prices, lookback=30):
    window = prices[-lookback:]
    swing_high = max(window)
    swing_low = min(window)
    rng = swing_high - swing_low
    return {
        "swing_high": round(swing_high),
        "swing_low": round(swing_low),
        "f382": round(swing_low + 0.382 * rng),
        "f500": round(swing_low + 0.500 * rng),
        "f618": round(swing_low + 0.618 * rng),
        "range": rng,
    }


def _calc_bollinger_bands(prices, period=20, num_std=2):
    if len(prices) < period:
        return None
    sma = sum(prices[-period:]) / period
    if sma == 0:
        return None
    variance = sum((p - sma) ** 2 for p in prices[-period:]) / period
    std = variance**0.5
    upper = sma + num_std * std
    lower = sma - num_std * std
    pct_b = (prices[-1] - lower) / (upper - lower) if upper != lower else 0.5
    return {
        "sma": round(sma, 2),
        "upper": round(upper, 2),
        "lower": round(lower, 2),
        "std": round(std, 2),
        "bandwidth": round(2 * num_std * std / sma * 100, 2),
        "pct_b": round(pct_b, 3),
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
    cross = "none"
    if len(hist) >= 2:
        if hist[-1] > 0 and hist[-2] <= 0:
            cross = "golden"
        elif hist[-1] < 0 and hist[-2] >= 0:
            cross = "death"
    expanding = len(hist) >= 2 and abs(hist[-1]) > abs(hist[-2])
    return {
        "macd": round(macd_line[-1], 4),
        "signal": round(signal_line[-1], 4),
        "hist": round(hist[-1], 4),
        "hist_prev": round(hist[-2], 4) if len(hist) >= 2 else 0,
        "cross": cross,
        "expanding": expanding,
        "bearish": hist[-1] < 0,
        "bullish": hist[-1] > 0,
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
        "adx": round(adx, 2),
        "strong": adx > 25,
        "very_strong": adx > 40,
        "di_plus": round(100 * pdm[-1] / atr[-1], 2) if atr and atr[-1] > 0 else 0,
        "di_minus": round(100 * mdm[-1] / atr[-1], 2) if atr and atr[-1] > 0 else 0,
    }


# ── 数据获取 ──────────────────────────────────────────────────────────────


def fetch_klines(coin: str, interval: str = "4h", limit: int = 1000) -> List[Dict]:
    """获取历史K线数据（带缓存）— 返回深拷贝避免副作用"""
    cache_file = CACHE_DIR / f"{coin}_{interval}_{limit}.json"

    if cache_file.exists():
        try:
            with open(cache_file) as f:
                cached = json.load(f)
            cache_age = time.time() - cached.get("cached_at", 0)
            if cache_age < 86400 * 7:  # 缓存7天
                return copy.deepcopy(cached.get("data", []))
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
            ma200.append(sum(closes[i - 199 : i + 1]) / 200)
        else:
            ma200.append(None)
    return ma200


def calc_ma_series(closes: List[float], period: int) -> List[Optional[float]]:
    """计算指定周期的MA序列"""
    ma = []
    for i in range(len(closes)):
        if i >= period - 1:
            ma.append(sum(closes[i - period + 1 : i + 1]) / period)
        else:
            ma.append(None)
    return ma


def prepare_daily_sma_for_4h(
    klines_4h: List[Dict], klines_1d: List[Dict], periods: List[int]
) -> Dict[int, List[Optional[float]]]:
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
                ma_list.append(sum(daily_closes[i - p + 1 : i + 1]) / p)
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


def prepare_ma200_for_4h(
    klines_4h: List[Dict], klines_1d: List[Dict], klines_1w: List[Dict]
) -> Tuple[List[Optional[float]], List[Optional[float]]]:
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


def _calc_ema_series(closes: List[float], period: int) -> List[Optional[float]]:
    """计算EMA序列（与实盘strategy_params._calc_ema一致）"""
    n = len(closes)
    ema_list = [None] * n
    if n < period:
        return ema_list
    k = 2 / (period + 1)
    ema = closes[0]
    for i in range(n):
        if i > 0:
            ema = closes[i] * k + ema * (1 - k)
        if i >= period - 1:
            ema_list[i] = ema
    return ema_list


def prepare_ema200_for_4h(
    klines_4h: List[Dict], klines_1d: List[Dict], klines_1w: List[Dict]
) -> Tuple[List[Optional[float]], List[Optional[float]]]:
    """
    为4H数据准备日线EMA200和周线EMA200序列（用于MA200+EMA200止损对比回测）
    返回: (daily_ema200_list, weekly_ema200_list)，长度与klines_4h相同
    """
    n = len(klines_4h)
    daily_ema200_for_4h = [None] * n
    weekly_ema200_for_4h = [None] * n

    # 计算日线EMA200
    if len(klines_1d) >= 200:
        daily_closes = [float(k["c"]) for k in klines_1d]
        daily_ema200_series = _calc_ema_series(daily_closes, 200)

        daily_ema200_dict = {}
        for k, ema in zip(klines_1d, daily_ema200_series):
            if ema is not None:
                date_str = _timestamp_to_date_str(k["t"])
                daily_ema200_dict[date_str] = ema

        for i, k in enumerate(klines_4h):
            date_str = _timestamp_to_date_str(k["t"])
            daily_ema200_for_4h[i] = daily_ema200_dict.get(date_str)

    # 计算周线EMA200
    if len(klines_1w) >= 200:
        weekly_closes = [float(k["c"]) for k in klines_1w]
        weekly_ema200_series = _calc_ema_series(weekly_closes, 200)

        weekly_ema200_dict = {}
        for k, ema in zip(klines_1w, weekly_ema200_series):
            if ema is not None:
                week_str = _timestamp_to_week_start_str(k["t"])
                weekly_ema200_dict[week_str] = ema

        for i, k in enumerate(klines_4h):
            week_str = _timestamp_to_week_start_str(k["t"])
            weekly_ema200_for_4h[i] = weekly_ema200_dict.get(week_str)

    return daily_ema200_for_4h, weekly_ema200_for_4h


def prepare_ma128_for_4h(klines_4h: List[Dict], klines_1d: List[Dict]) -> List[Optional[float]]:
    """
    为4H数据准备日线MA128序列（用于DirectionGate多空方向控制）
    返回: daily_ma128_list，长度与klines_4h相同
    """
    n = len(klines_4h)
    daily_ma128_for_4h = [None] * n

    if len(klines_1d) >= 128:
        daily_closes = [float(k["c"]) for k in klines_1d]
        daily_ma128_series = calc_ma_series(daily_closes, 128)

        daily_ma128_dict = {}
        for k, ma in zip(klines_1d, daily_ma128_series):
            if ma is not None:
                date_str = _timestamp_to_date_str(k["t"])
                daily_ma128_dict[date_str] = ma

        for i, k in enumerate(klines_4h):
            date_str = _timestamp_to_date_str(k["t"])
            daily_ma128_for_4h[i] = daily_ma128_dict.get(date_str)

    return daily_ma128_for_4h


def prepare_last_close_for_4h(
    klines_4h: List[Dict], klines_1d: List[Dict], klines_1w: List[Dict]
) -> Tuple[List[Optional[float]], List[Optional[float]]]:
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


def get_ma200_stop_loss(
    direction: str,
    close: float,
    daily_ma200: Optional[float],
    weekly_ma200: Optional[float],
    last_daily_close: Optional[float] = None,
    last_weekly_close: Optional[float] = None,
) -> Tuple[Optional[float], bool, str]:
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
            if (
                daily_ma200 is not None
                and last_daily_close is not None
                and last_daily_close > daily_ma200
            ):
                all_below_daily = False
            all_below_weekly = True
            if (
                weekly_ma200 is not None
                and last_weekly_close is not None
                and last_weekly_close > weekly_ma200
            ):
                all_below_weekly = False

            all_confirmed_below = all_below_daily and all_below_weekly
            return None, all_confirmed_below, "BELOW_ALL_MA"


def get_ma200_ema200_stop_loss(
    direction: str,
    close: float,
    daily_ma200: Optional[float],
    weekly_ma200: Optional[float],
    daily_ema200: Optional[float],
    weekly_ema200: Optional[float],
    last_daily_close: Optional[float] = None,
    last_weekly_close: Optional[float] = None,
) -> Tuple[Optional[float], bool, str]:
    """
    MA200+EMA200动态止损逻辑（与实盘strategy_params.get_dynamic_stop_loss一致）

    四条候选均线: 日MA200、日EMA200、周MA200、周EMA200
    止损线 = 价格下方（做多）/上方（做空）最近的一条
    触发 = 对应周期已收盘价确认跌破/突破

    返回: (止损线价格, 是否触发止损, 止损类型)
    """
    if (
        daily_ma200 is None
        and weekly_ma200 is None
        and daily_ema200 is None
        and weekly_ema200 is None
    ):
        return None, False, "NONE"

    if direction == "SHORT":
        candidates = []
        if daily_ma200 is not None and daily_ma200 > close:
            candidates.append((daily_ma200, daily_ma200 - close, "daily", "日MA200"))
        if daily_ema200 is not None and daily_ema200 > close:
            candidates.append((daily_ema200, daily_ema200 - close, "daily", "日EMA200"))
        if weekly_ma200 is not None and weekly_ma200 > close:
            candidates.append((weekly_ma200, weekly_ma200 - close, "weekly", "周MA200"))
        if weekly_ema200 is not None and weekly_ema200 > close:
            candidates.append((weekly_ema200, weekly_ema200 - close, "weekly", "周EMA200"))

        if candidates:
            candidates.sort(key=lambda x: x[1])
            stop_price, _, period, stop_type = candidates[0]
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
            candidates.append((daily_ma200, close - daily_ma200, "daily", "日MA200"))
        if daily_ema200 is not None and daily_ema200 < close:
            candidates.append((daily_ema200, close - daily_ema200, "daily", "日EMA200"))
        if weekly_ma200 is not None and weekly_ma200 < close:
            candidates.append((weekly_ma200, close - weekly_ma200, "weekly", "周MA200"))
        if weekly_ema200 is not None and weekly_ema200 < close:
            candidates.append((weekly_ema200, close - weekly_ema200, "weekly", "周EMA200"))

        if candidates:
            candidates.sort(key=lambda x: x[1])
            stop_price, _, period, stop_type = candidates[0]
            triggered = False
            if period == "daily" and last_daily_close is not None:
                triggered = last_daily_close <= stop_price
            elif period == "weekly" and last_weekly_close is not None:
                triggered = last_weekly_close <= stop_price
            return stop_price, triggered, stop_type
        else:
            # 所有均线都在价格上方 → 检查是否全部确认跌破
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
    return variance**0.5


def calc_atr(klines: List[Dict], period: int = 14) -> Optional[float]:
    """计算ATR（平均真实波幅）"""
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
    """计算ATR占价格百分比"""
    atr = calc_atr(klines, period)
    if atr is None or not klines:
        return None
    current_price = float(klines[-1].get("c", 0))
    if current_price <= 0:
        return None
    return (atr / current_price) * 100


def prepare_atr_pct_for_4h(klines_4h: List[Dict], period: int = 14) -> List[Optional[float]]:
    """为每根4H K线预计算ATR百分比（滑动窗口）"""
    n = len(klines_4h)
    result = [None] * n
    for i in range(period, n):
        window = klines_4h[: i + 1]
        atr_pct = calc_atr_pct(window, period)
        result[i] = atr_pct
    return result


def calc_elder_ray_size_mult(elder_ray: Dict, direction: str = "LONG") -> float:
    """根据Elder-ray趋势强度计算仓位调整倍数
    对齐 capital_manager.py 中的 calculate_per_coin_allocation 逻辑
    返回: 0.3x - 1.5x 之间的乘数
    """
    if not elder_ray:
        return 1.0

    strength = elder_ray.get("strength", 50)
    dir_er = elder_ray.get("direction", "BULL_TREND")
    ema_trend = elder_ray.get("ema_trend", "flat")
    both_weakening = elder_ray.get("both_weakening", False)
    bullish_div = elder_ray.get("bullish_divergence", False)
    bearish_div = elder_ray.get("bearish_divergence", False)

    # 基于 EMA 趋势方向 + Elder-ray 状态决定乘数
    if ema_trend == "up":
        if dir_er == "STRONG_BULL":
            strength_mult = 1.2 + (strength / 100) * 0.3  # 1.2 - 1.5
        elif dir_er == "BULL_TREND":
            strength_mult = 1.0 + (strength / 100) * 0.3  # 1.0 - 1.3
        elif dir_er == "BULL_REVERSAL":
            strength_mult = 0.5 + (strength / 100) * 0.3  # 0.5 - 0.8
        else:
            strength_mult = 0.8 + (strength / 100) * 0.2  # 0.8 - 1.0
    elif ema_trend == "down":
        if dir_er == "STRONG_BEAR":
            strength_mult = 0.3 + (strength / 100) * 0.2  # 0.3 - 0.5
        elif dir_er == "BEAR_TREND":
            strength_mult = 0.4 + (strength / 100) * 0.2  # 0.4 - 0.6
        elif dir_er == "BEAR_REVERSAL":
            strength_mult = 0.7 + (strength / 100) * 0.3  # 0.7 - 1.0
        else:
            strength_mult = 0.5 + (strength / 100) * 0.2  # 0.5 - 0.7
    else:  # flat
        strength_mult = 0.7 + (strength / 100) * 0.3  # 0.7 - 1.0

    # 做多方向加成
    if direction == "LONG" and bullish_div and ema_trend == "up":
        strength_mult *= 1.2
    # 做空方向加成
    if direction == "SHORT" and bearish_div and ema_trend == "down":
        strength_mult *= 1.2

    # 多空都减弱 → 变盘风险 → 降仓
    if both_weakening:
        strength_mult *= 0.7

    return max(_elder_ray_floor, min(_elder_ray_ceil, strength_mult))


def prepare_elder_ray_for_4h(klines_4h: List[Dict], klines_1d: List[Dict]) -> List[Optional[Dict]]:
    """为每根4H K线预计算Elder-ray状态（使用当日日线数据）
    返回: 长度与klines_4h相同的列表，每个元素为elder_ray dict或None
    """
    n = len(klines_4h)
    result = [None] * n

    if not _ELDER_RAY_AVAILABLE or len(klines_1d) < 18:
        return result

    # 按日期索引日线数据
    daily_by_date = {}
    for idx, k in enumerate(klines_1d):
        date_str = _timestamp_to_date_str(k["t"])
        daily_by_date[date_str] = idx

    # 为每根4H K线计算截至当日的elder-ray
    for i in range(n):
        date_str = _timestamp_to_date_str(klines_4h[i]["t"])
        if date_str not in daily_by_date:
            continue
        daily_end_idx = daily_by_date[date_str]
        if daily_end_idx < 17:
            continue
        # 使用截至当日的所有日线数据计算elder-ray
        window = klines_1d[: daily_end_idx + 1]
        elder = calc_elder_ray(window, period=13)
        if elder:
            result[i] = elder

    return result


# ── Phase B+: 子形态参数微调倍数表 ──────────────────────────────────────
# 宏观(BULL/BEAR) × 微观(Elder-ray 子形态) → tp_mult / holding_mult
# 设计原则：小幅微调(±15~20%)，不做整组参数硬覆盖，避免 Phase B 退化
# - STRONG: 趋势强劲 → 放宽TP+延长持仓，让利润跑
# - WEAK:   动能衰竭/逆转 → 收紧TP+缩短持仓，快速离场
# - NORMAL: 基准
DEFAULT_SUBREGIME_MULTS: Dict[str, Dict[str, float]] = {
    "BULL_STRONG":  {"tp_mult": 1.10, "holding_mult": 1.20},
    "BULL_WEAK":    {"tp_mult": 0.85, "holding_mult": 0.70},
    "BULL_NORMAL":  {"tp_mult": 1.00, "holding_mult": 1.00},
    "BEAR_STRONG":  {"tp_mult": 1.10, "holding_mult": 1.20},
    "BEAR_WEAK":    {"tp_mult": 0.85, "holding_mult": 0.70},
    "BEAR_NORMAL":  {"tp_mult": 1.00, "holding_mult": 1.00},
}


def _compute_subregimes(
    elder_ray_list: List[Optional[Dict]],
    macro_regimes: List[str],
    smooth_window: int = 3,
) -> List[str]:
    """基于 Elder-ray 子形态 + 宏观牛熊 → 子形态标签序列

    在宏观 BULL/BEAR 二分（BTC MA128 穿越确认）之下，用 Elder-ray 方向细分
    多种牛熊子形态，做小幅参数微调。

    Args:
        elder_ray_list: 每根 bar 的 Elder-ray dict（可为 None）
        macro_regimes: 每根 bar 的宏观形态（"BULL"/"BEAR"/"RANGE"等，非"BEAR"均按 BULL 处理）
        smooth_window: 众数平滑窗口（默认3 bar），降低 Elder-ray 逐 bar 抖动

    Returns:
        等长子形态标签列表，取值见 DEFAULT_SUBREGIME_MULTS 的 key
    """
    from collections import Counter

    n = len(elder_ray_list)
    # 1. 提取原始 Elder-ray 方向
    raw_dirs = []
    for er in elder_ray_list:
        if er:
            raw_dirs.append(er.get("direction", "SIDEWAYS"))
        else:
            raw_dirs.append("SIDEWAYS")

    # 2. 众数平滑（最近 smooth_window 根的众数）
    smoothed = []
    for i in range(n):
        start = max(0, i - smooth_window + 1)
        window = raw_dirs[start : i + 1]
        cnt = Counter(window)
        smoothed.append(cnt.most_common(1)[0][0])

    # 3. 宏观 × 微观 → 子形态
    subregimes = []
    for i in range(n):
        macro = macro_regimes[i] if i < len(macro_regimes) else "BULL"
        d = smoothed[i]
        if macro == "BEAR":
            if d in ("STRONG_BEAR", "BEAR_TREND"):
                subregimes.append("BEAR_STRONG")
            elif d == "BEAR_REVERSAL":
                subregimes.append("BEAR_WEAK")
            else:
                subregimes.append("BEAR_NORMAL")
        else:  # BULL / RANGE / 其他 → 按 BULL 处理
            if d in ("STRONG_BULL", "BULL_TREND"):
                subregimes.append("BULL_STRONG")
            elif d == "BULL_REVERSAL":
                subregimes.append("BULL_WEAK")
            else:
                subregimes.append("BULL_NORMAL")
    return subregimes


def get_vol_adjusted_params(
    base_tp: float,
    base_addon: float,
    coin_vol: float,
    btc_vol: float,
    coin_atr_pct: Optional[float] = None,
    btc_atr_pct: Optional[float] = None,
) -> Tuple[float, float, float]:
    """
    根据波动率调整参数（含ATR动态因子）
    返回: (调整后的止盈比例, 调整后的加仓间距, atr_factor)
    """
    if btc_vol <= 0:
        ratio = 1.0
    else:
        ratio = coin_vol / btc_vol

    # 限制调整范围 0.5x - 2.0x
    ratio = max(0.5, min(2.0, ratio))

    # ATR动态因子
    atr_factor = 1.0
    if coin_atr_pct is not None and btc_atr_pct is not None and btc_atr_pct > 0:
        atr_factor = coin_atr_pct / btc_atr_pct
        atr_factor = max(0.7, min(1.5, atr_factor))

    return base_tp * ratio * atr_factor, base_addon * ratio * atr_factor, atr_factor


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
        result[i] = sum(closes[i - period + 1 : i + 1]) / period

    return result


def prepare_weekly_ma_for_4h(
    klines_4h: List[Dict], klines_1w: List[Dict], period: int
) -> List[Optional[float]]:
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


def prepare_daily_ma_for_4h(
    klines_4h: List[Dict], klines_1d: List[Dict], period: int
) -> List[Optional[float]]:
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


def check_trend_filter(
    current_price: float, weekly_ma, daily_ma, filter_mode: str = "both_bear"
) -> bool:
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


def v15_decision(
    prices: List[float], override_position: str = None, override_smas: Dict[int, float] = None
) -> dict:
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

    if position == "BELOW_ALL":
        in_zone = fib["f382"] <= current_price <= fib["f618"]
        reasons.append(
            f"BELOW_ALL, Fib区: {fib['f382']}-{fib['f618']}, 现价: {current_price:.0f}, RSI: {rsi}"
        )

        boll_near_mid = boll and abs(current_price - boll["sma"]) / boll["sma"] < 0.02
        boll_touch_upper = boll and current_price >= boll["upper"]

        if (
            in_zone
            and current_price >= fib["f500"]
            and rsi > 45
            and (boll_near_mid or boll_touch_upper)
        ):
            fib_zone = "golden"
            boll_signal = "touch_upper" if boll_touch_upper else "near_mid"
            action = "OPEN_BEAR"
            confidence = 80
            size_mult = 1.0
        elif in_zone and current_price >= fib["f500"] and rsi > 45:
            fib_zone = "golden"
            action = "OPEN_BEAR"
            confidence = 75
            size_mult = 1.0
        elif in_zone and current_price < fib["f500"] and rsi > 45:
            fib_zone = "shallow"
            action = "OPEN_BEAR"
            confidence = 60
            size_mult = 0.5
        elif not in_zone and boll_near_mid and rsi > 50:
            boll_signal = "near_mid"
            action = "OPEN_BEAR"
            confidence = 65
            size_mult = 0.5
        elif rsi > 55 and not in_zone:
            boll_signal = "rsi_extreme"
            action = "OPEN_BEAR"
            confidence = 60
            size_mult = 0.5
        elif macd and macd["bearish"] and macd["expanding"] and rsi > 45:
            trend_signal = "macd_bear"
            action = "OPEN_BEAR"
            confidence = 68
            size_mult = 0.6
        elif adx and adx["strong"] and adx["di_minus"] > adx["di_plus"] and rsi > 45:
            trend_signal = "adx_bear"
            action = "OPEN_BEAR"
            confidence = 70
            size_mult = 0.7

    elif position == "ABOVE_ALL":
        rng = fib["swing_high"] - fib["swing_low"]
        f382_long = round(fib["swing_high"] - 0.382 * rng)
        f500_long = round(fib["swing_high"] - 0.500 * rng)
        f618_long = round(fib["swing_high"] - 0.618 * rng)
        in_zone = f618_long <= current_price <= f382_long

        reasons.append(
            f"ABOVE_ALL, Fib回调区: {f618_long}-{f382_long}, 现价: {current_price:.0f}, RSI: {rsi}"
        )

        boll_near_mid = boll and abs(current_price - boll["sma"]) / boll["sma"] < 0.02
        boll_touch_lower = boll and current_price <= boll["lower"]

        if (
            in_zone
            and current_price <= f500_long
            and rsi < 55
            and (boll_near_mid or boll_touch_lower)
        ):
            fib_zone = "golden"
            boll_signal = "touch_lower" if boll_touch_lower else "near_mid"
            action = "OPEN_BULL"
            confidence = 80
            size_mult = 1.0
        elif in_zone and current_price <= f500_long and rsi < 55:
            fib_zone = "golden"
            action = "OPEN_BULL"
            confidence = 75
            size_mult = 1.0
        elif in_zone and current_price > f500_long and rsi < 55:
            fib_zone = "shallow"
            action = "OPEN_BULL"
            confidence = 60
            size_mult = 0.5
        elif not in_zone and boll_near_mid and rsi < 50:
            boll_signal = "near_mid"
            action = "OPEN_BULL"
            confidence = 65
            size_mult = 0.5
        elif rsi < 45 and not in_zone:
            boll_signal = "rsi_extreme"
            action = "OPEN_BULL"
            confidence = 60
            size_mult = 0.5
        elif macd and macd["bullish"] and macd["expanding"] and rsi < 55:
            trend_signal = "macd_bull"
            action = "OPEN_BULL"
            confidence = 68
            size_mult = 0.6
        elif adx and adx["strong"] and adx["di_plus"] > adx["di_minus"] and rsi < 55:
            trend_signal = "adx_bull"
            action = "OPEN_BULL"
            confidence = 70
            size_mult = 0.7

    else:
        reasons.append(f"IN_ZONE, RSI: {rsi}")
        if boll:
            if current_price <= boll["lower"] and rsi < 45:
                action = "OPEN_BULL"
                confidence = 70
                boll_signal = "touch_lower"
            elif current_price >= boll["upper"] and rsi > 55:
                action = "OPEN_BEAR"
                confidence = 70
                boll_signal = "touch_upper"
            elif rsi < 35:
                action = "OPEN_BULL"
                confidence = 65
                boll_signal = "rsi_extreme"
            elif rsi > 65:
                action = "OPEN_BEAR"
                confidence = 65
                boll_signal = "rsi_extreme"
        else:
            if rsi < 35:
                action = "OPEN_BULL"
                confidence = 65
            elif rsi > 65:
                action = "OPEN_BEAR"
                confidence = 65

    vol_mult = 1.0
    if fib_zone == "golden" and boll_signal in ("touch_upper", "touch_lower"):
        vol_mult = 1.3
    elif fib_zone == "golden":
        vol_mult = 1.2
    elif fib_zone == "shallow":
        vol_mult = 0.8
    elif trend_signal == "adx_bull" or trend_signal == "adx_bear":
        vol_mult = 0.9
    elif trend_signal == "macd_bull" or trend_signal == "macd_bear":
        vol_mult = 0.8
    elif boll_signal in ("touch_upper", "touch_lower"):
        vol_mult = 1.0
    elif boll_signal == "rsi_extreme":
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
    max_base_holding_hours: float = 29.9,
    max_post_addon_hours: float = 37.7,
    golden_window_hours: float = 11.1,
    bounce_filter: Dict = None,
    use_direction_gate: bool = False,
    use_timing_gate: bool = False,   # Phase4: 波浪+斐波那契时机软调控（默认关，向后兼容）
    # ---- Phase4 TimingGate 可调超参（贝叶斯优化透传）：仅 use_timing_gate=True 生效 ----
    timing_gate_apply_to_btc: bool = False,   # False=BTC禁用timing（BTC swing结构不如小币清晰，更安全）
    timing_gate_threshold: float = 0.30,       # BO最优：放宽入场（原0.50）
    timing_gate_strict: bool = False,
    timing_gate_swing_window: int = 2,
    timing_gate_fib_retrace_lo: float = 0.23,  # BO最优：放宽回撤区间（原0.30）
    timing_gate_fib_retrace_hi: float = 0.71,  # BO最优（原0.72）
    timing_gate_fib_ext_ratio: float = 1.62,   # BO最优（原1.618）
    timing_gate_lenient_unclear: float = 0.58, # BO最优（原0.60）
    timing_gate_strict_unclear_score: float = 0.20,
    timing_gate_retrace_mu: float = 0.62,      # BO最优：偏F618（原0.50）
    timing_gate_retrace_sigma: float = 0.34,   # BO最优：更宽容（原0.18）
    timing_gate_unclear_retrace_ext: float = 0.88,  # BO最优（原0.90）
    timing_gate_soft_mode: bool = True,        # BO最优：软调控仓位落位（不做硬门禁continue）
    timing_size_power: float = 2.49,           # BO最优：强惩罚低分（timing_mult=score^2.49）
    timing_gate_swing_fusion_mode: str = "or", # BO最优：日线OR小时级取高分
    timing_gate_intraday_swing_window: int = 3,
    use_atr: bool = True,
    use_kelly: bool = False,
    kelly_base_pct: float = 0.22,
    use_trailing_tp: bool = False,
    trailing_atr_mult: float = 1.0,
    trailing_start_pct_of_tp: float = 0.8,
    use_btc_windvane: bool = False,
    btc_windvane_confirm_days: int = 3,
    btc_windvane_short_only: bool = False,
    regime_cooldown_bars: int = 0,
    regime_params: Dict = None,
    use_elder_ray: bool = True,
    use_ema200: bool = False,
    subregime_enabled: bool = False,
    subregime_mults: Dict = None,
    yijing_enabled: bool = False,
    yijing_step: int = 6,
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
        use_direction_gate: 启用DirectionGate多空方向控制（基于日/周MA200三状态模型）
        use_timing_gate: 启用TimingGate波浪+斐波那契时机软调控（三浪结构+fib回撤评分，默认false）
        use_atr: 启用ATR动态止盈（基于4H ATR百分比调整止盈和加仓间距）
        use_kelly: 启用凯利公式优化底仓比例（基于历史回测数据计算最优仓位）
        kelly_base_pct: 凯利优化的基线底仓比例（默认22%，凯利结果与之对比取保守者）
        use_trailing_tp: 启用ATR移动止盈（浮盈达标后从最高点回撤N×ATR止盈）
        trailing_atr_mult: 移动止盈的ATR倍数（默认1.5）
        trailing_start_pct_of_tp: 启动移动止盈的浮盈阈值=止盈比例×此系数（默认0.5即50%）
        use_btc_windvane: 启用BTC风向标模式（移除各币种MA200止损，用BTC MA200状态全局控方向）
        btc_windvane_confirm_days: BTC风向标跌破确认天数（默认3日，大市值币可用1日提高灵敏度）
        btc_windvane_short_only: SHORT_ALLOWED状态下是否只允许做空（默认false=多空都允许）
        use_elder_ray: 启用Elder-ray日线强度资金调度（不利势能减弱/反弹强度高时资金更大）
    """
    is_btc = coin.upper() == "BTC"

    # ── 智能模式：根据币种自动选择最优止损/方向控制策略 ──
    # 回测结论(2026-07-16):
    #   BTC: 自身MA200止损 + DirectionGate 更优（风向标模式收益-7.32%）
    #   其他币: BTC风向标3日确认 + SHORT_ALLOWED只做空 更优
    #     - SHORT_ALLOWED时只做空比多空都允许收益高4-7%，回撤大幅降低
    if not use_btc_windvane and not use_direction_gate:
        if is_btc:
            use_direction_gate = True
        else:
            use_btc_windvane = True
            btc_windvane_confirm_days = 3
            btc_windvane_short_only = True

    # ── 凯利公式底仓优化 ──
    # 当 use_kelly=True 时，先用基线比例跑一遍获取交易样本，
    # 再从样本计算凯利参数，用优化后的比例作为实际底仓比例
    kelly_params = None
    effective_base_pct = base_position_pct
    if use_kelly:
        try:
            kelly_path = str(Path(__file__).parent.parent / "lib")
            if kelly_path not in sys.path:
                sys.path.insert(0, kelly_path)
            from kelly_optimizer import calculate_kelly_from_trades

            # 先用基线比例跑一次预回测获取交易样本
            _pre_result = run_backtest(
                coin=coin,
                klines=klines,
                initial_capital=initial_capital,
                base_position_pct=kelly_base_pct,
                max_addons=max_addons,
                confidence_threshold=confidence_threshold,
                long_only=long_only,
                position_tf=position_tf,
                custom_addon_pct=custom_addon_pct,
                custom_tp_pct=custom_tp_pct,
                trend_filter_mode=trend_filter_mode,
                trend_filter_period=trend_filter_period,
                max_base_holding_hours=max_base_holding_hours,
                max_post_addon_hours=max_post_addon_hours,
                golden_window_hours=golden_window_hours,
                bounce_filter=bounce_filter,
                use_direction_gate=use_direction_gate,
                use_atr=use_atr,
                use_kelly=False,
            )
            _pre_trades = _pre_result.get("trades", [])
            kelly_params = calculate_kelly_from_trades(_pre_trades, base_pct=kelly_base_pct)
            effective_base_pct = kelly_params.final_pct
        except Exception as e:
            print(f"凯利优化失败[{coin}]: {e}，回退基线{kelly_base_pct}")
            effective_base_pct = kelly_base_pct

    # 获取数据
    if klines is None:
        klines = fetch_klines(coin, "4h", 1500)

    if len(klines) < 200:
        return {
            "error": f"4H K线数据不足({len(klines)}根)，至少需要200根",
            "trades": [],
            "metrics": {},
        }

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
        last_daily_close_list, last_weekly_close_list = prepare_last_close_for_4h(
            klines, klines_1d, klines_1w
        )

    # 预计算EMA200（仅use_ema200=True时计算，用于MA200+EMA200止损对比回测）
    daily_ema200_list, weekly_ema200_list = None, None
    if use_ema200 and len(klines_1d) >= 200:
        daily_ema200_list, weekly_ema200_list = prepare_ema200_for_4h(klines, klines_1d, klines_1w)

    # 预计算MA128（用于DirectionGate多空方向控制）
    daily_ma128_list = None
    if len(klines_1d) >= 128:
        daily_ma128_list = prepare_ma128_for_4h(klines, klines_1d)

    # 预计算BTC的MA128和收盘价（用于BTC风向标）
    btc_daily_ma128_list = None
    btc_recent_closes_list = None
    if use_direction_gate and _DIRECTION_GATE_AVAILABLE:
        btc_klines_1d_gate = fetch_klines("BTC", "1d", 400)
        if len(btc_klines_1d_gate) >= 128:
            btc_daily_ma128_list = prepare_ma128_for_4h(klines, btc_klines_1d_gate)
            btc_recent_closes_list = []
            btc_daily_close_dict = {}
            for k in btc_klines_1d_gate:
                date_str = _timestamp_to_date_str(k["t"])
                btc_daily_close_dict[date_str] = float(k["c"])
            for k in klines:
                date_str = _timestamp_to_date_str(k["t"])
                btc_recent_closes_list.append(btc_daily_close_dict.get(date_str))

    # Phase A: DirectionGate 路径预计算 confirmed BTC short_enabled（连续3日确认 + sticky）
    # 注意: 此处仅声明 None，实际预计算在 closes 定义之后执行
    confirmed_btc_short_enabled = None

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

    # 预计算ATR百分比序列（4H K线，14周期）
    coin_atr_pct_list = prepare_atr_pct_for_4h(klines, period=14)
    btc_klines_4h = fetch_klines("BTC", "4h", 1500)
    btc_atr_pct_list = prepare_atr_pct_for_4h(btc_klines_4h, period=14) if btc_klines_4h else []

    # 预计算Elder-ray日线强度（用于资金调度）
    elder_ray_list = None
    if use_elder_ray and _ELDER_RAY_AVAILABLE and len(klines_1d) >= 18:
        elder_ray_list = prepare_elder_ray_for_4h(klines, klines_1d)

    # 基础波动率调整（不含ATR，作为回退基准）
    effective_tp_pct_base, effective_addon_pct_base, _ = get_vol_adjusted_params(
        BASE_TP_PCT, BASE_ADDON_PCT, coin_vol, btc_vol
    )
    effective_tp_pct = effective_tp_pct_base
    effective_addon_pct = effective_addon_pct_base

    # 使用自定义参数覆盖（用于贝叶斯优化）
    if custom_tp_pct is not None:
        effective_tp_pct = custom_tp_pct
    if custom_addon_pct is not None:
        effective_addon_pct = custom_addon_pct

    closes = [float(k["c"]) for k in klines]
    highs = [float(k["h"]) for k in klines]
    lows = [float(k["l"]) for k in klines]

    # BTC风向标模式：预计算BTC日MA200和周MA200序列，并生成状态序列
    btc_windvane_states = None
    if use_btc_windvane:
        btc_klines_1d_wv = fetch_klines("BTC", "1d", 400)
        btc_klines_1w_wv = fetch_klines("BTC", "1w", 300)
        btc_daily_ma200_wv, btc_weekly_ma200_wv = prepare_ma200_for_4h(
            klines, btc_klines_1d_wv, btc_klines_1w_wv
        )
        # BTC每日收盘价序列（映射到4H）
        btc_daily_close_wv = [None] * len(klines)
        if btc_klines_1d_wv:
            btc_daily_close_dict = {}
            for k in btc_klines_1d_wv:
                date_str = _timestamp_to_date_str(k["t"])
                btc_daily_close_dict[date_str] = float(k["c"])
            for i, k in enumerate(klines):
                date_str = _timestamp_to_date_str(k["t"])
                btc_daily_close_wv[i] = btc_daily_close_dict.get(date_str)
        # 生成BTC状态序列
        btc_windvane_states = []
        btc_recent_closes = []
        last_date = None
        for i in range(len(closes)):
            state = "LONG_ONLY"
            btc_d200 = btc_daily_ma200_wv[i] if i < len(btc_daily_ma200_wv) else None
            btc_w200 = btc_weekly_ma200_wv[i] if i < len(btc_weekly_ma200_wv) else None
            btc_close = btc_daily_close_wv[i] if i < len(btc_daily_close_wv) else None

            if btc_close is not None:
                date_str = _timestamp_to_date_str(klines[i].get("t", 0))
                if date_str != last_date:
                    btc_recent_closes.append(btc_close)
                    if len(btc_recent_closes) > 5:
                        btc_recent_closes.pop(0)
                    last_date = date_str

            if btc_d200 is not None and btc_w200 is not None and btc_close is not None:
                if btc_close <= btc_w200:
                    state = "LONG_ONLY_FORCE"
                elif len(btc_recent_closes) >= btc_windvane_confirm_days and all(
                    c <= btc_d200 for c in btc_recent_closes[-btc_windvane_confirm_days:]
                ):
                    state = "SHORT_ALLOWED"
                else:
                    state = "LONG_ONLY"
            btc_windvane_states.append(state)

        # Phase A: 连续3日收盘确认 + sticky 防震荡
        if btc_windvane_states:
            from regime_manager import compute_confirmed_regimes_by_date
            bar_dates_wv = [_timestamp_to_date_str(k.get("t", 0)) for k in klines]
            btc_windvane_states = compute_confirmed_regimes_by_date(
                btc_windvane_states, bar_dates_wv,
                confirm_days=btc_windvane_confirm_days,
            )

    # Phase A: DirectionGate 路径预计算 confirmed BTC short_enabled（连续3日确认 + sticky）
    if use_direction_gate and _DIRECTION_GATE_AVAILABLE and btc_daily_ma128_list is not None:
        from regime_manager import compute_confirmed_regimes_by_date
        raw_btc_states = []
        for idx in range(len(closes)):
            btc_ma128 = btc_daily_ma128_list[idx] if idx < len(btc_daily_ma128_list) else None
            if btc_ma128 is not None:
                btc_recent = []
                for j in range(max(0, idx - 5), idx + 1):
                    if j < len(btc_recent_closes_list) and btc_recent_closes_list[j] is not None:
                        btc_recent.append(btc_recent_closes_list[j])
                if len(btc_recent) >= 3:
                    raw_btc_states.append("SHORT_ALLOWED" if all(c <= btc_ma128 for c in btc_recent[-3:]) else "LONG_ONLY")
                else:
                    raw_btc_states.append("LONG_ONLY")
            else:
                raw_btc_states.append("LONG_ONLY")
        bar_dates_gate = [_timestamp_to_date_str(k.get("t", 0)) for k in klines]
        confirmed_states = compute_confirmed_regimes_by_date(
            raw_btc_states, bar_dates_gate, confirm_days=3,
        )
        confirmed_btc_short_enabled = [s == "SHORT_ALLOWED" for s in confirmed_states]

    # Phase A+: 形态切换冷却期 — 切换后 N 根 bar 内不开新仓
    regime_cooldown_flags = None
    if regime_cooldown_bars > 0:
        regime_cooldown_flags = [False] * len(closes)
        # windvane 路径：从 btc_windvane_states 变化点计算
        if use_btc_windvane and btc_windvane_states:
            for idx in range(1, len(btc_windvane_states)):
                if btc_windvane_states[idx] != btc_windvane_states[idx - 1]:
                    for j in range(idx, min(idx + regime_cooldown_bars, len(regime_cooldown_flags))):
                        regime_cooldown_flags[j] = True
        # direction_gate 路径：从 confirmed_btc_short_enabled 变化点计算
        elif use_direction_gate and confirmed_btc_short_enabled:
            for idx in range(1, len(confirmed_btc_short_enabled)):
                if confirmed_btc_short_enabled[idx] != confirmed_btc_short_enabled[idx - 1]:
                    for j in range(idx, min(idx + regime_cooldown_bars, len(regime_cooldown_flags))):
                        regime_cooldown_flags[j] = True

    # Phase B: 预计算 per-bar regime 标签（用于 per-regime 参数切换）
    # Phase B+: subregime_enabled 时也需要 bar_regimes 作为宏观态
    bar_regimes = None
    if regime_params or subregime_enabled:
        bar_regimes = ["BULL"] * len(closes)  # 默认 BULL
        # windvane 路径：用 confirmed btc_windvane_states
        if use_btc_windvane and btc_windvane_states:
            for idx in range(len(btc_windvane_states)):
                s = btc_windvane_states[idx]
                if s == "SHORT_ALLOWED":
                    bar_regimes[idx] = "BEAR"
                elif s == "LONG_ONLY_FORCE":
                    bar_regimes[idx] = "RANGE"
                else:
                    bar_regimes[idx] = "BULL"
        # direction_gate 路径：用 confirmed_btc_short_enabled
        elif use_direction_gate and confirmed_btc_short_enabled:
            for idx in range(len(confirmed_btc_short_enabled)):
                bar_regimes[idx] = "BEAR" if confirmed_btc_short_enabled[idx] else "BULL"

    # Phase B+: 预计算 per-bar 子形态（宏观二分 × Elder-ray 微观子形态）
    # 仅在 subregime_enabled 且有 elder_ray 数据时计算，用于 TP/holding 小幅微调
    bar_subregimes = None
    if subregime_enabled and elder_ray_list and bar_regimes:
        bar_subregimes = _compute_subregimes(elder_ray_list, bar_regimes, smooth_window=3)

    # Phase C: 预计算 per-bar 易经 risk/value（用于参数插值微调）
    # 仅在 yijing_enabled 时批量推理，step 采样加速
    bar_yiji = None
    _yiji_bridge = None
    if yijing_enabled:
        try:
            sys.path.insert(0, str(Path(__file__).parent.parent / "lib"))
            from yijing_bridge import YijingBridge
            _yiji_bridge = YijingBridge()
            if _yiji_bridge.available:
                bar_yiji = _yiji_bridge.infer_klines(klines, step=yijing_step)
        except Exception as e:
            print(f"  [Phase C] 易经桥接初始化失败，降级为禁用: {e}")
            bar_yiji = None

    capital = initial_capital
    position = None
    trades = []

    for i in range(200, len(closes)):
        price_window = closes[: i + 1]
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
                decision = v15_decision(
                    price_window, override_position=daily_position, override_smas=daily_smas
                )
            else:
                decision = v15_decision(price_window)

            action = decision.get("action", "WAIT")
            conf = decision.get("confidence", 0)
            vol_mult = decision.get("vol_mult", 1.0)

            if action in ("OPEN_BULL", "OPEN_BEAR") and conf >= confidence_threshold:
                # Phase A+: 形态切换冷却期内不开新仓
                if regime_cooldown_flags is not None and i < len(regime_cooldown_flags) and regime_cooldown_flags[i]:
                    continue
                # 只做多模式：忽略做空信号
                if long_only and action == "OPEN_BEAR":
                    continue

                # BTC风向标模式：根据BTC状态决定开仓方向
                if use_btc_windvane and btc_windvane_states is not None:
                    btc_state = (
                        btc_windvane_states[i] if i < len(btc_windvane_states) else "LONG_ONLY"
                    )
                    if btc_state == "LONG_ONLY" and action == "OPEN_BEAR":
                        continue  # BTC在MA200上方，只做多
                    if btc_state == "LONG_ONLY_FORCE" and action == "OPEN_BEAR":
                        continue  # BTC触及周MA200，强制做多
                    if (
                        btc_state == "SHORT_ALLOWED"
                        and btc_windvane_short_only
                        and action == "OPEN_BULL"
                    ):
                        continue  # SHORT_ALLOWED状态下只允许做空

                # DirectionGate多空方向控制：BTC风向标 + MA128有效跌破
                coin_gate_result = None   # Phase4 TimingGate: 缓存币种DirectionGate结果（多空共用）
                if action == "OPEN_BEAR" and use_direction_gate and _DIRECTION_GATE_AVAILABLE:
                    # Phase A: 使用预计算的 confirmed btc_short_enabled（连续3日确认 + sticky）
                    if confirmed_btc_short_enabled is not None:
                        btc_short_enabled = confirmed_btc_short_enabled[i] if i < len(confirmed_btc_short_enabled) else False
                    else:
                        # fallback: 原始逐 bar 计算
                        btc_short_enabled = False
                        if btc_daily_ma128_list is not None and btc_recent_closes_list is not None:
                            btc_ma128 = (
                                btc_daily_ma128_list[i] if i < len(btc_daily_ma128_list) else None
                            )
                            if btc_ma128 is not None:
                                btc_recent = []
                                for j in range(max(0, i - 5), i + 1):
                                    if (
                                        j < len(btc_recent_closes_list)
                                        and btc_recent_closes_list[j] is not None
                                    ):
                                        btc_recent.append(btc_recent_closes_list[j])
                                if len(btc_recent) >= 3:
                                    last_3 = btc_recent[-3:]
                                    btc_short_enabled = all(c <= btc_ma128 for c in last_3)

                    # 2. 当前币种的方向控制
                    gate = DirectionGate(allow_short=True)
                    d_ma128 = (
                        daily_ma128_list[i]
                        if daily_ma128_list and i < len(daily_ma128_list)
                        else None
                    )
                    w_ma200 = (
                        weekly_ma200_list[i]
                        if weekly_ma200_list and i < len(weekly_ma200_list)
                        else None
                    )

                    recent_closes = []
                    if last_daily_close_list:
                        for j in range(max(0, i - 5), i + 1):
                            if (
                                j < len(last_daily_close_list)
                                and last_daily_close_list[j] is not None
                            ):
                                recent_closes.append(last_daily_close_list[j])

                    gate_result = gate.evaluate(
                        current_price=current_price,
                        daily_ma128=d_ma128,
                        weekly_ma200=w_ma200,
                        recent_daily_closes=recent_closes,
                        btc_short_enabled=btc_short_enabled,
                    )
                    coin_gate_result = gate_result
                    if not gate_result.short_enabled:
                        continue  # DirectionGate不允许做空，跳过

                # Phase 4: TimingGate 波浪+斐波那契时机软调控（方向先验 × 三浪结构评分）
                timing_mult: float = 1.0   # 默认无软调控，完全由 DirectionGate/指标 决定
                # apply_to_btc=False → BTC 单独禁用 timing（大币结构不清，避免反效果；贝叶斯优化开启）
                _timing_active = (
                    use_timing_gate and _TIMING_GATE_AVAILABLE
                    and (not is_btc or timing_gate_apply_to_btc)
                )
                if _timing_active:
                    # 1. 若此前未计算币种 DirectionGate，则补一次（TimingGate 需要 gate_result 作为方向先验）
                    if coin_gate_result is None and _DIRECTION_GATE_AVAILABLE:
                        try:
                            _d128 = daily_ma128_list[i] if daily_ma128_list and i < len(daily_ma128_list) else None
                            _w200 = weekly_ma200_list[i] if weekly_ma200_list and i < len(weekly_ma200_list) else None
                            _rc5: list = []
                            if last_daily_close_list:
                                for j in range(max(0, i - 5), i + 1):
                                    if j < len(last_daily_close_list) and last_daily_close_list[j] is not None:
                                        _rc5.append(last_daily_close_list[j])
                            # btc_short_enabled fallback: 没有 confirmed 就按 long_only（保守）
                            _btc_se = False
                            if confirmed_btc_short_enabled is not None and i < len(confirmed_btc_short_enabled):
                                _btc_se = confirmed_btc_short_enabled[i]
                            _g = DirectionGate(allow_short=True)
                            coin_gate_result = _g.evaluate(
                                current_price=current_price,
                                daily_ma128=_d128,
                                weekly_ma200=_w200,
                                recent_daily_closes=_rc5,
                                btc_short_enabled=_btc_se,
                            )
                        except Exception:
                            coin_gate_result = None
                    # 2. 准备 TimingGate 的长周期日线序列（最近 100 条每日收盘价）
                    timing_rcs: list = []
                    if last_daily_close_list:
                        for j in range(max(0, i - 99), i + 1):
                            if j < len(last_daily_close_list) and last_daily_close_list[j] is not None:
                                timing_rcs.append(last_daily_close_list[j])
                    # 2b. 准备小时级（4h）收盘价序列（最近 120 根≈20天，用于双周期 swing 融合）
                    timing_intraday: list = []
                    if timing_gate_swing_fusion_mode != "daily_only":
                        for j in range(max(0, i - 119), i + 1):
                            timing_intraday.append(closes[j])
                    # 3. TimingGate 评估 (参数从 run_backtest 透传，便于贝叶斯优化)
                    if coin_gate_result is not None and len(timing_rcs) >= 20:
                        try:
                            tg = TimingGate(
                                swing_window=int(timing_gate_swing_window),
                                fib_retrace_lo=float(timing_gate_fib_retrace_lo),
                                fib_retrace_hi=float(timing_gate_fib_retrace_hi),
                                fib_ext_ratio=float(timing_gate_fib_ext_ratio),
                                threshold=float(timing_gate_threshold),
                                lenient_unclear=float(timing_gate_lenient_unclear),
                                strict_unclear_score=float(timing_gate_strict_unclear_score),
                                strict=bool(timing_gate_strict),
                                retrace_mu=float(timing_gate_retrace_mu),
                                retrace_sigma=float(timing_gate_retrace_sigma),
                                unclear_retrace_ext=float(timing_gate_unclear_retrace_ext),
                                swing_fusion_mode=str(timing_gate_swing_fusion_mode),
                                intraday_swing_window=int(timing_gate_intraday_swing_window),
                            )
                            _intraday_arg = timing_intraday if len(timing_intraday) >= 20 else None
                            t_res = tg.evaluate(
                                coin_gate_result, timing_rcs,
                                price_now=current_price,
                                intraday_closes=_intraday_arg,
                            )
                            is_bull_action = "BULL" in action
                            if timing_gate_soft_mode:
                                # 软调控模式：不做硬门禁 continue，靠 timing_mult 连续调控仓位
                                # timing_mult = timing_score ^ size_power（power>1 强化惩罚低分）
                                _raw = float(max(0.0, min(1.0, t_res.timing_score)))
                                timing_mult = _raw ** float(timing_size_power)
                                # 极低分仍跳过（避免微零仓位无意义开仓）
                                if timing_mult < 0.02:
                                    continue
                            else:
                                # 硬门禁模式（原逻辑）
                                if is_bull_action and not t_res.long_timing_ok:
                                    continue
                                if (not is_bull_action) and not t_res.short_timing_ok:
                                    continue
                                timing_mult = float(max(0.0, min(1.0, t_res.timing_score)))
                        except Exception:
                            timing_mult = 1.0

                # 趋势过滤：下跌趋势中禁止做多马丁
                if "BULL" in action and trend_filter_mode != "none":
                    w_ma = trend_weekly_ma[i] if trend_weekly_ma and i < len(trend_weekly_ma) else 0
                    d_ma = trend_daily_ma[i] if trend_daily_ma and i < len(trend_daily_ma) else 0
                    if check_trend_filter(current_price, w_ma, d_ma, trend_filter_mode):
                        continue

                # 反弹过滤：只在触发反弹信号时开仓
                if bounce_filter is not None:
                    if i not in bounce_filter or not bounce_filter[i]:
                        continue

                direction = "LONG" if "BULL" in action else "SHORT"

                # Phase B: per-regime 参数覆盖（开仓时根据当前 regime 选择参数）
                cur_max_base_h = max_base_holding_hours
                cur_max_post_addon_h = max_post_addon_hours
                cur_golden_window_h = golden_window_hours
                cur_trailing_atr_mult = trailing_atr_mult
                cur_trailing_start = trailing_start_pct_of_tp
                if regime_params and bar_regimes and i < len(bar_regimes):
                    rp = regime_params.get(bar_regimes[i], {})
                    cur_max_base_h = rp.get('max_base_holding_hours', max_base_holding_hours)
                    cur_max_post_addon_h = rp.get('max_post_addon_hours', max_post_addon_hours)
                    cur_golden_window_h = rp.get('golden_window_hours', golden_window_hours)
                    cur_trailing_atr_mult = rp.get('trailing_atr_mult', trailing_atr_mult)
                    cur_trailing_start = rp.get('trailing_start_ratio', trailing_start_pct_of_tp)

                # Phase B+: 子形态小幅微调（TP + 持仓时间），不覆盖整组参数
                _cur_tp_mult = 1.0
                _cur_subregime = None
                if bar_subregimes is not None and i < len(bar_subregimes):
                    _cur_subregime = bar_subregimes[i]
                    _sr = (subregime_mults or DEFAULT_SUBREGIME_MULTS).get(_cur_subregime, {})
                    _h_mult = _sr.get('holding_mult', 1.0)
                    _cur_tp_mult = _sr.get('tp_mult', 1.0)
                    cur_max_base_h *= _h_mult
                    cur_max_post_addon_h *= _h_mult
                    cur_golden_window_h *= _h_mult

                # ATR动态止盈：每根K线实时计算ATR因子
                coin_atr_i = coin_atr_pct_list[i] if i < len(coin_atr_pct_list) else None
                btc_atr_i = btc_atr_pct_list[i] if i < len(btc_atr_pct_list) else None
                atr_factor_i = 1.0
                if use_atr and coin_atr_i is not None and btc_atr_i is not None and btc_atr_i > 0:
                    atr_factor_i = max(0.7, min(1.5, coin_atr_i / btc_atr_i))
                tp_pct_dyn = effective_tp_pct_base * atr_factor_i
                addon_pct_dyn = effective_addon_pct_base * atr_factor_i

                # 自定义参数覆盖时不使用ATR动态调整
                if custom_tp_pct is not None:
                    tp_pct_dyn = custom_tp_pct
                if custom_addon_pct is not None:
                    addon_pct_dyn = custom_addon_pct

                addon_pct = addon_pct_dyn * vol_mult
                tp_pct = tp_pct_dyn * vol_mult
                # Phase B+: 子形态 TP 微调（自定义止盈时不覆盖）
                if _cur_tp_mult != 1.0 and custom_tp_pct is None:
                    tp_pct *= _cur_tp_mult

                # Phase C: 易经 risk/value 插值微调（在子形态基础上叠加）
                # 前向填充：当前bar无推理时用最近的推理结果（限制最多回看3根bar≈12h，避免过时推理）
                _cur_yiji = None
                if bar_yiji is not None and i < len(bar_yiji):
                    _cur_yiji = bar_yiji[i]
                    if _cur_yiji is None:
                        for j in range(i - 1, max(i - 4, -1), -1):
                            if j < len(bar_yiji) and bar_yiji[j] is not None:
                                _cur_yiji = bar_yiji[j]
                                break
                if _cur_yiji is not None:
                    try:
                        from yijing_param_interpolator import interpolate_params
                        _sr_mults = {"tp_mult": _cur_tp_mult, "holding_mult": 1.0, "size_mult": 1.0}
                        # holding_mult 已应用到 cur_max_base_h，这里传 1.0 避免重复
                        if _cur_subregime:
                            _sr = (subregime_mults or DEFAULT_SUBREGIME_MULTS).get(_cur_subregime, {})
                            _sr_mults["holding_mult"] = _sr.get('holding_mult', 1.0)
                        _yiji_mults = interpolate_params(
                            _cur_yiji["risk_score"], _cur_yiji["value_score"],
                            subregime_mults=_sr_mults,
                        )
                        # 应用最终倍数（覆盖子形态的 tp_mult）
                        _cur_tp_mult = _yiji_mults["tp_mult"]
                        if custom_tp_pct is None:
                            tp_pct = tp_pct_dyn * vol_mult * _cur_tp_mult
                        # holding_mult 叠加（yiji 额外部分）
                        _yiji_h_extra = _yiji_mults["holding_mult"] / _sr_mults.get("holding_mult", 1.0)
                        if _yiji_h_extra != 1.0:
                            cur_max_base_h *= _yiji_h_extra
                            cur_max_post_addon_h *= _yiji_h_extra
                            cur_golden_window_h *= _yiji_h_extra
                    except Exception:
                        pass

                if direction == "LONG":
                    tp_price = current_price * (1 + tp_pct)
                    addon_prices = [
                        current_price * (1 - addon_pct * j) for j in range(1, max_addons + 1)
                    ]
                else:
                    tp_price = current_price * (1 - tp_pct)
                    addon_prices = [
                        current_price * (1 + addon_pct * j) for j in range(1, max_addons + 1)
                    ]

                # Elder-ray 资金调度：根据日线趋势强度调整仓位大小
                # 不利势能减弱/反弹强度高 → 资金更大；趋势强劲不利 → 资金更小
                elder_size_mult = 1.0
                if (
                    elder_ray_list is not None
                    and i < len(elder_ray_list)
                    and elder_ray_list[i] is not None
                ):
                    elder_size_mult = calc_elder_ray_size_mult(elder_ray_list[i], direction)

                position_size = capital * effective_base_pct * elder_size_mult * timing_mult / current_price
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
                    "tp_pct": tp_pct,
                    "addon_prices": addon_prices,
                    "vol_mult": vol_mult,
                    "confidence": conf,
                    "elder_mult": elder_size_mult,
                    "timing_mult": timing_mult,   # Phase4: 波浪+fib时机软调控（入场时确定，整仓保持）
                    "entry_reason": decision.get("position", ""),
                    "long_only": long_only,
                    "trailing_active": False,
                    "trailing_price": None,
                    "peak_price": current_price,
                    "max_base_h": cur_max_base_h,
                    "max_post_addon_h": cur_max_post_addon_h,
                    "golden_window_h": cur_golden_window_h,
                    "trailing_atr_mult": cur_trailing_atr_mult,
                    "trailing_start_ratio": cur_trailing_start,
                    "subregime": _cur_subregime,
                    "tp_mult": _cur_tp_mult,
                    "yiji_risk": _cur_yiji["risk_score"] if _cur_yiji else None,
                    "yiji_value": _cur_yiji["value_score"] if _cur_yiji else None,
                    "yiji_hexagram": _cur_yiji["hexagram"] if _cur_yiji else None,
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

            # BTC风向标模式：状态切换时平仓反向仓位（替代原MA200止损）
            if not hit_tp and not hit_sl and use_btc_windvane and btc_windvane_states is not None:
                btc_state = btc_windvane_states[i] if i < len(btc_windvane_states) else "LONG_ONLY"

                if btc_state == "LONG_ONLY" and direction == "SHORT":
                    # BTC回到日MA200上方 → 平掉空仓
                    hit_sl = True
                    position["sl_type"] = "btc_windvane_long_only"
                    exit_price = current_price
                elif btc_state == "LONG_ONLY_FORCE" and direction == "SHORT":
                    # BTC触及周MA200 → 强制平空转多
                    hit_sl = True
                    position["sl_type"] = "btc_windvane_force_long"
                    exit_price = current_price
                elif btc_state == "SHORT_ALLOWED" and direction == "LONG":
                    # BTC有效跌破日MA200 → 平掉多仓，允许做空
                    hit_sl = True
                    position["sl_type"] = "btc_windvane_short_allowed"
                    exit_price = current_price

            # MA200动态止损（所有币种都使用，BTC风向标模式下跳过）
            if not hit_tp and not hit_sl and daily_ma200_list is not None and not use_btc_windvane:
                daily_ma200 = daily_ma200_list[i]
                weekly_ma200 = weekly_ma200_list[i] if weekly_ma200_list else None
                last_d_close = last_daily_close_list[i] if last_daily_close_list else None
                last_w_close = last_weekly_close_list[i] if last_weekly_close_list else None

                if daily_ma200 is not None or weekly_ma200 is not None:
                    if use_ema200 and daily_ema200_list is not None:
                        daily_ema200 = daily_ema200_list[i]
                        weekly_ema200 = weekly_ema200_list[i] if weekly_ema200_list else None
                        stop_line, triggered, sl_type = get_ma200_ema200_stop_loss(
                            direction,
                            current_price,
                            daily_ma200,
                            weekly_ma200,
                            daily_ema200,
                            weekly_ema200,
                            last_d_close,
                            last_w_close,
                        )
                    else:
                        stop_line, triggered, sl_type = get_ma200_stop_loss(
                            direction,
                            current_price,
                            daily_ma200,
                            weekly_ma200,
                            last_d_close,
                            last_w_close,
                        )
                    if triggered:
                        hit_sl = True
                        position["sl_type"] = sl_type
                        if stop_line is not None:
                            exit_price = stop_line
                        else:
                            exit_price = current_price

            # ATR移动止盈（浮盈达标后从最高点回撤N×ATR止盈）
            if not hit_tp and not hit_sl and use_trailing_tp:
                coin_atr_i = coin_atr_pct_list[i] if i < len(coin_atr_pct_list) else None

                if coin_atr_i is not None and coin_atr_i > 0:
                    # 转换ATR百分比为价格
                    atr_price = current_price * (coin_atr_i / 100)

                    # 更新峰值价格
                    if direction == "LONG":
                        peak = max(position["peak_price"], high)
                    else:
                        peak = min(position["peak_price"], low)
                    position["peak_price"] = peak

                    # 计算浮盈比例
                    avg_entry = position["avg_entry"]
                    if direction == "LONG":
                        unrealized_pnl_pct = (peak - avg_entry) / avg_entry
                    else:
                        unrealized_pnl_pct = (avg_entry - peak) / avg_entry

                    # 启动阈值：浮盈达到止盈比例的一定比例
                    tp_pct_pos = position.get("tp_pct", 0.04)
                    pos_trailing_start = position.get("trailing_start_ratio", trailing_start_pct_of_tp)
                    start_threshold = tp_pct_pos * pos_trailing_start

                    if unrealized_pnl_pct >= start_threshold:
                        pos_trailing_atr_mult = position.get("trailing_atr_mult", trailing_atr_mult)
                        if direction == "LONG":
                            new_trailing = peak - pos_trailing_atr_mult * atr_price
                            # 移动止盈价只上移不下移
                            if (
                                position["trailing_price"] is None
                                or new_trailing > position["trailing_price"]
                            ):
                                position["trailing_price"] = new_trailing
                                position["trailing_active"] = True
                        else:
                            new_trailing = peak + pos_trailing_atr_mult * atr_price
                            # 移动止盈价只下移不上移
                            if (
                                position["trailing_price"] is None
                                or new_trailing < position["trailing_price"]
                            ):
                                position["trailing_price"] = new_trailing
                                position["trailing_active"] = True

                    # 检查是否触发移动止盈
                    if position["trailing_active"] and position["trailing_price"] is not None:
                        if direction == "LONG" and low <= position["trailing_price"]:
                            hit_tp = True
                            exit_price = position["trailing_price"]
                            position["sl_type"] = "trailing_tp"
                        elif direction == "SHORT" and high >= position["trailing_price"]:
                            hit_tp = True
                            exit_price = position["trailing_price"]
                            position["sl_type"] = "trailing_tp"

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
                        # 加仓时也根据当前Elder-ray状态调整资金规模
                        addon_elder_mult = 1.0
                        if (
                            elder_ray_list is not None
                            and i < len(elder_ray_list)
                            and elder_ray_list[i] is not None
                        ):
                            addon_elder_mult = calc_elder_ray_size_mult(
                                elder_ray_list[i], direction
                            )
                        # 加仓：继承入场时的 timing_mult（整仓时机尺度一致）
                        add_timing_mult = position.get("timing_mult", 1.0)
                        addon_size = (
                            capital * effective_base_pct * addon_elder_mult * add_timing_mult / addon_exec_price
                        )
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
                    pos_golden = position.get("golden_window_h", golden_window_hours)
                    pos_max_post = position.get("max_post_addon_h", max_post_addon_hours)
                    if hold_hours >= pos_golden and hold_hours >= pos_max_post:
                        time_exit_action = "evaluate"
                else:
                    # 无加仓：从开仓计时
                    bars_held = i - position["entry_idx"]
                    hold_hours = bars_held * HOURS_PER_BAR
                    pos_max_base = position.get("max_base_h", max_base_holding_hours)
                    if hold_hours >= pos_max_base:
                        time_exit_action = "evaluate"

                if time_exit_action == "evaluate":
                    try:
                        classic_path = str(Path(__file__).parent.parent.parent / "10-经典指标系统")
                        if classic_path not in sys.path:
                            sys.path.insert(0, classic_path)
                        from classic_exit_system import ClassicExitSystem, ExitConfig
                        from classic_exit_system import PositionState as ExitPosState

                        if not hasattr(run_backtest, "_exit_system"):
                            exit_cfg = ExitConfig()
                            exit_cfg.l0_max_hold_sec = (
                                999999  # 禁用L0持仓时间硬退出（马丁策略有自己的超时逻辑）
                            )
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
                        candles_for_exit = klines[: i + 1]
                        decision = system.evaluate_full(
                            pos_state, candles_1h=candles_for_exit, regime="trend"
                        )
                        action_val = (
                            decision.action.value
                            if hasattr(decision.action, "value")
                            else str(decision.action)
                        )

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
                            position["total_size"] *= 1 - reduce_frac
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
                    "exit_reason": (
                        "take_profit"
                        if hit_tp
                        else (
                            "time_exit"
                            if position.get("sl_type", "").startswith("time_exit")
                            else "ma200_stop"
                        )
                    ),
                    "sl_type": position.get("sl_type", ""),
                    "bars_held": i - position["entry_idx"],
                    "levels_used": position["current_level"] + 1,
                    "confidence": position["confidence"],
                    "vol_mult": position["vol_mult"],
                    "elder_mult": position.get("elder_mult", 1.0),
                    "entry_reason": position["entry_reason"],
                    "long_only": position.get("long_only", False),
                    "subregime": position.get("subregime"),
                    "tp_mult": position.get("tp_mult", 1.0),
                    "yiji_risk": position.get("yiji_risk"),
                    "yiji_value": position.get("yiji_value"),
                    "yiji_hexagram": position.get("yiji_hexagram"),
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
            std_return = variance**0.5
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
        trailing_tp_trades = sum(
            1
            for t in trades
            if t.get("exit_reason") == "take_profit" and t.get("sl_type") == "trailing_tp"
        )
        fixed_tp_trades = sum(
            1
            for t in trades
            if t.get("exit_reason") == "take_profit" and t.get("sl_type") != "trailing_tp"
        )
        btc_windvane_exits = sum(
            1 for t in trades if str(t.get("sl_type", "")).startswith("btc_windvane")
        )

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
            "trailing_tp_trades": trailing_tp_trades,
            "fixed_tp_trades": fixed_tp_trades,
            "coin_volatility": round(coin_vol * 100, 2),
            "btc_volatility": round(btc_vol * 100, 2),
            "vol_ratio": round(coin_vol / btc_vol, 2) if btc_vol > 0 else 1.0,
            "effective_tp_pct": round(effective_tp_pct_base * 100, 2),
            "effective_addon_pct": round(effective_addon_pct_base * 100, 2),
            "atr_enabled": use_atr,
            "kelly_enabled": use_kelly,
            "trailing_tp_enabled": use_trailing_tp,
            "btc_windvane_enabled": use_btc_windvane,
            "btc_windvane_exits": btc_windvane_exits,
            "elder_ray_enabled": use_elder_ray,
            "elder_ray_avg_mult": (
                round(sum(t.get("elder_mult", 1.0) for t in trades) / len(trades), 3)
                if trades
                else 1.0
            ),
            "effective_base_pct": round(effective_base_pct, 4),
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
            "trailing_tp_trades": 0,
            "fixed_tp_trades": 0,
            "btc_windvane_exits": 0,
            "coin_volatility": round(coin_vol * 100, 2),
            "btc_volatility": round(btc_vol * 100, 2),
            "vol_ratio": 1.0,
            "effective_tp_pct": round(effective_tp_pct_base * 100, 2),
            "effective_addon_pct": round(effective_addon_pct_base * 100, 2),
            "atr_enabled": use_atr,
            "kelly_enabled": use_kelly,
            "trailing_tp_enabled": use_trailing_tp,
            "btc_windvane_enabled": use_btc_windvane,
            "effective_base_pct": round(effective_base_pct, 4),
        }

    return {
        "coin": coin,
        "initial_capital": initial_capital,
        "base_position_pct": base_position_pct,
        "effective_base_pct": round(effective_base_pct, 4),
        "max_addons": max_addons,
        "confidence_threshold": confidence_threshold,
        "klines_count": len(closes),
        "long_only": long_only,
        "position_tf": position_tf,
        "trades": trades,
        "metrics": metrics,
        "kelly_params": kelly_params.__dict__ if kelly_params else None,
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
    print("  止损模式: MA200动态止损 (日线+周线)")
    print(
        f"  位置判定: {'日线均线(SMA30/60/120/200)' if result.get('position_tf') == '1d' else '4H均线(SMA30/65/128/200)'}"
    )
    print(f"  交易方向: {'只做多' if result.get('long_only') else '多空双向'}")
    if m.get("effective_tp_pct") != 4.0:
        print(
            f"  波动调整: 止盈{m['effective_tp_pct']:.1f}% / 加仓间距{m['effective_addon_pct']:.1f}% (比率{m['vol_ratio']:.2f}x)"
        )
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
        print(
            f"  {'#':>3} {'方向':>6} {'入场价':>10} {'均价':>10} {'出场价':>10} "
            f"{'收益率':>8} {'层级':>4} {'原因':>12} {'持仓':>5} {'出场':>8}"
        )
        print("-" * 70)
        for idx, t in enumerate(result["trades"][-10:]):
            exit_reason = "止盈" if t.get("exit_reason") == "take_profit" else "MA200"
            print(
                f"  {idx + 1:>3} {t['side']:>6} {t['entry_price']:>10.2f} {t['avg_entry']:>10.2f} "
                f"{t['exit_price']:>10.2f} {t['pnl_pct']:>+7.2f}% {t['levels_used']:>4} "
                f"{t['entry_reason']:>12} {t['bars_held']:>4} {exit_reason:>8}"
            )
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
    parser.add_argument(
        "--direction-gate",
        action="store_true",
        help="启用DirectionGate多空方向控制（基于日/周MA200）",
    )
    parser.add_argument(
        "--timing-gate",
        action="store_true",
        help="Phase4: 启用TimingGate波浪+斐波那契时机软调控（三浪+fib回撤评分）",
    )
    parser.add_argument(
        "--compare",
        action="store_true",
        help="对比三模式: 只做多 vs 无限制做空 vs DirectionGate控制做空",
    )
    parser.add_argument(
        "--compare-position", action="store_true", help="对比4H均线 vs 日线均线位置判定"
    )
    parser.add_argument(
        "--position-tf", default="4h", choices=["4h", "1d"], help="位置判定时间框架 (默认: 4h)"
    )
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
        print(
            f"  {'模式':>12} {'总收益':>10} {'交易数':>6} {'胜率':>8} {'盈亏比':>8} "
            f"{'最大回撤':>10} {'夏普':>8} {'连盈':>5} {'连亏':>5}"
        )
        print("-" * 80)
        for tf, r in all_results:
            if "error" not in r:
                m = r["metrics"]
                tf_str = "4H均线" if tf == "4h" else "日线均线"
                print(
                    f"  {tf_str:>12} {m['total_return_pct']:>+8.2f}% {m['total_trades']:>6} "
                    f"{m['win_rate']*100:>7.2f}% {m['profit_factor']:>8.2f} "
                    f"{m['max_drawdown_pct']:>9.2f}% {m['sharpe_ratio']:>8.4f} "
                    f"{m['max_consecutive_wins']:>5} {m['max_consecutive_losses']:>5}"
                )
        print("=" * 80)

    elif args.compare:
        coins = ["BTC", "ETH", "SOL", "ARB", "OP"]
        print("🚀 多币种V15策略回测 - 三模式对比: 只做多 vs 无限制做空 vs DirectionGate控制做空")
        all_results = []
        for coin in coins:
            print(f"\n{'='*60}")
            print(f"  回测 {coin}...")
            klines = fetch_klines(coin, "4h", args.limit)

            print("\n  --- 只做多 ---")
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
            all_results.append(("long_only", result_long))

            print("\n  --- 无限制做空 ---")
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

            print("\n  --- DirectionGate控制做空 ---")
            result_gate = run_backtest(
                coin=coin,
                klines=klines,
                initial_capital=args.capital,
                base_position_pct=args.position,
                max_addons=args.addons,
                confidence_threshold=args.threshold,
                long_only=False,
                use_direction_gate=True,
            )
            print_report(result_gate)
            all_results.append(("gate", result_gate))

        print("\n" + "=" * 90)
        print("  📊 三模式对比汇总: 只做多 vs 无限制做空 vs DirectionGate控制做空")
        print("=" * 90)
        print(
            f"  {'币种':>6} {'模式':>16} {'总收益':>10} {'交易数':>6} {'胜率':>8} {'盈亏比':>8} "
            f"{'最大回撤':>10} {'夏普':>8} {'做空数':>6}"
        )
        print("-" * 90)
        for mode, r in all_results:
            if "error" not in r:
                m = r["metrics"]
                short_trades = sum(1 for t in r.get("trades", []) if t.get("side") == "SHORT")
                mode_str = {"long_only": "只做多", "both": "无限制做空", "gate": "Gate控制做空"}[
                    mode
                ]
                print(
                    f"  {r['coin']:>6} {mode_str:>16} {m['total_return_pct']:>+8.2f}% {m['total_trades']:>6} "
                    f"{m['win_rate']*100:>7.2f}% {m['profit_factor']:>8.2f} "
                    f"{m['max_drawdown_pct']:>9.2f}% {m['sharpe_ratio']:>8.4f} {short_trades:>6}"
                )
        print("=" * 90)

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
        print(
            f"  {'币种':>6} {'总收益':>10} {'交易数':>6} {'胜率':>8} {'盈亏比':>8} "
            f"{'最大回撤':>10} {'夏普':>8} {'波动率':>8}"
        )
        print("-" * 70)
        total_return = 0
        total_trades = 0
        for r in all_results:
            if "error" not in r:
                m = r["metrics"]
                total_return += m["total_return_pct"]
                total_trades += m["total_trades"]
                vol_str = f"{m['vol_ratio']:.2f}x" if m.get("vol_ratio") else "1.00x"
                print(
                    f"  {r['coin']:>6} {m['total_return_pct']:>+8.2f}% {m['total_trades']:>6} "
                    f"{m['win_rate']*100:>7.2f}% {m['profit_factor']:>8.2f} "
                    f"{m['max_drawdown_pct']:>9.2f}% {m['sharpe_ratio']:>8.4f} {vol_str:>8}"
                )
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
            use_direction_gate=args.direction_gate,
            use_timing_gate=args.timing_gate,
        )
        print_report(result)


if __name__ == "__main__":
    main()
