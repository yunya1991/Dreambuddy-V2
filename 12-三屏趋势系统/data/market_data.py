"""三屏趋势系统 — 市场数据获取

提供 K 线数据获取和跨周期重采样功能。
数据源可插拔，默认使用 OKX API。
"""

import subprocess
import os
from typing import List, Dict, Optional


def _get_okx_client():
    """获取 OKX 客户端（从全局注册的适配器）"""
    try:
        from dreamllm.services.registry import get_adapter
        adapter = get_adapter("okx")
        if adapter and hasattr(adapter, "get_kline"):
            return adapter
    except Exception:
        pass
    return None


def _run_okx(args: list) -> dict:
    """通过 OKX CLI 获取数据（回退方案）"""
    home_bin = "/opt/homebrew/bin"
    env = os.environ.copy()
    env["PATH"] = home_bin + ":" + env.get("PATH", "")
    try:
        r = subprocess.run(
            ["okx"] + args + ["--profile", "screen_trade"],
            capture_output=True, text=True, timeout=15, env=env,
        )
        if r.returncode == 0 and r.stdout.strip():
            import json
            return {"ok": True, "data": json.loads(r.stdout)}
    except Exception:
        pass
    return {"ok": False, "data": None}


def fetch_candles(inst_id: str, bar: str, limit: int) -> List[Dict]:
    """
    获取K线数据

    参数:
        inst_id: 交易对ID，如 "BTC-USDT"
        bar: 时间周期，如 "1m", "5m", "1H", "4H", "1D", "1W"
        limit: 获取数量

    返回:
        K线列表，每根为 {"ts", "o", "h", "l", "c", "vol"}，时间正序
    """
    # 方式1: OKX 客户端
    client = _get_okx_client()
    if client:
        try:
            r = client.get_kline(inst_id, bar=bar, limit=limit)
            if r.get("ok"):
                candles = []
                for c in r.get("candles", []):
                    candles.append({
                        "ts": int(c["ts"]),
                        "o": float(c["o"]),
                        "h": float(c["h"]),
                        "l": float(c["l"]),
                        "c": float(c["c"]),
                        "vol": float(c.get("vol", 0)),
                    })
                return list(reversed(candles))
        except Exception:
            pass

    # 方式2: OKX CLI 回退
    r = _run_okx(["market", "candles", inst_id, "--bar", bar, "--limit", str(limit), "--json"])
    if not r["ok"]:
        return []
    raw = r["data"]
    candles = []
    for c in raw:
        candles.append({
            "ts": int(c[0]),
            "o": float(c[1]),
            "h": float(c[2]),
            "l": float(c[3]),
            "c": float(c[4]),
            "vol": float(c[5]),
        })
    return list(reversed(candles))


def _infer_timeframe(candles: List[Dict]) -> str:
    """根据K线间隔推断时间周期"""
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


def resample_candles(candles: List[Dict], target_tf: str) -> List[Dict]:
    """
    跨周期数据对齐：将低时间周期K线聚合成高时间周期K线

    参考 Backtrader 的 resampling 机制。

    聚合规则:
    - Open: 周期内第一根K线的开盘价
    - High: 周期内最高价
    - Low: 周期内最低价
    - Close: 周期内最后一根K线的收盘价
    - Volume: 周期内成交量之和

    支持的聚合:
    - 5m -> 1h: 12根
    - 1h -> 4h: 4根
    - 1h -> 1D: 24根
    - 4h -> 1D: 6根
    - 15m -> 1h: 4根
    - 15m -> 4h: 16根
    - 30m -> 1h: 2根
    - 30m -> 4h: 8根
    - 30m -> 1D: 48根

    返回: 聚合后的K线列表
    """
    if not candles:
        return []

    tf_mapping = {
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

    source_tf = _infer_timeframe(candles)
    key = (source_tf, target_tf)

    if key not in tf_mapping:
        return candles

    n = tf_mapping[key]
    result = []

    for i in range(0, len(candles), n):
        group = candles[i:i + n]
        if len(group) < n:
            continue
        result.append({
            "ts": group[0]["ts"],
            "o": group[0]["o"],
            "h": max(c["h"] for c in group),
            "l": min(c["l"] for c in group),
            "c": group[-1]["c"],
            "vol": sum(c["vol"] for c in group),
        })

    return result
