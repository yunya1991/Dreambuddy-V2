#!/usr/bin/env python3
"""
回测历史数据获取模块
======================
使用 OKX 公开API 获取历史K线数据，无需认证

支持周期: 1W (周线) / 1D (日线) / 4H (四小时线) / 1H (小时线)
数据源:   OKX /api/v5/market/history-candles (最早可到2021年)
缓存:     保存到 data/backtest/ 目录，避免重复请求

用法:
    python3 backtest_data_fetcher.py --inst BTC-USDT-SWAP --bar 1D --from 2025-01-01 --to 2026-05-16
"""

import os
import csv
import time
import json
import requests
import argparse
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Dict, Optional

# ==================== 配置 ====================
BASE_URL    = "https://www.okx.com"
DATA_DIR    = Path(__file__).parent.parent / "data" / "backtest"
SLEEP_MS    = 200    # API请求间隔 (毫秒)，避免限流
PAGE_LIMIT  = 100    # 每页最多100根K线

BAR_MILLIS = {
    "1W":  7 * 24 * 3600 * 1000,
    "1D":  1 * 24 * 3600 * 1000,
    "4H":  4  *   3600 * 1000,
    "1H":  1  *   3600 * 1000,
    "15m": 15 *     60 * 1000,
}


# ==================== 核心函数 ====================

def _fetch_page(inst_id: str, bar: str, after: Optional[str] = None, before: Optional[str] = None) -> List[List]:
    """
    获取一页K线数据（最多100根）
    
    OKX history-candles 接口说明:
      after  = 请求此时间戳之前的数据 (更早的数据)
      before = 请求此时间戳之后的数据 (更新的数据)
      
    返回格式: [[ts, open, high, low, close, vol, volCcy, volCcyQuote, confirm], ...]
    其中 ts 单位为毫秒，数据按时间降序排列（最新在前）
    """
    params = {
        "instId": inst_id,
        "bar":    bar,
        "limit":  str(PAGE_LIMIT),
    }
    if after:
        params["after"] = str(after)
    if before:
        params["before"] = str(before)

    url = BASE_URL + "/api/v5/market/history-candles"
    try:
        resp = requests.get(url, params=params, timeout=10)
        data = resp.json()
    except Exception as e:
        print(f"  ⚠️ 请求异常: {e}")
        return []

    if data.get("code") != "0":
        print(f"  ⚠️ API错误 code={data.get('code')} msg={data.get('msg')}")
        return []

    return data.get("data", [])


def fetch_historical_candles(
    inst_id: str,
    bar: str,
    start_ts: int,
    end_ts: int,
    verbose: bool = True
) -> List[Dict]:
    """
    获取完整历史K线 (start_ts ~ end_ts)，自动分页
    
    Args:
        inst_id:  交易对，如 "BTC-USDT-SWAP"
        bar:      K线周期，如 "1D" "1W" "4H" "1H"
        start_ts: 开始时间戳（毫秒）
        end_ts:   结束时间戳（毫秒）
        verbose:  是否输出进度
        
    Returns:
        按时间升序排列的K线列表，每条格式:
        {
            "ts":    int   (毫秒时间戳),
            "open":  float,
            "high":  float,
            "low":   float,
            "close": float,
            "vol":   float  (合约张数),
            "volUsd":float  (USDT成交额)
        }
    """
    if verbose:
        start_dt = datetime.fromtimestamp(start_ts / 1000)
        end_dt   = datetime.fromtimestamp(end_ts   / 1000)
        print(f"📥 获取K线数据: {inst_id} | {bar} | {start_dt:%Y-%m-%d} ~ {end_dt:%Y-%m-%d}")

    all_candles: List[List] = []
    # OKX history-candles 使用 after 参数向前翻页
    # after = 当前最早K线的ts，会返回比它更早的K线
    # 策略：从 end_ts 往前翻，直到覆盖 start_ts
    current_after = str(end_ts + 1)  # +1 确保包含 end_ts 那根K线

    page_count = 0
    while True:
        page = _fetch_page(inst_id, bar, after=current_after)
        if not page:
            break

        page_count += 1
        # 过滤时间范围
        filtered = [c for c in page if start_ts <= int(c[0]) <= end_ts]
        all_candles.extend(filtered)

        # 最早的K线时间
        earliest_ts = int(page[-1][0])
        if verbose and page_count % 5 == 0:
            earliest_dt = datetime.fromtimestamp(earliest_ts / 1000)
            print(f"  📦 第{page_count}页 | 最早: {earliest_dt:%Y-%m-%d} | 累计 {len(all_candles)} 根")

        # 已经到达 start_ts 之前，停止
        if earliest_ts <= start_ts:
            break

        # 准备下一页
        current_after = str(earliest_ts)
        time.sleep(SLEEP_MS / 1000)

    if verbose:
        print(f"  ✅ 获取完成，共 {len(all_candles)} 根K线")

    # 去重 + 升序排列
    seen = set()
    unique = []
    for c in all_candles:
        if c[0] not in seen:
            seen.add(c[0])
            unique.append(c)

    unique.sort(key=lambda x: int(x[0]))

    # 格式化为 dict
    result = []
    for c in unique:
        result.append({
            "ts":    int(c[0]),
            "open":  float(c[1]),
            "high":  float(c[2]),
            "low":   float(c[3]),
            "close": float(c[4]),
            "vol":   float(c[5]),
            "volUsd": float(c[7]) if len(c) > 7 else 0.0,
        })

    return result


# ==================== 缓存 ====================

def _cache_path(inst_id: str, bar: str, start_ts: int, end_ts: int) -> Path:
    inst_safe = inst_id.replace("-", "_")
    start_d = datetime.fromtimestamp(start_ts / 1000).strftime("%Y%m%d")
    end_d   = datetime.fromtimestamp(end_ts   / 1000).strftime("%Y%m%d")
    filename = f"{inst_safe}_{bar}_{start_d}_{end_d}.csv"
    return DATA_DIR / filename


def load_or_fetch(
    inst_id: str,
    bar: str,
    start_ts: int,
    end_ts: int,
    force_refresh: bool = False
) -> List[Dict]:
    """
    优先从缓存加载，缓存不存在时获取并保存
    """
    cache_file = _cache_path(inst_id, bar, start_ts, end_ts)
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    if cache_file.exists() and not force_refresh:
        print(f"  📂 从缓存加载: {cache_file.name}")
        return _load_csv(cache_file)

    candles = fetch_historical_candles(inst_id, bar, start_ts, end_ts)
    if candles:
        _save_csv(candles, cache_file)
        print(f"  💾 数据已缓存: {cache_file.name}")
    return candles


def _save_csv(candles: List[Dict], path: Path):
    with open(path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["ts", "open", "high", "low", "close", "vol", "volUsd"])
        writer.writeheader()
        writer.writerows(candles)


def _load_csv(path: Path) -> List[Dict]:
    result = []
    with open(path, "r") as f:
        reader = csv.DictReader(f)
        for row in reader:
            result.append({
                "ts":    int(row["ts"]),
                "open":  float(row["open"]),
                "high":  float(row["high"]),
                "low":   float(row["low"]),
                "close": float(row["close"]),
                "vol":   float(row["vol"]),
                "volUsd": float(row["volUsd"]),
            })
    return result


# ==================== 工具函数 ====================

def dt_to_ts(date_str: str) -> int:
    """日期字符串转毫秒时间戳，如 '2025-01-01'"""
    dt = datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    return int(dt.timestamp() * 1000)


def ts_to_dt(ts: int) -> datetime:
    """毫秒时间戳转 datetime"""
    return datetime.fromtimestamp(ts / 1000)


def resample_to_weekly(daily_candles: List[Dict]) -> List[Dict]:
    """将日线数据重采样为周线（周一开盘到周日收盘）"""
    from collections import defaultdict
    weeks: Dict[str, List[Dict]] = defaultdict(list)

    for c in daily_candles:
        dt = ts_to_dt(c["ts"])
        # ISO week: (year, week_number)
        week_key = dt.isocalendar()[:2]
        weeks[week_key].append(c)

    result = []
    for week_key in sorted(weeks.keys()):
        day_list = weeks[week_key]
        result.append({
            "ts":    day_list[0]["ts"],
            "open":  day_list[0]["open"],
            "high":  max(d["high"] for d in day_list),
            "low":   min(d["low"]  for d in day_list),
            "close": day_list[-1]["close"],
            "vol":   sum(d["vol"]  for d in day_list),
            "volUsd": sum(d["volUsd"] for d in day_list),
        })

    return result


def add_technical_indicators(candles: List[Dict]) -> List[Dict]:
    """
    添加技术指标 (用于三屏信号评分)
    
    指标:
      - EMA_20:   20周期EMA
      - EMA_50:   50周期EMA
      - MACD:     (EMA12 - EMA26), Signal(EMA9), Histogram
      - ATR_14:   14周期ATR (波动率)
      - RSI_14:   14周期RSI
      - vol_ratio: 成交量相对于20日均量之比
      - sma5/13/30/65/128/200: 简单均线 (MA区间经验法则用)
    """
    closes = [c["close"] for c in candles]
    highs  = [c["high"]  for c in candles]
    lows   = [c["low"]   for c in candles]
    n = len(closes)

    # EMA计算 (length 由 src 本身决定，不依赖外层 n)
    def ema(src, period):
        sz = len(src)
        result = [None] * sz
        k = 2 / (period + 1)
        for i in range(sz):
            if i < period - 1:
                result[i] = None
            elif i == period - 1:
                result[i] = sum(src[:period]) / period
            else:
                result[i] = src[i] * k + result[i-1] * (1 - k)
        return result

    # RSI计算
    def rsi(src, period=14):
        result = [None] * n
        for i in range(period, n):
            gains = [max(src[j] - src[j-1], 0) for j in range(i-period+1, i+1)]
            losses = [max(src[j-1] - src[j], 0) for j in range(i-period+1, i+1)]
            avg_gain = sum(gains) / period
            avg_loss = sum(losses) / period
            if avg_loss == 0:
                result[i] = 100.0
            else:
                rs = avg_gain / avg_loss
                result[i] = 100 - (100 / (1 + rs))
        return result

    # ATR计算
    def atr(period=14):
        result = [None] * n
        tr_list = []
        for i in range(1, n):
            tr = max(
                highs[i] - lows[i],
                abs(highs[i] - closes[i-1]),
                abs(lows[i]  - closes[i-1])
            )
            tr_list.append(tr)
        for i in range(period, len(tr_list)+1):
            if i == period:
                result[i] = sum(tr_list[:period]) / period
            elif result[i-1] is not None:
                result[i] = (result[i-1] * (period-1) + tr_list[i-1]) / period
        return result

    # 成交量均值
    vols = [c["vol"] for c in candles]
    vol_ma20 = [None] * n
    for i in range(19, n):
        vol_ma20[i] = sum(vols[i-19:i+1]) / 20

    ema20  = ema(closes, 20)
    ema50  = ema(closes, 50)
    ema12  = ema(closes, 12)
    ema26  = ema(closes, 26)
    rsi14  = rsi(closes, 14)
    atr14  = atr(14)

    macd_line = [
        (ema12[i] - ema26[i]) if (ema12[i] is not None and ema26[i] is not None) else None
        for i in range(n)
    ]
    macd_values = [v for v in macd_line if v is not None]
    # EMA函数需要独立列表，传入 macd_values 并获取对应长度的 signal_line
    signal_raw = ema(macd_values, 9)   # 长度 == len(macd_values)
    # 对齐 signal_line 到原始长度
    full_signal = [None] * n
    j = 0
    for i in range(n):
        if macd_line[i] is not None:
            full_signal[i] = signal_raw[j]
            j += 1

    # SMA 计算 (MA区间经验法则: MA5/13/30/65/128/200)
    _MA_PERIODS = [5, 13, 30, 65, 128, 200]
    sma_arrays = {}
    for p in _MA_PERIODS:
        arr = [None] * n
        for i in range(p - 1, n):
            arr[i] = sum(closes[i - p + 1:i + 1]) / p
        sma_arrays[p] = arr

    for i, c in enumerate(candles):
        c["ema20"]     = ema20[i]
        c["ema50"]     = ema50[i]
        c["macd"]      = macd_line[i]
        c["macd_signal"] = full_signal[i]
        c["macd_hist"] = (macd_line[i] - full_signal[i]) if (macd_line[i] and full_signal[i]) else None
        c["rsi"]       = rsi14[i]
        c["atr"]       = atr14[i]
        c["vol_ratio"] = (vols[i] / vol_ma20[i]) if vol_ma20[i] else None
        for p in _MA_PERIODS:
            c[f"sma{p}"] = sma_arrays[p][i]

    return candles


# ==================== 命令行接口 ====================

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="OKX历史K线数据获取工具")
    parser.add_argument("--inst",    default="BTC-USDT-SWAP", help="交易对 (默认: BTC-USDT-SWAP)")
    parser.add_argument("--bar",     default="1D",             help="K线周期 1W/1D/4H/1H (默认: 1D)")
    parser.add_argument("--from",    dest="start", default="2025-01-01", help="开始日期 YYYY-MM-DD")
    parser.add_argument("--to",      dest="end",   default="2026-05-16", help="结束日期 YYYY-MM-DD")
    parser.add_argument("--refresh", action="store_true",    help="强制刷新缓存")
    args = parser.parse_args()

    start_ts = dt_to_ts(args.start)
    end_ts   = dt_to_ts(args.end)

    candles = load_or_fetch(args.inst, args.bar, start_ts, end_ts, force_refresh=args.refresh)
    candles = add_technical_indicators(candles)

    print(f"\n✅ 获取 {len(candles)} 根 {args.bar} K线 ({args.inst})")
    if candles:
        first = ts_to_dt(candles[0]["ts"])
        last  = ts_to_dt(candles[-1]["ts"])
        print(f"   时间范围: {first:%Y-%m-%d} ~ {last:%Y-%m-%d}")
        print(f"   最新收盘: ${candles[-1]['close']:,.2f}")
        print(f"   ATR(14):  ${candles[-1].get('atr') or 0:,.2f}")
