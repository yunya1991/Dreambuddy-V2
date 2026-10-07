"""LongShortRatioCollector — 多空比采集器。

数据源: Binance Futures API
  (https://fapi.binance.com/futures/data/globalLongShortAccountRatio)
  - 免费
  - 频率: 5min
  - 字段: long_ratio, short_ratio

Spec: docs/superpowers/specs/2026-09-21-washout-detector-design.md §6.2 / §9.3 测试 5

FAIL-OPEN 铁律: API 异常 → 返回空列表不阻塞，不抛错。
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

import requests

from data_center.collectors._base import BaseCollector
from data_center.core.contract import DataRecord, validate_record

logger = logging.getLogger(__name__)

_API_BASE = "https://fapi.binance.com/futures/data"


class LongShortRatioCollector(BaseCollector):
    """多空比采集器（Binance Futures API）。

    采集多空账户比例数据，用于洗盘判定参考指标。
    """

    source = "binance_futures"
    category = "chain"

    def __init__(self, config: dict | None = None):
        super().__init__(config)

    def is_available(self) -> bool:
        """Binance Futures API 免费，始终可用。"""
        return True

    def fetch(self, params: dict) -> list[DataRecord]:
        """采集多空比数据。

        Args:
            params: {"symbol": "BTCUSDT", "period": "5m"}

        Returns:
            list[DataRecord] — 含 long_ratio/short_ratio/long_short_ratio。
            API 异常时返回空列表（FAIL-OPEN）。
        """
        symbol = params.get("symbol", "BTCUSDT")
        period = params.get("period", "5m")
        limit = params.get("limit", 500)
        try:
            resp = requests.get(
                f"{_API_BASE}/globalLongShortAccountRatio",
                params={"symbol": symbol, "period": period, "limit": limit},
                timeout=15,
            )
            resp.raise_for_status()
            data = resp.json()
            return self._build_records(data, symbol)
        except Exception as e:
            logger.debug("LongShortRatioCollector FAIL-OPEN: %s", e)
            return []

    def _build_records(self, data, symbol: str) -> list[DataRecord]:
        """从 API 响应构建 DataRecord 列表。

        Binance 响应格式: [{"timestamp": ..., "longShortRatio": ..., "longAccount": ..., "shortAccount": ...}]
        或 {"code": 200, "data": [...]} 格式。
        每条记录的 timestamp 取 Binance 返回的 timestamp (ms)，确保历史数据不互相覆盖。
        """
        recs: list[DataRecord] = []
        if isinstance(data, dict) and "data" in data:
            items = data.get("data", [])
        elif isinstance(data, list):
            items = data
        else:
            items = []

        if not isinstance(items, list) or not items:
            return recs

        for item in items:
            try:
                lsr = float(item.get("longShortRatio", 0.0))
                ts_ms = int(item.get("timestamp", 0))
                if ts_ms > 0:
                    dt = datetime.fromtimestamp(ts_ms / 1000, tz=timezone.utc)
                    ts_iso = dt.isoformat()
                else:
                    ts_iso = datetime.now(timezone.utc).astimezone().isoformat()
                rec = DataRecord(
                    source=self.source,
                    category=self.category,
                    sub_category=symbol,
                    timestamp=ts_iso,
                    metrics={
                        "long_short_ratio": lsr,
                        "long_ratio": lsr,
                        "short_ratio": float(item.get("shortAccount", 0.0)),
                        "long_account_pct": float(item.get("longAccount", 0.0)) * 100,
                        "short_account_pct": float(item.get("shortAccount", 0.0)) * 100,
                    },
                    events=[],
                    timeseries=[],
                    raw={"symbol": symbol, "api_data": item},
                )
                validate_record(rec)
                recs.append(rec)
            except Exception as e:
                logger.debug("LongShortRatioCollector _build_records FAIL-OPEN: %s", e)
        return recs
