"""Gold Supply & Demand collector — World Gold Council 网页爬虫。

数据源: https://www.gold.org/goldhub/research/gold-demand-trends/
- 季度更新（每年 1/4/7/10 月发布上季度报告）
- 从 5 个子页面抓取供需表格：supply / central-banks / investment / jewellery / technology
- XLSX 下载有反爬(403)，改用 BeautifulSoup 解析网页表格

产出字段（单位：吨 tonnes）：
  供应端: total_supply, mine_production, recycled_gold, net_producer_hedging
  需求端: total_demand, jewellery, bar_and_coin, gold_etfs, central_banks, technology
  衍生:   supply_demand_balance(=supply-demand), central_bank_yoy_pct
"""
from __future__ import annotations

import re
from datetime import datetime, timezone

import requests
from bs4 import BeautifulSoup

from data_center.collectors._base import BaseCollector
from data_center.core.contract import DataRecord, validate_record


class GoldSupplyDemandCollector(BaseCollector):
    source = "gold_supply_demand"
    category = "chain"

    BASE_URL = "https://www.gold.org/goldhub/research/gold-demand-trends/gold-demand-trends-q{q}-{y}/"
    SECTIONS = ("supply", "central-banks", "investment", "jewellery", "technology")

    HEADERS = {
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
    }

    def is_available(self) -> bool:
        return True

    def fetch(self, params: dict) -> list[DataRecord]:
        """自动探测最新季度并抓取供需数据。"""
        # 探测最新季度
        quarter, year = self._detect_latest_quarter()
        if quarter is None:
            return []

        # 抓取各 section
        data = {}
        for section in self.SECTIONS:
            section_data = self._fetch_section(quarter, year, section)
            if section_data:
                data[section] = section_data

        if not data:
            return []

        # 汇总关键指标
        metrics = self._aggregate(data, quarter, year)

        rec = DataRecord(
            source="gold_supply_demand",
            category="chain",
            sub_category=f"q{quarter}_{year}",
            timestamp=datetime.now(timezone.utc).astimezone().isoformat(),
            metrics=metrics,
            events=[],
            timeseries=[],
            raw={
                "source": "World Gold Council",
                "quarter": f"Q{quarter} {year}",
                "sections": list(data.keys()),
                "raw_tables": data,
            },
        )
        validate_record(rec)
        return [rec]

    # ------------------------------------------------------------------
    # 探测最新季度
    # ------------------------------------------------------------------
    def _detect_latest_quarter(self) -> tuple[int, int] | tuple[None, None]:
        """从当前季度往前探测，找到 WGC 已发布的最新季度。"""
        now = datetime.now()
        # WGC 通常在季度结束后约 1 个月发布（Q1→4月底, Q2→7月底, Q3→10月底, Q4→1月底）
        candidates = []
        for offset in range(0, 5):
            q = ((now.month - 1) // 3 - offset) % 4 + 1
            y = now.year
            # 处理跨年
            if ((now.month - 1) // 3 - offset) < 0:
                y -= 1
                q = 4 - (abs((now.month - 1) // 3 - offset) - 1)
            candidates.append((q, y))

        for q, y in candidates:
            url = self.BASE_URL.format(q=q, y=y)
            try:
                resp = requests.get(url + "supply", headers=self.HEADERS, timeout=15)
                if resp.status_code == 200 and "Mine production" in resp.text:
                    return (q, y)
            except Exception:
                continue
        return (None, None)

    # ------------------------------------------------------------------
    # 抓取单个 section 的表格
    # ------------------------------------------------------------------
    def _fetch_section(self, quarter: int, year: int, section: str) -> dict:
        url = self.BASE_URL.format(q=quarter, y=year) + section
        try:
            resp = requests.get(url, headers=self.HEADERS, timeout=20)
            resp.raise_for_status()
        except Exception:
            return {}

        soup = BeautifulSoup(resp.text, "html.parser")
        tables = soup.find_all("table")
        if not tables:
            return {}

        # 解析第一个表格（通常是汇总表）
        # 结构: label | Q{q}'{y-1} | Q{q}'{y} | y/y% change
        result = {}
        for table in tables[:1]:
            rows = table.find_all("tr")
            for row in rows:
                cells = [c.get_text(strip=True) for c in row.find_all(["th", "td"])]
                if len(cells) >= 3:
                    label = cells[0].strip()
                    # 取本季度值（第3列，index=2）和上一年同季度值（第2列，index=1）
                    val_curr = self._parse_num(cells[2])
                    val_prev = self._parse_num(cells[1])
                    if label and val_curr is not None:
                        result[label] = val_curr
                        result[f"{label}__prev"] = val_prev
        return result

    # ------------------------------------------------------------------
    # 汇总指标
    # ------------------------------------------------------------------
    def _aggregate(self, data: dict, quarter: int, year: int) -> dict:
        metrics = {"quarter": f"Q{quarter} {year}"}

        supply = data.get("supply", {})
        cb = data.get("central-banks", {})
        inv = data.get("investment", {})
        jew = data.get("jewellery", {})
        tech = data.get("technology", {})

        # 供应端
        metrics["total_supply"] = self._get(supply, "Total supply")
        metrics["mine_production"] = self._get(supply, "Mine production")
        metrics["recycled_gold"] = self._get(supply, "Recycled gold")
        metrics["net_producer_hedging"] = self._get(supply, "Net producer hedging")

        # 需求端各板块
        metrics["jewellery"] = self._get(jew, "World Total")
        metrics["bar_and_coin"] = self._get(inv, "Bar and Coin")
        metrics["gold_etfs"] = self._get(inv, "Gold ETFs")
        metrics["central_banks"] = self._get(cb, "Central Banks") or self._get(cb, "Central Banks andOther")
        metrics["technology"] = self._get(tech, "Technology")

        # 计算总需求（各板块求和，不含 OTC）
        demand_parts = [
            metrics.get("jewellery"),
            metrics.get("bar_and_coin"),
            metrics.get("gold_etfs"),
            metrics.get("central_banks"),
            metrics.get("technology"),
        ]
        valid_demand = [v for v in demand_parts if isinstance(v, (int, float))]
        if valid_demand:
            metrics["total_demand"] = round(sum(valid_demand), 1)
            # 供需平衡（supply - demand，正值=供过于求）
            if isinstance(metrics.get("total_supply"), (int, float)):
                metrics["supply_demand_balance"] = round(
                    metrics["total_supply"] - metrics["total_demand"], 1
                )
                # OTC 及其他 = total_supply - total_demand（供需平衡项，含 OTC 交易）
                metrics["otc_and_other"] = metrics["supply_demand_balance"]

        # 央行购金同比
        cb_curr = metrics.get("central_banks")
        cb_prev = self._get_prev(cb, "Central Banks")
        if isinstance(cb_curr, (int, float)) and isinstance(cb_prev, (int, float)) and cb_prev != 0:
            metrics["central_bank_yoy_pct"] = round(
                (cb_curr - cb_prev) / abs(cb_prev) * 100, 1
            )

        # 金矿产量同比
        mp_curr = metrics.get("mine_production")
        mp_prev = self._get_prev(supply, "Mine production")
        if isinstance(mp_curr, (int, float)) and isinstance(mp_prev, (int, float)) and mp_prev != 0:
            metrics["mine_production_yoy_pct"] = round(
                (mp_curr - mp_prev) / abs(mp_prev) * 100, 1
            )

        return metrics

    @staticmethod
    def _parse_num(s: str) -> float | None:
        """解析 '1,268.9' 或 '-' 为 float。"""
        s = s.strip().replace(",", "").replace("%", "")
        if s in ("", "-", "—", "n/a"):
            return None
        try:
            return float(s)
        except ValueError:
            return None

    @staticmethod
    def _get(d: dict, key: str) -> float | None:
        for k, v in d.items():
            if key.lower() in k.lower() and not k.endswith("__prev"):
                return v
        return None

    @staticmethod
    def _get_prev(d: dict, key: str) -> float | None:
        """取上一年同季度值。"""
        for k, v in d.items():
            if key.lower() in k.lower() and k.endswith("__prev"):
                return v
        return None
