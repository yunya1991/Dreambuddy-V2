"""data_compat — 9-基本面分析 data_collector 兼容层。

fetch_tavily_news 用 TavilyCollector 替换手写 HTTP，
返回格式兼容老 data_collector.fetch_tavily_news 的 List[Dict]。
DataCollector / generate_timeseries 暂转发老实现 + DeprecationWarning。
"""
from __future__ import annotations

import os
import sys
import warnings

from data_center.collectors.news.tavily_collector import TavilyCollector

# data_collector 所在路径
_DATA_COLLECTOR_DIR = os.path.join(
    os.path.dirname(__file__), "..", "..", "..", "9-基本面分析"
)


def fetch_tavily_news(query: str, max_results: int = 10) -> list[dict]:
    """兼容老 data_collector.fetch_tavily_news 签名。

    Returns:
        List[Dict] 每条含 title/content/url/source/published_at
    """
    api_key = os.environ.get("TAVILY_API_KEY", "")
    collector = TavilyCollector(config={"api_key": api_key})
    if not collector.is_available():
        return []

    recs = collector.fetch({"query": query, "max_results": max_results})
    results = []
    for r in recs:
        content = r.events[0].get("content", "") if r.events else ""
        results.append({
            "title": r.metrics.get("title", ""),
            "url": r.metrics.get("url", ""),
            "source": r.metrics.get("source", ""),
            "content": content,
            "published_at": r.raw.get("published_date", ""),
            "raw_content": dict(r.raw),
        })
    return results


def _import_legacy_data_collector():
    """延迟导入老 data_collector 模块。"""
    dc_dir = os.path.abspath(_DATA_COLLECTOR_DIR)
    if dc_dir not in sys.path:
        sys.path.insert(0, dc_dir)
    import data_collector
    return data_collector


class DataCollector:
    """兼容老 data_collector.DataCollector。

    复杂多方法类暂转发老实现，发 DeprecationWarning 引导迁移到 DataCenter。
    """

    def __init__(self, *args, **kwargs):
        warnings.warn(
            "data_collector.DataCollector 已废弃，请迁移到 "
            "from data_center import DataCenter",
            DeprecationWarning,
            stacklevel=2,
        )
        legacy = _import_legacy_data_collector()
        self._impl = legacy.DataCollector(*args, **kwargs)

    def __getattr__(self, name):
        return getattr(self._impl, name)


def generate_timeseries(module: str, days: int = 30):
    """兼容老 data_collector.generate_timeseries 签名。"""
    warnings.warn(
        "data_collector.generate_timeseries 已废弃，请迁移到 data_center",
        DeprecationWarning,
        stacklevel=2,
    )
    legacy = _import_legacy_data_collector()
    return legacy.generate_timeseries(module, days)
