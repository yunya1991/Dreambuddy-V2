"""Google Trends 搜索热度采集器 — 非官方 API，无需 Key。

数据源: https://trends.google.com/trends/api/
- 非官方 JSON API，直接解析返回的 JSON
- 搜索热度 0-100，用于零售 FOMO/恐慌指标
- F&G 组成因子(10%)

解析策略：
  1. 构造 Google Trends探索 API 请求
  2. 解析返回的 JSONP（去掉 )]}' 前缀）
  3. 提取 interest_over_time 数据
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone

import requests

from data_center.collectors._base import BaseCollector
from data_center.core.contract import DataRecord, validate_record

_BASE = "https://trends.google.com/trends/api/daily"


def _now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat()


class GoogleTrendsCollector(BaseCollector):
    """Google Trends 搜索热度采集器。"""

    source = "google_trends"
    category = "chain"

    def is_available(self) -> bool:
        return True  # 非官方 API 无需 Key

    def fetch(self, params: dict) -> list[DataRecord]:
        keyword = params.get("keyword", "buy bitcoin")
        geo = params.get("geo", "")  # 空串=全球
        try:
            data = self._fetch_trends(keyword, geo)
        except Exception:
            return []  # fail-open

        if not data:
            return []

        return self._build_records(data, keyword)

    def _fetch_trends(self, keyword: str, geo: str) -> dict:
        """请求 Google Trends 非官方 API。"""
        params = {
            "hl": "en-US",
            "q": keyword,
            "geo": geo,
            "tz": "0",
        }
        resp = requests.get(_BASE, params=params, timeout=20,
                            headers={"User-Agent": "Mozilla/5.0"})
        resp.raise_for_status()
        text = resp.text
        # 去掉 JSONP 前缀 )]}'  和括号
        text = re.sub(r"^\)\]\}'\s*\n?", "", text)
        # 尝试去掉外层括号
        if text.startswith("("):
            text = text[1:]
        if text.endswith(")"):
            text = text[:-1]
        return json.loads(text)

    def _build_records(self, data: dict, keyword: str) -> list[DataRecord]:
        # 提取 interest_over_time
        default = data.get("default", {})
        timeline = default.get("timelineData", [])
        if not timeline:
            return []

        ts_list: list[dict] = []
        latest_value = 0
        latest_date = ""
        for item in timeline[-30:]:  # 最近30天
            try:
                date_str = item.get("formattedTime", "")
                value = int(item.get("value", [0])[0]) if item.get("value") else 0
                ts_list.append({"date": date_str, "interest": value})
                latest_value = value
                latest_date = date_str
            except (KeyError, ValueError, IndexError, TypeError):
                continue

        if not ts_list:
            return []

        # 计算趋势变化
        if len(ts_list) >= 2:
            prev = ts_list[-2]["interest"]
            curr = ts_list[-1]["interest"]
            change_pct = ((curr - prev) / prev * 100) if prev > 0 else 0
        else:
            change_pct = 0

        rec = DataRecord(
            source="google_trends",
            category="chain",
            sub_category="search_trends",
            timestamp=_now_iso(),
            metrics={
                "keyword": keyword,
                "latest_interest": latest_value,
                "latest_date": latest_date,
                "change_pct": round(change_pct, 2),
                "data_points": len(ts_list),
            },
            events=[],
            timeseries=ts_list,
            raw={"source": "trends.google.com", "keyword": keyword},
        )
        validate_record(rec)
        return [rec]
