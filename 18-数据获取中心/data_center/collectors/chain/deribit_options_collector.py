"""Deribit 期权数据采集器 — 免费 public REST API，无需 Key。

端点：
  GET /public/get_book_summary_by_currency?currency=BTC&kind=option
      — BTC/ETH 期权订单摘要（含标记价/标的价格/Greeks/未平仓量）
  GET /public/get_index_price?index_name=btc_usd
      — BTC 指数价格

用于 AGI 蓝图 L1 感知层期权数据（Max Pain / DVOL / Put-Call Ratio）。
"""
from __future__ import annotations

from datetime import datetime, timezone

import requests

from data_center.collectors._base import BaseCollector
from data_center.core.contract import DataRecord, validate_record

_BASE = "https://www.deribit.com/api/v2"


def _now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat()


class DeribitOptionsCollector(BaseCollector):
    """Deribit BTC/ETH 期权数据采集器。"""

    source = "deribit"
    category = "chain"

    def is_available(self) -> bool:
        return True  # public API 无需 Key

    def fetch(self, params: dict) -> list[DataRecord]:
        currency = params.get("currency", "BTC")  # BTC / ETH
        kind = params.get("kind", "option")       # option / future

        try:
            summary = self._get_book_summary(currency, kind)
            index_price = self._get_index_price(currency)
        except Exception:
            return []  # fail-open

        if not summary:
            return []

        # 聚合统计
        total_oi = sum(float(s.get("open_interest", 0)) for s in summary)
        total_volume = sum(float(s.get("volume", 0)) for s in summary)
        call_count = sum(1 for s in summary if "C" in s.get("instrument_name", ""))
        put_count = sum(1 for s in summary if "P" in s.get("instrument_name", ""))
        pc_ratio = put_count / call_count if call_count > 0 else 0.0

        # 找最大未平仓量对应行权价（Max Pain proxy）
        by_strike: dict[str, float] = {}
        for s in summary:
            name = s.get("instrument_name", "")
            # 解析行权价：BTC-28JUN26-75000-C
            parts = name.split("-")
            if len(parts) >= 3:
                strike = parts[-2]
                try:
                    by_strike[strike] = by_strike.get(strike, 0) + float(s.get("open_interest", 0))
                except (ValueError, TypeError):
                    pass

        max_strike = max(by_strike, key=by_strike.get) if by_strike else "0"
        max_pain_oi = by_strike.get(max_strike, 0)

        rec = DataRecord(
            source="deribit",
            category="chain",
            sub_category="options",
            timestamp=_now_iso(),
            metrics={
                "currency": currency,
                "index_price": float(index_price),
                "total_oi": total_oi,
                "total_volume": total_volume,
                "call_count": call_count,
                "put_count": put_count,
                "put_call_ratio": round(pc_ratio, 4),
                "max_pain_strike": str(max_strike),
                "max_pain_oi": max_pain_oi,
                "instrument_count": len(summary),
            },
            events=[],
            timeseries=[
                {"strike": k, "oi": v}
                for k, v in sorted(by_strike.items(), key=lambda x: float(x[0]) if x[0].replace(".", "").isdigit() else 0)
            ][:30],
            raw={
                "source": "deribit.com",
                "currency": currency,
                "index_price": index_price,
            },
        )
        validate_record(rec)
        return [rec]

    def _get_book_summary(self, currency: str, kind: str) -> list[dict]:
        resp = requests.get(
            f"{_BASE}/public/get_book_summary_by_currency",
            params={"currency": currency, "kind": kind},
            timeout=20,
        )
        resp.raise_for_status()
        data = resp.json().get("result", [])
        return data if isinstance(data, list) else []

    def _get_index_price(self, currency: str) -> float:
        index_name = f"{currency.lower()}_usd"
        resp = requests.get(
            f"{_BASE}/public/get_index_price",
            params={"index_name": index_name},
            timeout=15,
        )
        resp.raise_for_status()
        result = resp.json().get("result", {})
        return float(result.get("index_price", 0)) if isinstance(result, dict) else 0.0
