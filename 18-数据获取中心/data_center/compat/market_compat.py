"""market_compat — 12-三屏趋势系统 market_data 兼容层。

fetch_candles 用 ccxt 替换 OKX SDK 直连，inst_id/bar 格式自动转换；
resample_candles 是纯数据变换，直接复用老逻辑。
"""
from __future__ import annotations

import ccxt


def fetch_candles(inst_id: str, bar: str, limit: int) -> list[dict]:
    """获取K线数据（兼容老 market_data.fetch_candles 签名）。

    Args:
        inst_id: OKX 格式 "BTC-USDT" → 自动转 ccxt "BTC/USDT"
        bar: OKX 格式 "1H"/"4H"/"1D"/"1W" → 自动转小写
        limit: 获取数量
    Returns:
        K线列表 [{"ts","o","h","l","c","vol"}]，时间正序
    """
    symbol = inst_id.replace("-", "/")
    timeframe = bar.lower()
    try:
        exchange = ccxt.okx()
        raw = exchange.fetch_ohlcv(symbol, timeframe=timeframe, limit=limit)
        candles = [
            {
                "ts": int(item[0] / 1000),
                "o": float(item[1]),
                "h": float(item[2]),
                "l": float(item[3]),
                "c": float(item[4]),
                "vol": float(item[5]),
            }
            for item in (raw or [])
        ]
        return list(reversed(candles))
    except Exception:
        return []


def _infer_timeframe(candles: list[dict]) -> str:
    if len(candles) < 2:
        return "1h"
    diff = candles[1]["ts"] - candles[0]["ts"]
    diff_min = diff / 60000
    if diff_min <= 1:
        return "1m"
    elif diff_min <= 5:
        return "5m"
    elif diff_min <= 15:
        return "15m"
    elif diff_min <= 30:
        return "30m"
    elif diff_min <= 60:
        return "1h"
    elif diff_min <= 240:
        return "4h"
    elif diff_min <= 1440:
        return "1D"
    else:
        return "1W"


_TF_MAPPING = {
    ("5m", "1h"): 12,
    ("1h", "4h"): 4,
    ("1h", "1D"): 24,
    ("4h", "1D"): 6,
    ("15m", "1h"): 4,
    ("15m", "4h"): 16,
    ("30m", "1h"): 2,
    ("30m", "4h"): 8,
    ("30m", "1D"): 48,
}


def resample_candles(candles: list[dict], target_tf: str) -> list[dict]:
    """跨周期K线聚合（兼容老 market_data.resample_candles）。"""
    if not candles:
        return []
    source_tf = _infer_timeframe(candles)
    key = (source_tf, target_tf)
    if key not in _TF_MAPPING:
        return candles
    n = _TF_MAPPING[key]
    result = []
    for i in range(0, len(candles), n):
        group = candles[i : i + n]
        if len(group) < n:
            continue
        result.append(
            {
                "ts": group[0]["ts"],
                "o": group[0]["o"],
                "h": max(c["h"] for c in group),
                "l": min(c["l"] for c in group),
                "c": group[-1]["c"],
                "vol": sum(c["vol"] for c in group),
            }
        )
    return result
