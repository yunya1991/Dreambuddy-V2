"""
数据获取模块 — 从OKX获取K线历史数据

Phase 0: 优先从本地已有数据加载，没有则从OKX API拉取
"""

import os
import json
import time
from typing import List, Dict, Optional
from pathlib import Path

import numpy as np
import pandas as pd


def _get_okx_client():
    """获取OKX客户端（优先使用系统已有的okx_simulated）"""
    try:
        from ..okx_simulated import OKXSimulatedClient
        return OKXSimulatedClient()
    except Exception:
        pass
    try:
        from okx import OKXClient
        return OKXClient()
    except Exception:
        pass
    return None


def load_kline_from_local(
    symbol: str,
    timeframe: str = "1H",
    data_dir: Optional[str] = None,
) -> Optional[pd.DataFrame]:
    """从本地加载K线数据"""
    if data_dir is None:
        data_dir = Path(__file__).parent.parent.parent / "data" / "klines"
    else:
        data_dir = Path(data_dir)

    filepath = data_dir / f"{symbol}_{timeframe}.csv"

    if filepath.exists():
        df = pd.read_csv(filepath)
        if "timestamp" in df.columns:
            # Bug修复: 统一 UTC 时区，避免与其他来源数据的时区冲突
            ts = pd.to_datetime(df["timestamp"])
            if ts.dt.tz is None:
                ts = ts.dt.tz_localize("UTC")
            else:
                ts = ts.dt.tz_convert("UTC")
            df["timestamp"] = ts
            df = df.set_index("timestamp")
        elif "ts" in df.columns:
            ts = pd.to_datetime(df["ts"], unit="ms", utc=True)
            df["timestamp"] = ts
            df = df.set_index("timestamp")
        else:
            # 用第一列当时间索引
            df = df.set_index(df.columns[0])
            ts = pd.to_datetime(df.index)
            if ts.tz is None:
                ts = ts.tz_localize("UTC")
            else:
                ts = ts.tz_convert("UTC")
            df.index = ts
        df.index.name = "timestamp"
        return df
    return None


def fetch_okx_klines(
    symbol: str,
    bar: str = "1H",
    limit: int = 1000,
    max_pages: int = 5,
) -> pd.DataFrame:
    """
    从OKX获取K线数据

    Args:
        symbol: 交易对，如 BTC-USDT
        bar: K线周期: 1H, 4H, 1D 等
        limit: 每次请求的K线数量 (最大100)
        max_pages: 最大翻页次数

    Returns:
        DataFrame with columns: open, high, low, close, volume
        index = timestamp
    """
    all_data = []
    after = None  # 分页锚点

    for page in range(max_pages):
        try:
            import requests
            url = "https://www.okx.com/api/v5/market/history-candles"
            params = {
                "instId": f"{symbol}-USDT",
                "bar": bar,
                "limit": min(limit, 100),
            }
            if after:
                params["after"] = str(after)

            resp = requests.get(url, params=params, timeout=10)
            data = resp.json()

            if data.get("code") != "0":
                break

            candles = data.get("data", [])
            if not candles:
                break

            all_data.extend(candles)

            # 设置下一页锚点 (最后一根K线的ts)
            after = candles[-1][0]

            if len(candles) < limit:
                break

            time.sleep(0.2)  # 限频

        except Exception as e:
            print(f"  获取K线失败 (page {page+1}): {e}")
            break

    if not all_data:
        return pd.DataFrame()

    # 解析数据
    # OKX K线格式: [ts, o, h, l, c, vol, volCcy, volCcyQuote, confirm]
    df = pd.DataFrame(all_data, columns=[
        "ts", "open", "high", "low", "close",
        "volume", "vol_ccy", "vol_ccy_quote", "confirm"
    ])

    # 类型转换
    for col in ["open", "high", "low", "close", "volume"]:
        df[col] = df[col].astype(float)

    df["ts"] = df["ts"].astype(int)
    # Bug修复: 统一使用 UTC 时区，避免与其他数据拼接时 datetime64[ns] vs datetime64[ns, UTC] 错误
    df["timestamp"] = pd.to_datetime(df["ts"], unit="ms", utc=True)
    df = df.set_index("timestamp")
    df = df.sort_index()

    return df[["open", "high", "low", "close", "volume"]]


def save_klines(df: pd.DataFrame, symbol: str, timeframe: str, data_dir: Optional[str] = None):
    """保存K线到本地"""
    if data_dir is None:
        data_dir = Path(__file__).parent.parent.parent / "data" / "klines"
    else:
        data_dir = Path(data_dir)

    data_dir.mkdir(parents=True, exist_ok=True)
    filepath = data_dir / f"{symbol}_{timeframe}.csv"
    df.to_csv(filepath)
    print(f"  已保存到: {filepath}")


def get_klines(
    symbol: str,
    timeframe: str = "1H",
    use_cache: bool = True,
    refresh: bool = False,
    max_bars: int = 5000,
) -> pd.DataFrame:
    """
    获取K线数据 (统一入口)

    优先级: 本地缓存 → OKX API
    """
    sym_usdt = symbol.replace("-USDT", "").replace("USDT", "")
    sym_key = f"{sym_usdt}-USDT"

    # 尝试本地加载
    if use_cache and not refresh:
        df = load_kline_from_local(sym_usdt, timeframe)
        if df is not None and len(df) > 100:
            print(f"  从本地加载: {len(df)}根K线")
            return df.tail(max_bars)

    # 从OKX拉取
    print(f"  从OKX获取 {sym_key} {timeframe} K线...")
    df = fetch_okx_klines(sym_usdt, bar=timeframe, limit=100, max_pages=max_bars // 100 + 1)

    if len(df) > 0:
        print(f"  获取到 {len(df)}根K线")
        if use_cache:
            save_klines(df, sym_usdt, timeframe)
        return df.tail(max_bars)

    return pd.DataFrame()
