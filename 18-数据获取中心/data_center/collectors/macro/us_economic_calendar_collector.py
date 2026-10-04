"""UsEconomicCalendarCollector — 美国经济数据 actual/forecast/surprise 采集。

支持指标：CPI（通胀）、NFP（非农就业）、PPI（生产者物价）。
surprise = actual - forecast，正值=超预期鹰派，负值=不及预期鸽派。

数据源（纯爬虫，无需 API Key）：
  Trading Economics 页面 → actual / forecast / previous

FAIL-OPEN：所有异常被捕获，失败时返回空列表。
"""
from __future__ import annotations

import logging
import re
from datetime import datetime, timezone

from data_center.collectors._base import BaseCollector
from data_center.collectors.macro.cesi_history import (
    append_surprise,
    compute_cesi,
    get_surprise_history,
)
from data_center.core.contract import DataRecord, validate_record
from data_center.crawler.scrapling_engine import ScraplingEngine

logger = logging.getLogger(__name__)

# Trading Economics 指标页 URL
_TE_URLS = {
    "cpi": "https://tradingeconomics.com/united-states/inflation-cpi",
    "nfp": "https://tradingeconomics.com/united-states/non-farm-payrolls",
    "ppi": "https://tradingeconomics.com/united-states/producer-prices-change",
}

_engine = ScraplingEngine()


def _parse_number(text: str) -> float | None:
    """从字符串解析数字，如 '3.2%' → 3.2, '256.5' → 256.5。"""
    if not text:
        return None
    text = text.strip().replace(",", "").replace("%", "")
    m = re.search(r"-?[\d.]+", text)
    if m:
        try:
            return float(m.group(0))
        except ValueError:
            return None
    return None


def _fetch_indicator(indicator: str) -> dict:
    """从 Trading Economics 爬取单个指标的 actual/forecast/previous。

    页面结构：表格行包含 Latest、Previous、Forecast 等列。
    """
    url = _TE_URLS.get(indicator)
    if not url:
        return {}

    # Trading Economics 有反爬，用 http 模式（curl_cffi TLS 指纹），降级到 static
    html = _engine.fetch_html(url, mode="http", timeout=30)
    if not html:
        logger.warning("[EconCal] %s 页面返回空: %s", indicator.upper(), url)
        return {}

    try:
        from bs4 import BeautifulSoup

        root = BeautifulSoup(html, "html.parser")

        # Trading Economics 页面结构：
        # 表格 0（Calendar）：Date | GMT | Reference | Actual | Previous
        #   例：['2026-09-11', '12:30 PM', 'Inflation Rate YoY', 'Aug', '3.4%']
        # 表格 1（Components/Related）：Name | Last | Previous | Unit | Reference
        #   例：['CPI', '334.98', '333.92', 'points', 'Aug 2026']

        actual = forecast = previous = None
        release_date = ""

        # 方法1：解析 Calendar 表格（含 Actual 列）
        tables = root.find_all("table")
        for table in tables:
            rows = table.find_all("tr")
            header_cells = [th.get_text(strip=True).lower() for th in rows[0].find_all(["td", "th"])] if rows else []

            # 查找包含 "actual" 列的表格
            if "actual" in " ".join(header_cells):
                # Trading Economics 表格列：
                # Date | GMT | Reference(indicator) | Actual(reference month) | Previous(value%)
                # 实际数值在最后一列（"Previous" 列名误导，实为最新发布值）
                value_col = len(header_cells) - 1  # 最后一列为数值
                # 遍历所有行，取最近一个有数值的历史日期
                today_str = datetime.now().strftime("%Y-%m-%d")
                for row in rows[1:]:  # 跳过表头
                    cells = [td.get_text(strip=True) for td in row.find_all("td")]
                    if len(cells) <= value_col:
                        continue

                    # 第一列是日期（YYYY-MM-DD）
                    date_match = re.search(r"(\d{4}-\d{2}-\d{2})", cells[0])
                    if not date_match:
                        continue
                    row_date = date_match.group(1)

                    # 跳过未来日期（未发布的数据）
                    if row_date > today_str:
                        continue

                    # 最后一列为实际数值
                    val = _parse_number(cells[value_col])
                    if val is not None:
                        actual = val
                        release_date = row_date
                        # Previous 列（倒数第二列）
                        if value_col > 0:
                            prev_val = _parse_number(cells[value_col - 1])
                            if prev_val is not None:
                                previous = prev_val
                        break
                if actual is not None:
                    break

        # 方法2：解析 Components 表格（Last / Previous 列）
        if actual is None:
            for table in tables:
                rows = table.find_all("tr")
                header_cells = [th.get_text(strip=True).lower() for th in rows[0].find_all(["td", "th"])] if rows else []
                if "last" in " ".join(header_cells):
                    last_col = header_cells.index("last") if "last" in header_cells else 1
                    prev_col = header_cells.index("previous") if "previous" in header_cells else 2

                    for row in rows[1:]:
                        cells = [td.get_text(strip=True) for td in row.find_all("td")]
                        if len(cells) > max(last_col, prev_col):
                            # 第一列是指标名称，只取匹配的
                            name = cells[0].lower()
                            if indicator == "cpi" and "inflation rate" not in name and "cpi" not in name:
                                # 取 Inflation Rate YoY 行
                                if "inflation rate" in name:
                                    val = _parse_number(cells[last_col])
                                    if val is not None:
                                        actual = val
                                        previous = _parse_number(cells[prev_col])
                                        break
                            elif indicator in name or name in indicator:
                                val = _parse_number(cells[last_col])
                                if val is not None:
                                    actual = val
                                    previous = _parse_number(cells[prev_col])
                                    break

        # 方法3：从页面文本正则提取
        if actual is None:
            full_text = root.get_text(separator=" ", strip=True)
            # 匹配 "3.40 percent" 或 "3.4%" 格式
            pct_match = re.search(r"([\d.]+)\s*(?:percent|%)", full_text)
            if pct_match:
                actual = float(pct_match.group(1))

        if actual is None:
            logger.warning("[EconCal] %s 未能从页面提取数据", indicator.upper())
            return {}

        # forecast 降级为 previous
        if forecast is None:
            forecast = previous if previous is not None else actual
        if previous is None:
            previous = actual

        return {
            "actual": actual,
            "forecast": forecast,
            "previous": previous,
            "release_date": release_date,
        }

    except Exception as e:
        logger.warning("[EconCal] %s HTML 解析失败: %s", indicator.upper(), e)
        return {}


class UsEconomicCalendarCollector(BaseCollector):
    """美国经济日历采集器（CPI/NFP/PPI actual/forecast/surprise）。"""

    source = "econ_calendar"
    category = "macro"

    SUPPORTED_INDICATORS = ("cpi", "nfp", "ppi")

    def is_available(self) -> bool:
        """不需要 API Key，默认可用。"""
        return True

    def fetch(self, params: dict) -> list[DataRecord]:
        """按 params["indicator"] 采集。

        Args:
            params: {"indicator": "cpi" | "nfp" | "ppi"}
        """
        indicator = params.get("indicator")
        if indicator not in self.SUPPORTED_INDICATORS:
            return []

        try:
            data = _fetch_indicator(indicator)
        except Exception as e:
            logger.warning("%s 采集失败，FAIL-OPEN: %s", indicator, e)
            return []
        if not data:
            return []

        surprise = data["actual"] - data["forecast"]

        # CESI 标准化：Surprise = (Actual - Forecast) / σ_history（SPEC §3.1.3）
        # σ 维护：滚动窗口最近 12 次发布的 surprise 标准差，至少 6 次才能算
        # FAIL-OPEN：CESI 计算失败时 metrics 不含 cesi，下游用 surprise 兜底
        cesi = None
        try:
            history = get_surprise_history(indicator)
            cesi = compute_cesi(data["actual"], data["forecast"], history)
            # 追加到历史，积累 σ 样本（无论 cesi 是否计算成功都追加）
            append_surprise(indicator, surprise)
        except Exception as e:
            logger.warning(
                "[EconCal] %s CESI 计算失败，FAIL-OPEN 跳过: %s",
                indicator.upper(),
                e,
            )
            cesi = None

        metrics = {
            "actual": data["actual"],
            "forecast": data["forecast"],
            "surprise": surprise,
            "previous": data["previous"],
            "release_date": data["release_date"],
        }
        # cesi is not None 时才放入 metrics（契约校验禁止 None）
        if cesi is not None:
            metrics["cesi"] = cesi

        rec = DataRecord(
            source="econ_calendar",
            category="macro",
            sub_category=indicator,
            timestamp=datetime.now(timezone.utc).astimezone().isoformat(),
            metrics=metrics,
            events=[],
            timeseries=[],
            raw=data,
        )
        validate_record(rec)
        return [rec]
