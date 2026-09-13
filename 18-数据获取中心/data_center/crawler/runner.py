"""Crawler runner — 统一编排入口。

读 sites.yaml → 按 engine 分发：
  - engine=static（或未配置）: 原 GenericSpider(requests) / PlaywrightFallback
  - engine=http/dynamic/stealthy: ScraplingEngine（带 FAIL-OPEN 回退到 static）
→ adapt → DataRecord(category=web)。
"""
from __future__ import annotations

import logging
import os

import yaml

from data_center.core.contract import DataRecord
from data_center.crawler.adapters import adapt_items
from data_center.crawler.generic_spider import GenericSpider
from data_center.crawler.playwright_fallback import PlaywrightFallback
from data_center.crawler.scrapling_engine import ScraplingEngine

logger = logging.getLogger("data_center.crawler.runner")

_DEFAULT_CONFIG = os.path.join(
    os.path.dirname(__file__), "..", "..", "config", "sites.yaml"
)

# engine 为 static 或未配置时走原链路
_LEGACY_ENGINES = {"static", None}


class CrawlerRunner:
    """爬虫轨统一入口：读配置 → 分发 → 适配 → DataRecord。"""

    def __init__(self, config_path: str = _DEFAULT_CONFIG):
        self._sites: dict = self._load_config(config_path)
        self._spider = GenericSpider()
        self._pw = PlaywrightFallback()
        self._scrapling = ScraplingEngine()

    @staticmethod
    def _load_config(path: str) -> dict:
        with open(path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
        return data.get("sites", {}) if data else {}

    def run(self, site_name: str | None = None) -> list[DataRecord]:
        """爬取指定站点；未指定则爬取全部 enabled 站点。"""
        if site_name:
            return self._crawl_site(site_name)
        return self.run_all()

    def run_all(self) -> list[DataRecord]:
        """爬取所有 enabled 站点。"""
        recs: list[DataRecord] = []
        for name in self._sites:
            site = self._sites[name]
            if site.get("enabled", False):
                recs.extend(self._crawl_one(name, site))
        return recs

    def _crawl_site(self, name: str) -> list[DataRecord]:
        site = self._sites.get(name)
        if not site or not site.get("enabled", False):
            return []
        return self._crawl_one(name, site)

    def _crawl_one(self, name: str, site: dict) -> list[DataRecord]:
        engine = site.get("engine")

        # engine=static 或未配置 → 原链路（向后兼容）
        if engine in _LEGACY_ENGINES:
            if site.get("js_render"):
                items = self._pw.fetch_and_parse(site)
            else:
                items = self._spider.fetch_and_parse(site)
            return adapt_items(items, site)

        # engine=http/dynamic/stealthy → ScraplingEngine（带 FAIL-OPEN 回退）
        url = site.get("url")
        if not url:
            return []
        try:
            html = self._scrapling.fetch_html(url, mode=engine)
            items = self._scrapling.parse(html, site)
        except Exception as exc:  # noqa: BLE003 — 双保险：ScraplingEngine 已内部捕获
            logger.warning(
                "[CrawlerRunner] site=%s engine=%s 异常，返回空: %s: %s",
                name, engine, type(exc).__name__, str(exc)[:120],
            )
            items = []
        return adapt_items(items, site)

    def list_sites(self) -> list[str]:
        return list(self._sites.keys())
