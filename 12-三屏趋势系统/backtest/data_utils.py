"""三屏趋势系统 — 回测数据准备工具

数据获取、预处理、多周期对齐等功能。
"""

from typing import Dict, Optional, Tuple, List
import pandas as pd
import numpy as np


def prepare_ohlcv_dataframe(candles: List[Dict]) -> pd.DataFrame:
    """
    将原始K线数据转换为标准OHLCV DataFrame

    参数:
        candles: K线列表，每根为 {"ts", "o", "h", "l", "c", "vol"}

    返回:
        DataFrame with columns: date, open, high, low, close, volume
    """
    if not candles:
        return pd.DataFrame(columns=["date", "open", "high", "low", "close", "volume"])

    df = pd.DataFrame([
        {
            "date": pd.to_datetime(c["ts"], unit="ms"),
            "open": float(c["o"]),
            "high": float(c["h"]),
            "low": float(c["l"]),
            "close": float(c["c"]),
            "volume": float(c.get("vol", 0)),
        }
        for c in candles
    ])

    df = df.sort_values("date").reset_index(drop=True)
    return df


def fetch_historical_data(
    symbol: str = "BTC-USDT",
    bar: str = "1D",
    limit: int = 1000,
) -> pd.DataFrame:
    """
    从OKX获取历史K线数据

    参数:
        symbol: 交易对，如 "BTC-USDT"
        bar: 时间周期，如 "1D", "4H", "1H"
        limit: 获取数量

    返回:
        OHLCV DataFrame
    """
    try:
        from data.market_data import fetch_candles
    except ImportError:
        import sys
        import os
        sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
        from data.market_data import fetch_candles

    candles = fetch_candles(symbol, bar, limit)
    return prepare_ohlcv_dataframe(candles)


def train_test_split(
    df: pd.DataFrame,
    train_ratio: float = 0.7,
    by_date: bool = True,
) -> Tuple[pd.DataFrame, pd.DataFrame]:
    """
    样本内/样本外分割

    参数:
        df: 数据DataFrame
        train_ratio: 训练集比例
        by_date: 按日期分割（True）还是随机分割（False）

    返回:
        (train_df, test_df)
    """
    if by_date:
        split_idx = int(len(df) * train_ratio)
        train_df = df.iloc[:split_idx].copy()
        test_df = df.iloc[split_idx:].copy()
    else:
        shuffled = df.sample(frac=1, random_state=42)
        split_idx = int(len(shuffled) * train_ratio)
        train_df = shuffled.iloc[:split_idx].copy()
        test_df = shuffled.iloc[split_idx:].copy()

    return train_df, test_df


def generate_sample_data(
    n_days: int = 1000,
    start_price: float = 100.0,
    volatility: float = 0.02,
    drift: float = 0.0001,
    seed: int = 42,
) -> pd.DataFrame:
    """
    生成合成测试数据（几何布朗运动）

    用于快速测试回测框架，不需要真实数据。

    参数:
        n_days: 天数
        start_price: 起始价格
        volatility: 日波动率
        drift: 日漂移率
        seed: 随机种子

    返回:
        OHLCV DataFrame
    """
    np.random.seed(seed)

    dates = pd.date_range(end=pd.Timestamp.now(), periods=n_days, freq="D")

    returns = np.random.normal(drift, volatility, n_days)
    close_prices = start_price * np.cumprod(1 + returns)

    open_prices = np.zeros(n_days)
    high_prices = np.zeros(n_days)
    low_prices = np.zeros(n_days)

    for i in range(n_days):
        if i == 0:
            open_prices[i] = start_price
        else:
            open_prices[i] = close_prices[i - 1]

        day_vol = volatility * close_prices[i]
        high_prices[i] = max(open_prices[i], close_prices[i]) + abs(np.random.normal(0, day_vol * 0.3))
        low_prices[i] = min(open_prices[i], close_prices[i]) - abs(np.random.normal(0, day_vol * 0.3))

    volumes = np.random.lognormal(10, 1, n_days) * close_prices * 0.1

    df = pd.DataFrame({
        "date": dates,
        "open": open_prices,
        "high": high_prices,
        "low": low_prices,
        "close": close_prices,
        "volume": volumes,
    })

    return df
