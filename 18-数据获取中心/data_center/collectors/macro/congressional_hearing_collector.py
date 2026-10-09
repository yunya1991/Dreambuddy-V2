"""CongressionalHearingCollector — 国会听证会采集。

SPEC-Phase2 §6.4:
  - 数据源: senate.gov 信贷委员会 + house.gov 金融服务委员会（HTML）
  - direction: 默认 neutral（由内容决定，初版固定 neutral，SPEC §7.3）
  - crypto_related: 标题含 crypto/stablecoin/digital asset 等
  - is_scheduled: True（轨道 A 窗口预演型）
  - FAIL-OPEN: 抓取/解析失败返回空列表

注：senate.gov 有反爬（Access Denied），URL 可通过 config["urls"] 覆盖，
    便于后续接入可用数据源或 RSS/API。
"""
from __future__ import annotations

import logging
import re
from datetime import datetime

from data_center.collectors._base import BaseCollector
from data_center.core.contract import DataRecord, validate_record

logger = logging.getLogger(__name__)


class CongressionalHearingCollector(BaseCollector):
    """国会听证会采集器（加密监管相关）。"""

    source = "congress"
    category = "macro"  # DataRecord 契约合法值（"hearing" 不在 CATEGORIES）

    # 默认数据源（可通过 config["urls"] 覆盖）
    DEFAULT_URLS = [
        "https://www.banking.senate.gov/hearings",
        "https://financialservices.house.gov/calendar/",
    ]

    CRYPTO_KEYWORDS = [
        "crypto", "bitcoin", "ethereum", "stablecoin", "digital asset",
        "digital currency", "token", "blockchain", "defi", "nft",
    ]

    # 月份缩写映射
    _MONTHS = {
        "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
        "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
    }

    def is_available(self) -> bool:
        """公开页面无需 API Key。"""
        return True

    def fetch(self, params: dict) -> list[DataRecord]:
        """
        采集国会听证会，返回 DataRecord 列表。

        params:
            crypto_only: bool — 仅返回加密相关听证会（默认 False）
        """
        try:
            pages = self._fetch_pages()
        except Exception as e:
            logger.warning("CongressionalHearing 抓取失败，FAIL-OPEN: %s", e)
            return []

        if not pages:
            return []

        crypto_only = params.get("crypto_only", False)
        records: list[DataRecord] = []
        ts = datetime.now().astimezone().isoformat()

        for html in pages:
            try:
                hearings = self._parse_hearings(html, source="congress")
            except Exception as e:
                logger.debug("[FO] CongressionalHearing parse fail: %s", e)
                continue

            for h in hearings:
                if crypto_only and not h.get("crypto_related"):
                    continue
                rec = DataRecord(
                    source=self.source,
                    category=self.category,
                    sub_category="congressional_hearing",
                    timestamp=ts,
                    metrics={
                        "event_type": "congressional_hearing",
                        "direction": "neutral",  # SPEC §7.3: 默认 neutral
                        "is_scheduled": True,
                        "date_event": h.get("date", ""),
                        "crypto_related": h.get("crypto_related", False),
                        "title": h.get("title", ""),
                        "committee": h.get("committee", ""),
                    },
                    events=[{
                        "title": h.get("title", ""),
                        "date": h.get("date", ""),
                        "committee": h.get("committee", ""),
                    }],
                    timeseries=[],
                    raw={"html_excerpt": html[:500], "source": h.get("committee", "")},
                )
                validate_record(rec)
                records.append(rec)

        return records

    # ---------------------------------------------------------------- HTML 抓取

    def _fetch_pages(self) -> list[str]:
        """抓取所有配置的 URL，返回 HTML 列表。

        FAIL-OPEN: 单 URL 失败不影响其他 URL。
        """
        urls = self.config.get("urls") if self.config else None
        if not urls:
            urls = self.DEFAULT_URLS

        try:
            import requests
        except ImportError:
            logger.warning("CongressionalHearing: requests 未安装，FAIL-OPEN")
            return []

        pages: list[str] = []
        for url in urls:
            try:
                headers = {
                    "User-Agent": (
                        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                        "AppleWebKit/537.36"
                    )
                }
                resp = requests.get(url, headers=headers, timeout=15)
                if resp.status_code == 200:
                    pages.append(resp.text)
            except Exception as e:
                logger.debug("[FO] CongressionalHearing fetch %s fail: %s", url, e)
                continue
        return pages

    # ---------------------------------------------------------------- HTML 解析

    def _parse_hearings(self, html: str, source: str) -> list[dict]:
        """从 HTML 中提取听证会列表。

        优先用 BeautifulSoup，回退正则。提取 date + title + crypto_related。
        """
        hearings: list[dict] = []
        if not html:
            return hearings

        items = self._extract_hearing_items(html)
        for item in items:
            date_str = self._extract_date(item)
            title = self._extract_title(item)
            if not date_str or not title:
                continue
            normalized_date = self._normalize_date(date_str)
            if not normalized_date:
                continue
            hearings.append({
                "date": normalized_date,
                "title": title.strip(),
                "crypto_related": self._is_crypto_related(title),
                "committee": source,
            })
        return hearings

    @staticmethod
    def _extract_hearing_items(html: str) -> list[str]:
        """提取听证会条目 HTML 片段。

        优先 BeautifulSoup 按 div.hearing-item 切分；回退正则匹配 hearing 块。
        """
        try:
            from bs4 import BeautifulSoup
            soup = BeautifulSoup(html, "html.parser")
            items = soup.select(".hearing-item")
            if items:
                return [str(it) for it in items]
        except ImportError:
            pass

        # 回退：按 hearing-item 类切分
        blocks = re.findall(
            r'<[^>]*class="[^"]*hearing-item[^"]*"[^>]*>.*?</[^>]*>',
            html, re.DOTALL,
        )
        return blocks

    @staticmethod
    def _extract_date(item_html: str) -> str:
        """从条目 HTML 提取日期字符串。"""
        # 优先 hearing-date class
        m = re.search(
            r'<[^>]*class="[^"]*hearing-date[^"]*"[^>]*>([^<]+)<',
            item_html,
        )
        if m:
            return m.group(1).strip()
        # 回退：常见日期格式
        m = re.search(
            r'(\d{4}-\d{2}-\d{2}|'
            r'(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+\d{1,2},?\s*\d{4}|'
            r'(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+\d{1,2}\s+\d{4})',
            item_html, re.IGNORECASE,
        )
        return m.group(1).strip() if m else ""

    @staticmethod
    def _extract_title(item_html: str) -> str:
        """从条目 HTML 提取标题（第一个 <a> 文本）。"""
        m = re.search(r'<a[^>]*>([^<]+)</a>', item_html)
        if m:
            return m.group(1).strip()
        # 回退：去标签后的文本
        text = re.sub(r'<[^>]+>', ' ', item_html)
        text = re.sub(r'\s+', ' ', text).strip()
        return text[:200]

    def _normalize_date(self, date_str: str) -> str:
        """将多种日期格式归一化为 YYYY-MM-DD。"""
        date_str = date_str.strip()
        # ISO 格式
        m = re.match(r'(\d{4})-(\d{2})-(\d{2})', date_str)
        if m:
            return f"{m.group(1)}-{m.group(2)}-{m.group(3)}"
        # "October 15, 2026" / "Oct 15, 2026" / "Oct 15 2026"
        m = re.match(
            r'(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+(\d{1,2}),?\s+(\d{4})',
            date_str, re.IGNORECASE,
        )
        if m:
            month = self._MONTHS[m.group(1).lower()[:3]]
            return f"{m.group(3)}-{month:02d}-{int(m.group(2)):02d}"
        return ""

    def _is_crypto_related(self, title: str) -> bool:
        """标题是否含加密关键词。"""
        lower = title.lower()
        return any(kw in lower for kw in self.CRYPTO_KEYWORDS)
