"""V4+波浪策略 — 市场数据获取

提供 K 线数据获取和跨周期重采样功能。
数据源可插拔，默认使用 OKX API。
"""

try:
    from .market_data import fetch_candles, fetch_historical_candles, resample_candles, candles_to_dataframe
except ImportError:
    from market_data import fetch_candles, fetch_historical_candles, resample_candles, candles_to_dataframe

__all__ = [
    "fetch_candles",
    "fetch_historical_candles",
    "resample_candles",
    "candles_to_dataframe",
]
