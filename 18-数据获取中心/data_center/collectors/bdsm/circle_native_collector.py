# -*- coding: utf-8 -*-
"""Circle (USDC/EURC) 原生数据采集器 — 从 circle.com/transparency 爬取储备数据。

页面为 Webflow SSR，数值嵌入在 HTML 的 data-* 属性中（canvas data 属性 + span data-point）。
requests 可直接获取 HTML，无需浏览器渲染。

采集字段（对齐 BDSM E5/E6/E7 + 稳定币监控需求）：
  USDC 储备组成（单位 $B）：
    - usdc_other_bank_deposits_bln: Other Bank Deposits
    - usdc_sii_deposits_bln: Deposits at Systemically Important Institutions
    - usdc_overnight_repo_bln: Overnight Reverse Treasury Repo
    - usdc_treasuries_3m_bln: <3-Month Treasuries
    - usdc_total_reserves_bln: 四项合计
  USDC 发行与赎回（单位 $B）：
    - usdc_issued_7d / usdc_redeemed_7d
    - usdc_issued_30d / usdc_redeemed_30d
    - usdc_issued_365d / usdc_redeemed_365d
  EURC 同理（单位 €M）

FAIL-OPEN: 网络异常/解析失败 → 返回空列表，不抛异常。
"""
from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from typing import Any

import requests

from data_center.collectors._base import BaseCollector
from data_center.core.contract import DataRecord

logger = logging.getLogger("data_center.collectors.bdsm.circle")

_CIRCLE_URL = "https://www.circle.com/transparency"
_HTTP_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}
_HTTP_TIMEOUT = 20


class CircleNativeCollector(BaseCollector):
    """Circle (USDC/EURC) 透明度数据采集器 — 从官网爬取储备组成。"""

    source = "bdsm_circle"
    category = "bdsm"

    def is_available(self) -> bool:
        return True

    def fetch(self, params: dict) -> list[DataRecord]:
        """采集 Circle transparency 数据，返回 DataRecord。"""
        try:
            resp = requests.get(
                _CIRCLE_URL, headers=_HTTP_HEADERS, timeout=_HTTP_TIMEOUT
            )
            resp.raise_for_status()
            html = resp.text
        except Exception as exc:
            logger.warning("Circle transparency fetch failed: %s", exc)
            return []  # FAIL-OPEN

        if not html:
            return []

        return [self._build_record(html)]

    def _build_record(self, html: str) -> DataRecord:
        """从 HTML 提取数据属性，构建 DataRecord。"""
        now = datetime.now(timezone.utc).isoformat()

        # USDC 储备组成（canvas data-* 属性，单位 $B）
        usdc_deposits = self._extract_data_attr(html, "data-usdc-in-circulation")
        usdc_cash = self._extract_data_attr(html, "data-usdc-cash")
        usdc_treasuries = self._extract_data_attr(html, "data-usdc-us-treasuries")
        usdc_months = self._extract_data_attr(html, "data-usdc-months")

        usdc_total_reserves = (
            usdc_deposits + usdc_cash + usdc_treasuries + usdc_months
        )

        # USDC 发行与赎回（span data-point 属性，单位 $B）
        usdc_issued_7d = self._extract_data_point(html, "usdc-issued-7")
        usdc_redeemed_7d = self._extract_data_point(html, "usdc-redeemed-7")
        usdc_issued_30d = self._extract_data_point(html, "usdc-issued-30")
        usdc_redeemed_30d = self._extract_data_point(html, "usdc-redeemed-30")
        usdc_issued_365d = self._extract_data_point(html, "usdc-issued-365")
        usdc_redeemed_365d = self._extract_data_point(html, "usdc-redeemed-365")

        # EURC 数据
        eurc_tokens = self._extract_data_attr(html, "data-eurocoin-tokens")
        eurc_cash = self._extract_data_attr(html, "data-eurocoin-cash")
        eurc_total_reserves = eurc_tokens + eurc_cash

        eurc_in_circulation = self._extract_data_point(html, "euro-in-circulation")
        eurc_issued_7d = self._extract_data_point(html, "euro-issued-7")
        eurc_redeemed_7d = self._extract_data_point(html, "euro-redeemed-7")
        eurc_issued_30d = self._extract_data_point(html, "euro-issued-30")
        eurc_redeemed_30d = self._extract_data_point(html, "euro-redeemed-30")
        eurc_issued_365d = self._extract_data_point(html, "euro-issued-365")
        eurc_redeemed_365d = self._extract_data_point(html, "euro-redeemed-365")

        # 日期
        report_date = ""
        m = re.search(r"As of\s+([A-Z][a-z]+\s+\d{1,2},?\s*\d{4})", html)
        if m:
            report_date = m.group(1)

        # 储备集中度（E7 输入）：最大储备项占比
        reserves = {
            "other_bank_deposits": usdc_deposits,
            "sii_deposits": usdc_cash,
            "overnight_repo": usdc_treasuries,
            "treasuries_3m": usdc_months,
        }
        total = sum(reserves.values())
        max_reserve_pct = max(reserves.values()) / total * 100 if total > 0 else 0.0

        metrics: dict[str, Any] = {
            # USDC 储备组成（$B）
            "usdc_other_bank_deposits_bln": round(usdc_deposits, 2),
            "usdc_sii_deposits_bln": round(usdc_cash, 2),
            "usdc_overnight_repo_bln": round(usdc_treasuries, 2),
            "usdc_treasuries_3m_bln": round(usdc_months, 2),
            "usdc_total_reserves_bln": round(usdc_total_reserves, 2),
            # USDC 发行与赎回（$B）
            "usdc_issued_7d_bln": round(usdc_issued_7d, 2),
            "usdc_redeemed_7d_bln": round(usdc_redeemed_7d, 2),
            "usdc_issued_30d_bln": round(usdc_issued_30d, 2),
            "usdc_redeemed_30d_bln": round(usdc_redeemed_30d, 2),
            "usdc_issued_365d_bln": round(usdc_issued_365d, 2),
            "usdc_redeemed_365d_bln": round(usdc_redeemed_365d, 2),
            # USDC 净变化
            "usdc_net_change_7d_bln": round(usdc_issued_7d - usdc_redeemed_7d, 2),
            "usdc_net_change_30d_bln": round(usdc_issued_30d - usdc_redeemed_30d, 2),
            "usdc_net_change_365d_bln": round(usdc_issued_365d - usdc_redeemed_365d, 2),
            # EURC 数据（€M）
            "eurc_tokens_mln": round(eurc_tokens, 2),
            "eurc_cash_mln": round(eurc_cash, 2),
            "eurc_total_reserves_mln": round(eurc_total_reserves, 2),
            "eurc_in_circulation_mln": round(eurc_in_circulation, 2),
            "eurc_issued_7d_mln": round(eurc_issued_7d, 2),
            "eurc_redeemed_7d_mln": round(eurc_redeemed_7d, 2),
            "eurc_net_change_7d_mln": round(eurc_issued_7d - eurc_redeemed_7d, 2),
            # 储备集中度（E7 输入）
            "max_reserve_pct": round(max_reserve_pct, 2),
            "reserve_diversification_count": sum(1 for v in reserves.values() if v > 0),
            # 年化收入代理（储备利息 ≈ 储备总量 × 假设 5% 年化收益率）
            "annualized_revenue_usd": round(usdc_total_reserves * 1e9 * 0.05, 2),
            "report_date": report_date,
        }

        return DataRecord(
            source=self.source,
            category=self.category,
            sub_category="usdc_transparency",
            timestamp=now,
            metrics=metrics,
            events=[],
            timeseries=[
                {
                    "date": report_date,
                    "usdc_reserves_bln": usdc_total_reserves,
                    "usdc_net_change_7d_bln": usdc_issued_7d - usdc_redeemed_7d,
                    "eurc_reserves_mln": eurc_total_reserves,
                }
            ],
            raw={
                "url": _CIRCLE_URL,
                "html_length": len(html),
                "reserves_breakdown": reserves,
            },
        )

    @staticmethod
    def _extract_data_attr(html: str, attr: str) -> float:
        """提取 canvas 的 data-* 属性值（如 data-usdc-cash="10.46" → 10.46）。"""
        m = re.search(rf'{attr}="([\d.]+)"', html)
        return float(m.group(1)) if m else 0.0

    @staticmethod
    def _extract_data_point(html: str, element_id: str) -> float:
        """提取 span 的 data-point 属性值（如 id="usdc-issued-7" data-point="11.19" → 11.19）。"""
        m = re.search(
            rf'id="{element_id}"[^>]*data-point="([\d.]+)"', html
        )
        if not m:
            m = re.search(
                rf'data-point="([\d.]+)"[^>]*id="{element_id}"', html
            )
        return float(m.group(1)) if m else 0.0


if __name__ == "__main__":
    c = CircleNativeCollector()
    recs = c.fetch({})
    if recs:
        r = recs[0]
        print("metrics:")
        for k, v in r.metrics.items():
            print(f"  {k}: {v}")
    else:
        print("FAIL-OPEN: empty")
