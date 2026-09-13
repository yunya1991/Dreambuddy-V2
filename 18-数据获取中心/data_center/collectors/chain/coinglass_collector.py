"""Coinglass 衍生品聚合采集器 — V4 API + stealthy 爬虫回退。

数据源:
  - API: https://open-api-v4.coinglass.com/api/futures/* (需 CG_API_KEY)
  - Web: https://www.coinglass.com/zh/* (stealthy mode 绕过 Cloudflare)

覆盖:
  - 持仓量(OI): /api/futures/open-interest/aggregated-history
  - 资金费率(Funding Rate): /api/futures/funding-rate/exchange-list
  - 清算数据(Liquidations): /api/futures/liquidation/aggregated-history
  - 多空比(Long/Short Ratio): /api/futures/global-long-short-account-ratio/history

用于 AGI 蓝图 L1 感知层核心缺口（衍生品数据完全缺失）。
"""
from __future__ import annotations

import os
from datetime import datetime, timezone

import requests

from data_center.collectors._base import BaseCollector
from data_center.core.contract import DataRecord, validate_record

_API_BASE = "https://open-api-v4.coinglass.com/api/futures"

# Web 回退页面
_PAGES = {
    "oi": "https://www.coinglass.com/zh/FuturesData",
    "funding": "https://www.coinglass.com/zh/FundingRate",
    "liquidations": "https://www.coinglass.com/zh/FuturesLiquidationChart",
    "long_short": "https://www.coinglass.com/zh/FuturesLongShortRatioChart",
}


def _now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat()


class CoinglassCollector(BaseCollector):
    """Coinglass 衍生品数据采集器（OI/Funding/清算/多空比）。"""

    source = "coinglass"
    category = "chain"

    def __init__(self, config: dict | None = None):
        super().__init__(config)
        self._api_key: str = (
            self.config.get("api_key")
            or os.environ.get("COINGLASS_API_KEY", "")
            or os.environ.get("CG_API_KEY", "")
        )

    def is_available(self) -> bool:
        return True  # 有 API Key 走 API，无 Key 走 stealthy 爬虫

    def fetch(self, params: dict) -> list[DataRecord]:
        pages = params.get("pages", "all")
        if pages == "all":
            page_keys = list(_PAGES.keys())
        elif isinstance(pages, list):
            page_keys = [p for p in pages if p in _PAGES]
        else:
            page_keys = [pages] if pages in _PAGES else []

        if not page_keys:
            return []

        # 优先走 V4 API（如果有 Key）
        if self._api_key:
            recs = self._fetch_via_api(page_keys)
            if recs:
                return recs

        # 回退到 stealthy 爬虫
        recs: list[DataRecord] = []
        for page_key in page_keys:
            items = self._fetch_page_stealthy(page_key)
            if items:
                rec = self._build_record(page_key, items)
                recs.append(rec)
        return recs

    # ==================================================================
    # V4 API 方式
    # ==================================================================
    def _fetch_via_api(self, page_keys: list[str]) -> list[DataRecord]:
        recs: list[DataRecord] = []
        headers = {"accept": "application/json", "CG-API-KEY": self._api_key}

        for key in page_keys:
            try:
                if key == "oi":
                    data = self._api_call(
                        f"{_API_BASE}/open-interest/aggregated-history",
                        headers, {"symbol": "BTC", "interval": "1d", "limit": 7},
                    )
                    recs.append(self._build_api_record("open_interest", data, "oi"))
                elif key == "funding":
                    data = self._api_call(
                        f"{_API_BASE}/funding-rate/exchange-list",
                        headers, {"symbol": "BTC"},
                    )
                    recs.append(self._build_api_record("funding_rate", data, "funding"))
                elif key == "liquidations":
                    data = self._api_call(
                        f"{_API_BASE}/liquidation/aggregated-history",
                        headers, {"symbol": "BTC", "interval": "1d", "limit": 7},
                    )
                    recs.append(self._build_api_record("liquidations", data, "liquidations"))
                elif key == "long_short":
                    data = self._api_call(
                        f"{_API_BASE}/global-long-short-account-ratio/history",
                        headers, {"symbol": "BTC", "interval": "1d", "limit": 7},
                    )
                    recs.append(self._build_api_record("long_short_ratio", data, "long_short"))
            except Exception:
                pass  # fail-open per page

        return recs

    @staticmethod
    def _api_call(url: str, headers: dict, params: dict) -> dict:
        resp = requests.get(url, headers=headers, params=params, timeout=15)
        resp.raise_for_status()
        return resp.json()

    def _build_api_record(self, sub_category: str, data: dict, page_key: str) -> DataRecord:
        """从 V4 API 响应构建 DataRecord。"""
        metrics: dict[str, float | str] = {"page": page_key}
        ts_list: list[dict] = []
        raw_data = data.get("data", [])

        if isinstance(raw_data, list) and raw_data:
            for i, item in enumerate(raw_data[-7:]):  # 最近7条
                if isinstance(item, dict):
                    ts_entry: dict[str, float | str] = {}
                    for k, v in item.items():
                        try:
                            ts_entry[k] = float(v) if isinstance(v, (int, float, str)) else str(v)[:100]
                        except (ValueError, TypeError):
                            ts_entry[k] = str(v)[:100] if v is not None else 0.0
                    ts_list.append(ts_entry)
                    # 扁平化最新一条到 metrics
                    if i == len(raw_list := raw_data[-7:]) - 1:
                        for k, v in item.items():
                            try:
                                metrics[f"latest_{k}"] = float(v) if isinstance(v, (int, float, str)) else str(v)[:100]
                            except (ValueError, TypeError):
                                metrics[f"latest_{k}"] = str(v)[:100] if v is not None else 0.0
        elif isinstance(raw_data, dict):
            # exchange-list 格式：dict of exchange→rate
            for ex, val in list(raw_data.items())[:10]:
                try:
                    metrics[f"{ex}_rate"] = float(val.get("rate", 0) if isinstance(val, dict) else val)
                except (ValueError, TypeError):
                    pass

        metrics["data_source"] = "coinglass_v4_api"

        rec = DataRecord(
            source="coinglass",
            category="chain",
            sub_category=sub_category,
            timestamp=_now_iso(),
            metrics=metrics,
            events=[],
            timeseries=ts_list,
            raw={"source": "coinglass.com", "page": page_key, "api": "v4"},
        )
        validate_record(rec)
        return rec

    # ==================================================================
    # Stealthy 爬虫回退
    # ==================================================================
    def _fetch_page_stealthy(self, page_key: str) -> list[dict]:
        """用 ScraplingEngine stealthy mode 抓取页面。"""
        url = _PAGES.get(page_key, "")
        if not url:
            return []
        try:
            from data_center.crawler.scrapling_engine import ScraplingEngine
            engine = ScraplingEngine()
            html = engine.fetch_html(url, mode="stealthy")
            if not html:
                return []
            # 通用表格解析
            site = {
                "selectors": {
                    "item": "table tbody tr, div[class*='row']",
                    "exchange": "td:first-child::text, div[class*='name']::text",
                    "value": "td:nth-child(2)::text, div[class*='value']::text",
                },
                "adaptive": True,
            }
            return engine.parse(html, site)
        except Exception:
            return []

    def _build_record(self, page_key: str, items: list[dict]) -> DataRecord:
        sub_map = {
            "oi": "open_interest",
            "funding": "funding_rate",
            "liquidations": "liquidations",
            "long_short": "long_short_ratio",
        }
        ts = _now_iso()

        metrics: dict[str, float | str] = {"page": page_key, "item_count": len(items), "data_source": "stealthy_scrape"}
        for i, item in enumerate(items[:10]):
            for k, v in item.items():
                metrics_key = f"item_{i}_{k}"
                try:
                    metrics[metrics_key] = float(v) if isinstance(v, (int, float, str)) else str(v)[:100]
                except (ValueError, TypeError):
                    metrics[metrics_key] = str(v)[:100]

        rec = DataRecord(
            source="coinglass",
            category="chain",
            sub_category=sub_map.get(page_key, page_key),
            timestamp=ts,
            metrics=metrics,
            events=[],
            timeseries=[],
            raw={"source": "coinglass.com", "page": page_key, "items": items[:20]},
        )
        validate_record(rec)
        return rec
