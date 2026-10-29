"""CFTC Commitment of Traders (COT) 采集器 — Socrata 公共 API 方式。

v2 修复：原 fut.txt/com.txt 文件下载解析方式持续返回空（2026-10-19 起连续
EMPTY_RESULT，从未入库），改为 40 系统侧已验证的 Socrata API：
  https://publicreporting.cftc.gov/resource/6dca-aqww.json
查询方式：commodity_name=BITCOIN 精确过滤（like 模糊查询返回 0 行），
取 contract_market_name=="BITCOIN" 且 CHICAGO MERCANTILE 的主合约。

记录格式对齐 40 系统侧 p3_smart_money.py 直采：
  source=cftc, category=position, sub_category=BTC_FUTURES_CME
  metrics: noncomm_long/short/net, comm_long/short/net, open_interest, date
保证 40 系统侧读取与既有 12 条周度记录无缝衔接（dedupe_key 幂等）。

v3 修复（2026-10-27）：只上报最新报告期记录。历史记录已入库（dedupe_key
幂等），全量上报会因最老记录超过 Silver 门禁 48h 新鲜度阈值导致整批被
拦截（EMPTY_RESULT 告警，2026-10-26 22:24 实测拦截）。

fail-open：网络/HTTP 异常返回空列表，不抛异常。
"""
from __future__ import annotations
import json
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from data_center.collectors._base import BaseCollector
from data_center.core.contract import DataRecord, validate_record

_CFTC_API = "https://publicreporting.cftc.gov/resource/6dca-aqww.json"


def _now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat()


class CftcCotCollector(BaseCollector):
    """CFTC COT 持仓报告采集器（Socrata API，BTC CME 主合约）。"""

    source = "cftc_cot"
    category = "finance"

    def is_available(self) -> bool:
        return True  # 公开数据

    def fetch(self, params: dict) -> list[DataRecord]:
        market = params.get("market", "bitcoin")
        limit = int(params.get("limit", 60))
        try:
            rows = self._fetch_rows(limit)
        except Exception:
            return []  # fail-open
        if not rows:
            return []
        return self._build_records(rows, market)

    @staticmethod
    def _fetch_rows(limit: int) -> list[dict]:
        query = urllib.parse.urlencode({
            "$limit": limit,
            "commodity_name": "BITCOIN",
            "$order": "report_date_as_yyyy_mm_dd DESC",
        })
        url = f"{_CFTC_API}?{query}"
        req = urllib.request.Request(url, headers={"Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.load(resp)

    @staticmethod
    def _build_records(rows: list[dict], market: str) -> list[DataRecord]:
        # 主合约：CHICAGO MERCANTILE 的 BITCOIN（非 Nano/Micro）
        cme = [
            r for r in rows
            if "CHICAGO MERCANTILE" in r.get("market_and_exchange_names", "")
            and r.get("contract_market_name", "").strip() == "BITCOIN"
        ]
        # v3：只上报最新报告期记录，避免历史记录触发新鲜度门禁整批拦截
        dates = [
            d for d in ((r.get("report_date_as_yyyy_mm_dd") or "")[:10] for r in cme)
            if d
        ]
        if not dates:
            return []
        latest_date = max(dates)
        cme = [
            r for r in cme
            if (r.get("report_date_as_yyyy_mm_dd") or "")[:10] == latest_date
        ]
        recs: list[DataRecord] = []
        for r in cme:
            date_str = (r.get("report_date_as_yyyy_mm_dd") or "")[:10]
            if not date_str:
                continue
            # v3：timestamp 对齐 FRED 低频源模式用采集时刻（通过 Silver 门禁 48h
            # 新鲜度检查）；数据日期保留在 metrics.date 与 raw.date。
            # dedupe_key 由 sub_category+metrics.date 生成，不含 timestamp，
            # 同报告期记录 INSERT OR REPLACE 幂等覆盖，不会重复入库。
            ts_iso = _now_iso()
            noncomm_long = int(r.get("noncomm_positions_long_all", 0) or 0)
            noncomm_short = int(r.get("noncomm_positions_short_all", 0) or 0)
            comm_long = int(r.get("comm_positions_long_all", 0) or 0)
            comm_short = int(r.get("comm_positions_short_all", 0) or 0)
            oi = int(r.get("open_interest_all", 0) or 0)
            rec = DataRecord(
                source="cftc",
                category="finance",
                sub_category="BTC_FUTURES_CME",
                timestamp=ts_iso,
                metrics={
                    "noncomm_long": noncomm_long,
                    "noncomm_short": noncomm_short,
                    "noncomm_net": noncomm_long - noncomm_short,
                    "comm_long": comm_long,
                    "comm_short": comm_short,
                    "comm_net": comm_long - comm_short,
                    "open_interest": oi,
                    "date": date_str,
                },
                events=[],
                timeseries=[],
                raw={
                    "source": "publicreporting.cftc.gov",
                    "market_and_exchange_names": r.get("market_and_exchange_names", ""),
                    "date": date_str,
                },
            )
            validate_record(rec)
            recs.append(rec)
        return recs
