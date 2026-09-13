"""BGeometrics BTC 链上深度指标采集器 — 免费 REST API。

端点：
  GET /mvrv               — MVRV (Market Value to Realized Value)
  GET /sopr               — SOPR (Spent Output Profit Ratio)
  GET /nupl               — NUPL (Net Unrealized Profit/Loss)
  GET /active-addresses   — 活跃地址数
  GET /exchange-netflow    — 交易所净流入/流出
  GET /puell-multiple      — Puell Multiple (矿工收入周期)
  GET /hashribbons         — Hashribbons (矿工投降信号)

用于 AGI 蓝图 L1 数据层 + BDSM E5/E6/E7 信号 + 五维"地"维度。
"""
from __future__ import annotations

import os
from datetime import datetime, timezone

import requests

from data_center.collectors._base import BaseCollector
from data_center.core.contract import DataRecord, validate_record

_BASE = "https://bitcoin-data.com/v1"

# 指标端点 → API 路径映射（free tier 可用，无需 token）
_ENDPOINTS = {
    "mvrv": "/mvrv",
    "sopr": "/sopr",
    "nupl": "/nupl",
    "active_addresses": "/active-addresses",
    "puell_multiple": "/puell-multiple",
    "hashribbons": "/hashribbons",
    "aviv": "/aviv",
    "realized_price": "/realized-price",
    "profit_loss": "/profit-loss",
    "cdd": "/cdd",
    "nvt_ratio": "/nvt-ratio",
}


def _now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat()


class BGeometricsCollector(BaseCollector):
    """BGeometrics BTC 链上深度指标采集器。"""

    source = "bgeometrics"
    category = "chain"

    def __init__(self, config: dict | None = None):
        super().__init__(config)
        self._token: str = (
            self.config.get("token")
            or os.environ.get("BGEOMETRICS_TOKEN", "")
        )

    def is_available(self) -> bool:
        return True  # free tier 无需 token，最近7天数据延迟（v1.7 限制）

    def _headers(self) -> dict:
        if self._token:
            return {"Authorization": f"Bearer {self._token}"}
        return {}

    def fetch(self, params: dict) -> list[DataRecord]:
        metrics_to_fetch = params.get("metrics", "all")
        if metrics_to_fetch == "all":
            # free tier: 8次/小时, 15次/天 → 每次只取 top 3 指标轮换
            # 优先级：MVRV > SOPR > NUPL > Active Addresses > Puell > AVIV
            endpoints = ["mvrv", "sopr", "nupl"]
        elif isinstance(metrics_to_fetch, list):
            endpoints = [m for m in metrics_to_fetch if m in _ENDPOINTS]
        else:
            endpoints = [metrics_to_fetch] if metrics_to_fetch in _ENDPOINTS else []

        if not endpoints:
            return []

        all_metrics: dict[str, float | str] = {}
        all_ts: list[dict] = []
        all_raw: dict = {}

        for name in endpoints:
            data = self._fetch_one(name)
            if data:
                # 检查是否是 rate limit 错误
                if isinstance(data, dict) and "error" in data:
                    continue  # 跳过 rate-limited 端点
                val = self._extract_latest(data)
                if val is not None:
                    all_metrics[name] = val
                all_raw[name] = data
                ts_data = self._extract_timeseries(data, name)
                if ts_data:
                    all_ts.extend(ts_data)

        if not all_metrics:
            return []

        rec = DataRecord(
            source="bgeometrics",
            category="chain",
            sub_category="btc_metrics",
            timestamp=_now_iso(),
            metrics=all_metrics,
            events=[],
            timeseries=all_ts[:100],
            raw={"source": "bitcoin-data.com", **all_raw},
        )
        validate_record(rec)
        return [rec]

    def _fetch_one(self, name: str) -> dict | None:
        path = _ENDPOINTS.get(name)
        if not path:
            return None
        try:
            resp = requests.get(
                f"{_BASE}{path}",
                headers=self._headers(),
                timeout=15,
            )
            resp.raise_for_status()
            return resp.json()
        except Exception:
            return None  # fail-open per metric

    @staticmethod
    def _extract_latest(data: dict | list) -> float | None:
        """从响应中提取最新值。"""
        try:
            if isinstance(data, list) and data:
                return float(data[-1].get("value", 0))
            if isinstance(data, dict):
                # 尝试常见字段名
                for key in ("value", "latest", "current"):
                    if key in data:
                        v = data[key]
                        if isinstance(v, (int, float)):
                            return float(v)
                        if isinstance(v, dict) and "value" in v:
                            return float(v["value"])
                if "data" in data and isinstance(data["data"], list) and data["data"]:
                    return float(data["data"][-1].get("value", 0))
        except (ValueError, TypeError, KeyError):
            pass
        return None

    @staticmethod
    def _extract_timeseries(data: dict | list, name: str) -> list[dict]:
        """从响应中提取时序列。"""
        ts_list: list[dict] = []
        try:
            items = data if isinstance(data, list) else data.get("data", [])
            if isinstance(items, list):
                for item in items[-10:]:  # 最近10条
                    ts_list.append({
                        "metric": name,
                        "date": str(item.get("date", item.get("timestamp", ""))),
                        "value": float(item.get("value", 0)),
                    })
        except (ValueError, TypeError, KeyError):
            pass
        return ts_list
