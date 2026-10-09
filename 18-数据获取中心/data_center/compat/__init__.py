"""data_center.compat — 老调用方兼容层。

提供与老模块（flow_collector / data_collector / market_data）同签名的函数，
内部走 DataCenter 或 ccxt 等成熟库，调用方切换 import 即可。
"""
from data_center.compat.market_compat import fetch_candles, resample_candles

try:
    from data_center.compat.data_compat import fetch_tavily_news, DataCollector, generate_timeseries
except ImportError:
    fetch_tavily_news = None
    DataCollector = None
    generate_timeseries = None

try:
    from data_center.compat.flow_compat import (
        fetch_yahoo_symbol,
        fetch_fred_series,
        run_full_collection,
    )
except ImportError:
    fetch_yahoo_symbol = None
    fetch_fred_series = None
    run_full_collection = None

__all__ = [
    "fetch_candles",
    "resample_candles",
    "fetch_tavily_news",
    "fetch_yahoo_symbol",
    "fetch_fred_series",
    "run_full_collection",
    "DataCollector",
    "generate_timeseries",
]
