"""CFTC Commitment of Traders (COT) 报告采集器 — 免费公开数据。

数据源: https://cftc.gov/MarketReports/CommitmentsofTraders
- 每周二更新，公开 CSV/HTML 数据
- 700+ 市场，含 BTC 期货
- 用于 AGI 蓝图 L1 约束层机构持仓定位

解析策略：
  1. 下载 COT 历史数据文件 (futures_only.txt)
  2. 解析 BTC 相关行（标记为 "Bitcoin - CME Futures"）
  3. 提取非商业持仓（多头/空头/净持仓）
"""
from __future__ import annotations

import io
import zipfile
from datetime import datetime, timezone

import requests

from data_center.collectors._base import BaseCollector
from data_center.core.contract import DataRecord, validate_record

# COT 历史数据下载（futures only, 含所有市场）
_COT_URL = "https://www.cftc.gov/sites/default/files/files/dea/history/fut.txt"
# 当年数据（可能需要年份调整）
_COT_CURRENT_URL = "https://www.cftc.gov/sites/default/files/files/dea/history/com.txt"


def _now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat()


class CftcCotCollector(BaseCollector):
    """CFTC COT 持仓报告采集器。"""

    source = "cftc_cot"
    category = "finance"

    def is_available(self) -> bool:
        return True  # 公开数据

    def fetch(self, params: dict) -> list[DataRecord]:
        market = params.get("market", "bitcoin")  # 默认 Bitcoin
        try:
            data = self._download_cot()
        except Exception:
            return []  # fail-open

        if not data:
            return []

        rows = self._parse_cot(data, market)
        if not rows:
            return []

        return self._build_records(rows, market)

    def _download_cot(self) -> str:
        """下载 COT futures only 文本数据。"""
        # 尝试当前年数据 + 历史数据
        for url in (_COT_CURRENT_URL, _COT_URL):
            try:
                resp = requests.get(url, timeout=30)
                if resp.status_code == 200:
                    return resp.text
            except Exception:
                continue
        return ""

    @staticmethod
    def _parse_cot(text: str, market: str) -> list[dict]:
        """解析 COT 文本数据，筛选 market 相关行。

        COT 格式：逗号分隔，字段包括：
        Market&Exchange Names, Date, Open Interest,
        Non-Commercial Long, Short, Spreading,
        Commercial Long, Short,
        Non-Reportable Long, Short
        """
        rows: list[dict] = []
        for line in text.strip().split("\n"):
            parts = line.split(",")
            if len(parts) < 9:
                continue
            name = parts[0].strip().lower()
            if market.lower() not in name:
                continue

            try:
                rows.append({
                    "market_name": parts[0].strip(),
                    "date": parts[1].strip(),
                    "open_interest": int(parts[2]) if parts[2].strip().lstrip("-").isdigit() else 0,
                    "non_comm_long": int(parts[3]) if parts[3].strip().lstrip("-").isdigit() else 0,
                    "non_comm_short": int(parts[4]) if parts[4].strip().lstrip("-").isdigit() else 0,
                    "non_comm_spreading": int(parts[5]) if parts[5].strip().lstrip("-").isdigit() else 0,
                    "comm_long": int(parts[6]) if len(parts) > 6 and parts[6].strip().lstrip("-").isdigit() else 0,
                    "comm_short": int(parts[7]) if len(parts) > 7 and parts[7].strip().lstrip("-").isdigit() else 0,
                })
            except (ValueError, IndexError):
                continue

        return rows[-20:]  # 最近20条记录

    def _build_records(self, rows: list[dict], market: str) -> list[DataRecord]:
        ts = _now_iso()
        recs: list[DataRecord] = []

        for row in rows[-5:]:  # 最近5条
            non_comm_long = row["non_comm_long"]
            non_comm_short = row["non_comm_short"]
            net_position = non_comm_long - non_comm_short
            oi = row["open_interest"]

            rec = DataRecord(
                source="cftc_cot",
                category="finance",
                sub_category="cot",
                timestamp=ts,
                metrics={
                    "market": market,
                    "date": row["date"],
                    "open_interest": oi,
                    "non_comm_long": non_comm_long,
                    "non_comm_short": non_comm_short,
                    "non_comm_net": net_position,
                    "non_comm_spreading": row["non_comm_spreading"],
                    "comm_long": row["comm_long"],
                    "comm_short": row["comm_short"],
                    "net_sentiment": "long" if net_position > 0 else "short",
                },
                events=[],
                timeseries=[],
                raw={"source": "cftc.gov", "market": row["market_name"], "date": row["date"]},
            )
            recs.append(rec)

        return recs
