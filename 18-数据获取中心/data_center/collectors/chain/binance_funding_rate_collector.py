"""BinanceFundingRateCollector — 资金费率采集器。

数据源: Binance Futures API
  (https://fapi.binance.com/fapi/v1/fundingRate)
  - 免费，无需 API Key
  - 频率: 每 8 小时结算一次（00:00 / 08:00 / 16:00 UTC）
  - 字段: fundingRate, fundingTime

用于基本面 flow 模块的真实资金费率（替代 coinglass 需 key 的方案）。

FAIL-OPEN 铁律: API 异常 → 返回空列表不阻塞，不抛错。
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

import requests

from data_center.collectors._base import BaseCollector
from data_center.core.contract import DataRecord, validate_record

logger = logging.getLogger(__name__)

_API_BASE = "https://fapi.binance.com/fapi/v1"


class BinanceFundingRateCollector(BaseCollector):
    """资金费率采集器（Binance Futures 免费 API）。"""

    source = "binance_futures"
    category = "chain"

    def is_available(self) -> bool:
        return True

    def fetch(self, params: dict) -> list[DataRecord]:
        """采集资金费率。

        Args:
            params: {"symbol": "BTCUSDT", "limit": 5}

        Returns:
            list[DataRecord] — 含 funding_rate_pct / funding_rate_annualized_pct。
        """
        symbol = params.get("symbol", "BTCUSDT")
        limit = params.get("limit", 5)
        try:
            resp = requests.get(
                f"{_API_BASE}/fundingRate",
                params={"symbol": symbol, "limit": limit},
                timeout=15,
            )
            resp.raise_for_status()
            data = resp.json()
            return self._build_records(data, symbol)
        except Exception as e:
            logger.debug("BinanceFundingRateCollector FAIL-OPEN: %s", e)
            return []

    def _build_records(self, data, symbol: str) -> list[DataRecord]:
        recs: list[DataRecord] = []
        if not isinstance(data, list) or not data:
            return recs

        latest = data[-1]
        try:
            rate = float(latest.get("fundingRate", 0.0))
            # 年化 = rate * 3 * 365 * 100 (Binance 每 8h 结算一次)
            annualized = rate * 3 * 365 * 100
            rec = DataRecord(
                source=self.source,
                category=self.category,
                sub_category="funding_rate",
                timestamp=datetime.now(timezone.utc).astimezone().isoformat(),
                metrics={
                    "funding_rate_pct": round(rate * 100, 6),
                    "funding_rate_annualized_pct": round(annualized, 4),
                    "funding_time": int(latest.get("fundingTime", 0)),
                },
                events=[],
                timeseries=[],
                raw={"symbol": symbol, "api_data": data},
            )
            validate_record(rec)
            recs.append(rec)
        except Exception as e:
            logger.debug("BinanceFundingRateCollector _build_records FAIL-OPEN: %s", e)
        return recs
