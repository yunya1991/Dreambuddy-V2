"""FRED macro collector — 迁移自 flow_collector.py 的 fetch_fred_* 四序列，并为
易经推理五计庙算扩展：M2/WALCL 联储资产负债表/CPI/PPI/工业产出。

用 fredapi 库薄封装替代手写 HTTP，产出统一 DataRecord。
无 FRED_API_KEY 时降级返回空列表，不抛异常（沿用原 flow_collector 无 Key 降级）。
"""
from __future__ import annotations

import os
from datetime import datetime, timezone

from fredapi import Fred

from data_center.collectors._base import BaseCollector
from data_center.core.contract import DataRecord, validate_record
from data_center.core.errors import RateLimitError


class FredCollector(BaseCollector):
    source = "fred"
    category = "macro"

    # 原 flow_collector 4 序列 + 易经推理五维需求新增 5 序列
    # D1：FEDFUNDS 央行利率；D2：M2NS/M2SL M2；D3：WALCL 联储总资产
    # D4：CPIAUCSL CPI；D5：PPIACO PPI；D6：INDPRO 工业产出（美林增长 proxy）
    SERIES = (
        "FEDFUNDS", "RRPONTSYD", "DFII10", "T10YIE",           # 原有
        "M2NS", "M2SL", "WALCL", "CPIAUCSL", "PPIACO", "INDPRO", # 五维需求新增
        "PAYEMS",                                                  # NFP 非农就业
    )

    def __init__(self, config: dict | None = None):
        super().__init__(config)
        self._api_key = (config or {}).get("api_key") or os.environ.get(
            "FRED_API_KEY", ""
        ).strip()

    def is_available(self) -> bool:
        return bool(self._api_key)

    def fetch(self, params: dict) -> list[DataRecord]:
        """采集 FRED 序列。

        Args:
            params: {"series": "CPIAUCSL", "historical": false}
                    historical=True 时返回全量历史数据点（每月一条 DataRecord），
                    否则只返回最新值（默认行为，向后兼容）。
        """
        series_id = params["series"]
        historical = params.get("historical", False)
        if not self.is_available():
            return []

        fred = Fred(api_key=self._api_key)
        try:
            series = fred.get_series(series_id)
        except Exception as e:
            msg = str(e).lower()
            if "429" in msg or "rate" in msg or "limit" in msg:
                raise RateLimitError(f"FRED 限流 {series_id}: {e}") from e
            raise

        series = series.dropna()
        if series.empty:
            return []

        if historical:
            # 全量历史模式：每月一条 DataRecord，timestamp 为数据日期
            records = []
            for ts, val in series.items():
                date_str = str(ts.date() if hasattr(ts, "date") else ts)
                try:
                    dt = ts.to_pydatetime() if hasattr(ts, "to_pydatetime") else None
                    if dt is None:
                        from dateutil import parser as _parser
                        dt = _parser.parse(date_str)
                    ts_iso = dt.replace(tzinfo=timezone.utc).isoformat()
                except Exception:
                    ts_iso = datetime.now(timezone.utc).astimezone().isoformat()

                rec = DataRecord(
                    source="fred",
                    category="macro",
                    sub_category=series_id,
                    timestamp=ts_iso,
                    metrics={"value": float(val)},
                    events=[],
                    timeseries=[],
                    raw={"series_id": series_id, "date": date_str, "value": float(val)},
                )
                validate_record(rec)
                records.append(rec)
            return records

        # 默认模式：只取最新值（向后兼容）
        latest_ts = series.index[-1]
        latest_date = str(latest_ts.date() if hasattr(latest_ts, "date") else latest_ts)
        latest_val = float(series.iloc[-1])

        rec = DataRecord(
            source="fred",
            category="macro",
            sub_category=series_id,
            timestamp=datetime.now(timezone.utc).astimezone().isoformat(),
            metrics={"value": latest_val, "date": latest_date},
            events=[],
            timeseries=[{"date": latest_date, "value": latest_val}],
            raw={
                "series_id": series_id,
                "latest": {"date": latest_date, "value": latest_val},
                "count": int(len(series)),
            },
        )
        validate_record(rec)
        return [rec]
