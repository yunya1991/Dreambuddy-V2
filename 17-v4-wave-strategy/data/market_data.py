"""V4+波浪策略 — 市场数据获取

提供 K 线数据获取和跨周期重采样功能。
数据源可插拔，默认使用 OKX API。

历史数据获取支持：
- 通过分页获取2-3年的历史K线数据
- 使用OKX Python SDK（okx包）的history-candles接口
- 使用before/after参数进行分页
- 自动去重和数据合并
"""

import subprocess
import os
import time
from typing import List, Dict, Optional
import json
import pandas as pd


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
            capture_output=True, text=True, timeout=30, env=env,
        )
        if r.returncode == 0 and r.stdout.strip():
            return {"ok": True, "data": json.loads(r.stdout)}
    except Exception:
        pass
    return {"ok": False, "data": None}


def fetch_candles(inst_id: str, bar: str, limit: int) -> List[Dict]:
    """
    获取K线数据（单次调用）

    参数:
        inst_id: 交易对ID，如 "BTC-USDT"
        bar: 时间周期，如 "1m", "5m", "1H", "4H", "1D", "1W"
        limit: 获取数量

    返回:
        K线列表，每根为 {"ts", "o", "h", "l", "c", "vol"}，时间正序
    """
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


def fetch_historical_candles(
    inst_id: str,
    bar: str = "1D",
    days: int = 730,
    max_limit_per_page: int = 300,
) -> List[Dict]:
    """
    通过分页获取历史K线数据（支持2-3年）

    使用OKX Python SDK的history-candles接口，支持after参数进行分页。
    API返回数据为降序（最新在前），每次用after参数获取更早的数据。

    参数:
        inst_id: 交易对ID，如 "BTC-USDT"
        bar: 时间周期，如 "1m", "5m", "1H", "4H", "1D", "1W"
        days: 获取天数，默认730天（约2年）
        max_limit_per_page: 每页最大数量，默认300

    返回:
        K线列表，时间正序排列，已去重
    """
    all_candles = []
    seen_ts = set()
    after = None
    page = 0
    max_pages = (days // max_limit_per_page) + 10

    print(f"  开始获取 {inst_id} {bar} 历史数据，目标 {days} 天...")

    try:
        from okx.api import Market

        market = Market(flag="0")

        while page < max_pages:
            try:
                if after:
                    r = market.get_history_candles(
                        instId=inst_id,
                        bar=bar,
                        limit=max_limit_per_page,
                        after=after,
                    )
                else:
                    r = market.get_history_candles(
                        instId=inst_id,
                        bar=bar,
                        limit=max_limit_per_page,
                    )

                if r.get("code") != "0":
                    print(f"  [WARN] 第 {page+1} 页API返回错误: {r.get('msg')}")
                    break

                raw = r.get("data", [])
                if not raw or len(raw) == 0:
                    print(f"  [INFO] 第 {page+1} 页无数据，停止")
                    break

                new_candles = []
                for c in raw:
                    ts = int(c[0])
                    if ts in seen_ts:
                        continue
                    seen_ts.add(ts)
                    new_candles.append({
                        "ts": ts,
                        "o": float(c[1]),
                        "h": float(c[2]),
                        "l": float(c[3]),
                        "c": float(c[4]),
                        "vol": float(c[5]),
                    })

                if not new_candles:
                    print(f"  [INFO] 第 {page+1} 页无新数据，停止")
                    break

                all_candles.extend(new_candles)
                oldest_ts = min(c["ts"] for c in new_candles)
                after = str(oldest_ts)

                print(f"  第 {page+1} 页: {len(new_candles)} 条，累计 {len(all_candles)} 条")

                page += 1
                time.sleep(0.3)

            except Exception as e:
                print(f"  [WARN] 第 {page+1} 页获取失败: {e}")
                break

    except ImportError:
        print("  [WARN] OKX SDK未安装，使用CLI方案")
        pass

    if not all_candles:
        print(f"  [WARN] 通过SDK未获取到数据，尝试CLI回退方案")
        all_candles = fetch_candles(inst_id, bar, min(days, 1000))

    all_candles.sort(key=lambda x: x["ts"])

    print(f"  完成: 共获取 {len(all_candles)} 条数据")
    if all_candles:
        import datetime
        start_dt = datetime.datetime.fromtimestamp(all_candles[0]["ts"] / 1000)
        end_dt = datetime.datetime.fromtimestamp(all_candles[-1]["ts"] / 1000)
        print(f"  时间范围: {start_dt.strftime('%Y-%m-%d')} ~ {end_dt.strftime('%Y-%m-%d')}")

    return all_candles


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


def candles_to_dataframe(candles: List[Dict]) -> pd.DataFrame:
    """将K线列表转换为 pandas DataFrame

    返回 DataFrame 列: open, high, low, close, volume，索引为时间
    """
    if not candles:
        return pd.DataFrame()

    df = pd.DataFrame(candles)
    df["timestamp"] = pd.to_datetime(df["ts"], unit="ms")
    df = df.set_index("timestamp")
    df = df.rename(columns={
        "o": "open",
        "h": "high",
        "l": "low",
        "c": "close",
        "vol": "volume",
    })
    df = df[["open", "high", "low", "close", "volume"]]
    return df
