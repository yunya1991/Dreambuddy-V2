"""Crypto Fear & Greed Index collector — alternative.me 免费 API。

数据源: https://api.alternative.me/fng/
- 无需 API key，免费
- limit=0 获取从 2018-02-01 至今的完整历史
- 返回 value(0-100) + value_classification + timestamp

用于战略层天维度情绪评分补充。
"""
from __future__ import annotations

from datetime import datetime, timezone

import requests

from data_center.collectors._base import BaseCollector
from data_center.core.contract import DataRecord, validate_record


class FearGreedCollector(BaseCollector):
    source = "fear_greed"
    category = "chain"

    BASE_URL = "https://api.alternative.me/fng/"

    def is_available(self) -> bool:
        return True  # 免费无 key，永远可用

    def fetch(self, params: dict) -> list[DataRecord]:
        limit = params.get("limit", 0)  # 0 = 全部历史
        try:
            resp = requests.get(
                self.BASE_URL,
                params={"limit": limit, "format": "json"},
                timeout=15,
            )
            resp.raise_for_status()
            data = resp.json()
        except Exception:
            return []  # fail-open

        items = data.get("data", [])
        if not items:
            return []

        # 最新值
        latest = items[0]
        latest_value = int(latest["value"])
        latest_class = latest.get("value_classification", "")
        latest_ts = int(latest["timestamp"])
        latest_date = datetime.fromtimestamp(latest_ts, tz=timezone.utc).strftime("%Y-%m-%d")

        # 构建 timeseries（全部历史，按时间正序）
        ts = []
        for item in reversed(items):
            try:
                ts.append({
                    "date": datetime.fromtimestamp(int(item["timestamp"]), tz=timezone.utc).strftime("%Y-%m-%d"),
                    "value": int(item["value"]),
                    "classification": item.get("value_classification", ""),
                })
            except (KeyError, ValueError, TypeError):
                continue

        rec = DataRecord(
            source="fear_greed",
            category="chain",
            sub_category="crypto_fear_greed",
            timestamp=datetime.now(timezone.utc).astimezone().isoformat(),
            metrics={
                "value": latest_value,
                "classification": latest_class,
                "date": latest_date,
                "count": len(ts),
            },
            events=[],
            timeseries=ts,
            raw={
                "source": "alternative.me",
                "latest": {"date": latest_date, "value": latest_value, "classification": latest_class},
                "count": len(ts),
            },
        )
        validate_record(rec)
        return [rec]
