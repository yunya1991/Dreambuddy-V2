"""CoinMarketCap 币种排名/F&G 采集器 — 免费 tier REST API，需 Key。

端点：
  GET /v1/cryptocurrency/listings/latest — 币种排名/市值
  GET /v3/fear-and-greed/latest — CMC F&G 指数
  GET /v1/cryptocurrency/quotes/latest — 单币种行情

免费 tier: 10,000 calls/月，需 CoinMarketCap API Key。
与 CoinGecko 交叉验证排名数据。
"""
from __future__ import annotations

import os
from datetime import datetime, timezone

import requests

from data_center.collectors._base import BaseCollector
from data_center.core.contract import DataRecord, validate_record

_BASE = "https://pro-api.coinmarketcap.com"


def _now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat()


class CoinMarketCapCollector(BaseCollector):
    """CoinMarketCap 币种排名 + F&G 采集器。"""

    source = "coinmarketcap"
    category = "coin"

    def __init__(self, config: dict | None = None):
        super().__init__(config)
        self._api_key: str = (
            self.config.get("api_key")
            or os.environ.get("COINMARKETCAP_API_KEY", "")
        )

    def is_available(self) -> bool:
        return bool(self._api_key)

    def _headers(self) -> dict:
        return {"X-CMC_PRO_API_KEY": self._api_key}

    def fetch(self, params: dict) -> list[DataRecord]:
        if not self.is_available():
            return []
        route = params.get("route", "listings")
        try:
            if route == "listings":
                return self._fetch_listings(params)
            if route == "fear_greed":
                return self._fetch_fear_greed(params)
        except Exception:
            return []  # fail-open

    def _fetch_listings(self, params: dict) -> list[DataRecord]:
        limit = params.get("limit", 20)
        resp = requests.get(
            f"{_BASE}/v1/cryptocurrency/listings/latest",
            headers=self._headers(),
            params={"start": 1, "limit": limit, "convert": "USD"},
            timeout=20,
        )
        resp.raise_for_status()
        data = resp.json().get("data", [])

        ts_list: list[dict] = []
        top_name = ""
        top_mcap = 0.0
        for coin in data[:20]:
            name = coin.get("name", "")
            symbol = coin.get("symbol", "")
            mcap = float(coin.get("quote", {}).get("USD", {}).get("market_cap", 0) or 0)
            price = float(coin.get("quote", {}).get("USD", {}).get("price", 0) or 0)
            change_24h = float(coin.get("quote", {}).get("USD", {}).get("percent_change_24h", 0) or 0)
            ts_list.append({
                "rank": coin.get("cmc_rank", 0),
                "name": name,
                "symbol": symbol,
                "market_cap": mcap,
                "price": price,
                "change_24h_pct": change_24h,
            })
            if not top_name:
                top_name = symbol
                top_mcap = mcap

        rec = DataRecord(
            source="coinmarketcap",
            category="coin",
            sub_category="listings",
            timestamp=_now_iso(),
            metrics={
                "top1_symbol": top_name,
                "top1_mcap": top_mcap,
                "coin_count": len(ts_list),
            },
            events=[],
            timeseries=ts_list,
            raw={"source": "pro-api.coinmarketcap.com", "route": "listings"},
        )
        validate_record(rec)
        return [rec]

    def _fetch_fear_greed(self, params: dict) -> list[DataRecord]:
        resp = requests.get(
            f"{_BASE}/v3/fear-and-greed/latest",
            headers=self._headers(),
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json().get("data", {})

        value = int(data.get("value", 0) or 0)
        classification = data.get("value_classification", "")

        rec = DataRecord(
            source="coinmarketcap",
            category="chain",
            sub_category="cmc_fear_greed",
            timestamp=_now_iso(),
            metrics={
                "value": value,
                "classification": classification,
            },
            events=[],
            timeseries=[],
            raw={"source": "pro-api.coinmarketcap.com", "data": data},
        )
        validate_record(rec)
        return [rec]
