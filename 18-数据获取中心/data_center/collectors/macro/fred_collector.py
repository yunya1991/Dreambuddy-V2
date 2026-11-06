"""FRED macro collector — 迁移自 flow_collector.py 的 fetch_fred_* 四序列，并为
易经推理五计庙算扩展：M2/WALCL 联储资产负债表/CPI/PPI/工业产出。

用 fredapi 库薄封装替代手写 HTTP，产出统一 DataRecord。
无 FRED_API_KEY 时降级走 fredgraph.csv 免 Key 端点（2026-11-06 修复：Key 丢失导致 13 个任务静默失败）。
"""
from __future__ import annotations

import os
from datetime import datetime, timezone

import requests
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

    _CSV_BASE = "https://fred.stlouisfed.org/graph/fredgraph.csv"

    def is_available(self) -> bool:
        # fredgraph.csv 免 Key 端点始终可用（2026-11-06）
        return True

    def _fetch_csv(self, series_id: str) -> list:
        """免 Key 降级: fredgraph.csv 端点，返回 [(date_str, value), ...] 全量历史。"""
        resp = requests.get(self._CSV_BASE, params={"id": series_id}, timeout=30)
        resp.raise_for_status()
        lines = resp.text.strip().splitlines()
        if len(lines) < 2:
            return []
        out = []
        for line in lines[1:]:
            parts = line.split(",")
            if len(parts) != 2:
                continue
            date_str, val_str = parts[0].strip(), parts[1].strip()
            if not date_str or val_str in ("", "."):
                continue
            try:
                out.append((date_str, float(val_str)))
            except ValueError:
                continue
        return out

    def fetch(self, params: dict) -> list[DataRecord]:
        """采集 FRED 序列。

        Args:
            params: {"series": "CPIAUCSL", "historical": false}
                    historical=True 时返回全量历史数据点（每月一条 DataRecord），
                    否则只返回最新值（默认行为，向后兼容）。
        """
        series_id = params["series"]
        historical = params.get("historical", False)

        if not self._api_key:
            # 免 Key 降级: fredgraph.csv（全量历史，天然覆盖 historical 模式）
            rows = self._fetch_csv(series_id)
            if not rows:
                return []
            if not historical:
                rows = rows[-1:]  # 默认模式只取最新值（全量历史会触发质量门禁拦截）
            records = []
            for date_str, val in rows:
                if historical:
                    try:
                        from dateutil import parser as _parser
                        dt = _parser.parse(date_str).replace(tzinfo=timezone.utc)
                        ts_iso = dt.isoformat()
                    except Exception:
                        ts_iso = datetime.now(timezone.utc).astimezone().isoformat()
                else:
                    # 默认模式 timestamp 用当前时间，对齐 fredapi 路径（新鲜度门禁友好）
                    ts_iso = datetime.now(timezone.utc).astimezone().isoformat()
                rec = DataRecord(
                    source="fred",
                    category="macro",
                    sub_category=series_id,
                    timestamp=ts_iso,
                    # date 必须进 metrics: stable_id 对 macro 取 sub_category:metrics.date,
                    # 缺 date 会导致全批历史记录同 dedupe_key 被 DUPLICATE_DETECTED 拦截
                    metrics={"value": val, "date": date_str},
                    events=[],
                    timeseries=[],
                    raw={"series_id": series_id, "date": date_str, "value": val, "via": "fredgraph_csv"},
                )
                validate_record(rec)
                records.append(rec)
            return records

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
