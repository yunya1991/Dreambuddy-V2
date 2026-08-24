"""flow_compat — 9-基本面分析 flow_collector 兼容层。

fetch_yahoo_symbol / fetch_fred_series 用 YFinanceCollector / FredCollector 替换手写 HTTP；
run_full_collection 是复杂三层编排器（2300+ 行），compat 版转发老实现 + 发 DeprecationWarning。
"""
from __future__ import annotations

import os
import sys
import warnings

from data_center.collectors.finance.yfinance_collector import YFinanceCollector
from data_center.collectors.macro.fred_collector import FredCollector

# flow_collector 所在路径（老代码）
_FLOW_COLLECTOR_DIR = os.path.join(
    os.path.dirname(__file__), "..", "..", "..",
    "9-基本面分析", "ops", "nanoclaw", "core_task1", "flow", "scripts",
)


def fetch_yahoo_symbol(symbol: str) -> dict | None:
    """兼容老 flow_collector.fetch_yahoo_symbol 签名。

    用 YFinanceCollector 替换手写 HTTP，返回含 symbol/price/currency 的 dict。
    """
    try:
        collector = YFinanceCollector()
        if not collector.is_available():
            return None
        recs = collector.fetch({"symbol": symbol})
        if not recs:
            return None
        r = recs[0]
        return {
            "symbol": r.metrics.get("symbol", symbol),
            "price": r.metrics.get("price"),
            "currency": r.metrics.get("currency", ""),
            "raw": dict(r.raw),
        }
    except Exception:
        return None


def fetch_fred_series(series_id: str, api_key: str | None = None) -> dict | None:
    """兼容老 flow_collector.fetch_fred_series 签名。

    用 FredCollector 替换手写 HTTP，返回含 series_id/value 的 dict。
    """
    key = api_key or os.environ.get("FRED_API_KEY", "")
    if not key:
        return None
    try:
        collector = FredCollector(config={"api_key": key})
        if not collector.is_available():
            return None
        recs = collector.fetch({"series": series_id})
        if not recs:
            return None
        r = recs[0]
        return {
            "series_id": series_id,
            "value": r.metrics.get("value"),
            "timeseries": r.timeseries,
            "raw": dict(r.raw),
        }
    except Exception:
        return None


def _run_full_collection_legacy() -> dict:
    """延迟导入老 flow_collector.run_full_collection。"""
    flow_dir = os.path.abspath(_FLOW_COLLECTOR_DIR)
    if flow_dir not in sys.path:
        sys.path.insert(0, flow_dir)
    import flow_collector
    return flow_collector.run_full_collection()


def run_full_collection() -> dict:
    """兼容老 flow_collector.run_full_collection 签名。

    复杂三层编排器暂转发老实现，发 DeprecationWarning 引导迁移到 DataCenter。
    """
    warnings.warn(
        "flow_collector.run_full_collection 已废弃，请迁移到 "
        "from data_center import DataCenter; dc.fetch('macro'/'finance'/'chain')",
        DeprecationWarning,
        stacklevel=2,
    )
    return _run_full_collection_legacy()
