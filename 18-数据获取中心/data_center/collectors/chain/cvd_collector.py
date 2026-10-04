"""CvdCollector — Cumulative Volume Delta 采集器。

数据源: CoinGlass V4 API (https://open-api-v4.coinglass.com/api/futures/cvd-history)
  - 需 API key (COINGLASS_API_KEY / CG_API_KEY)
  - 频率: 5min
  - 字段: cvd_value, buy_volume, sell_volume

Spec: docs/superpowers/specs/2026-09-21-washout-detector-design.md §6.2 / §9.3 测试 1-2

FAIL-OPEN 铁律: API 异常 → 返回空列表不阻塞，不抛错。
"""
from __future__ import annotations

import logging
import os
from datetime import datetime, timezone

import requests

from data_center.collectors._base import BaseCollector
from data_center.core.contract import DataRecord, validate_record

logger = logging.getLogger(__name__)

_API_BASE = "https://open-api-v4.coinglass.com/api/futures"


class CvdCollector(BaseCollector):
    """Cumulative Volume Delta 采集器（CoinGlass V4 API）。

    采集 CVD（累计成交量差）数据，用于洗盘判定 F11 cvd_price_divergence。
    """

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
        """有 API Key 走 API，无 Key 也可尝试（FAIL-OPEN）。"""
        return True

    def fetch(self, params: dict) -> list[DataRecord]:
        """采集 CVD 数据。

        Args:
            params: {"symbol": "BTC", "interval": "5min"}

        Returns:
            list[DataRecord] — 含 cvd_value/buy_volume/sell_volume。
            API 异常时返回空列表（FAIL-OPEN）。
        """
        symbol = params.get("symbol", "BTC")
        interval = params.get("interval", "5min")
        try:
            headers = {"accept": "application/json", "CG-API-KEY": self._api_key}
            resp = requests.get(
                f"{_API_BASE}/cvd-history",
                headers=headers,
                params={"symbol": symbol, "interval": interval, "limit": 1},
                timeout=15,
            )
            resp.raise_for_status()
            data = resp.json()
            return self._build_records(data, symbol)
        except Exception as e:
            logger.debug("CvdCollector FAIL-OPEN: %s", e)
            return []

    def _build_records(self, data: dict, symbol: str) -> list[DataRecord]:
        """从 API 响应构建 DataRecord 列表。"""
        recs: list[DataRecord] = []
        items = data.get("data", [])
        if not isinstance(items, list) or not items:
            return recs
        item = items[-1]  # 最新一条
        try:
            rec = DataRecord(
                source=self.source,
                category=self.category,
                sub_category=symbol,
                timestamp=datetime.now(timezone.utc).astimezone().isoformat(),
                metrics={
                    "cvd_value": float(item.get("c", 0.0)),
                    "buy_volume": float(item.get("b", 0.0)),
                    "sell_volume": float(item.get("s", 0.0)),
                },
                events=[],
                timeseries=[],
                raw={"symbol": symbol, "api_data": data},
            )
            validate_record(rec)
            recs.append(rec)
        except Exception as e:
            logger.debug("CvdCollector _build_records FAIL-OPEN: %s", e)
        return recs
