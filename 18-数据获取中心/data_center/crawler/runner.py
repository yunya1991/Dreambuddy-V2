"""Crawler runner — 统一编排入口。

读 sites.yaml → 按 js_render 分发 static(GenericSpider)/JS(PlaywrightFallback)
→ adapt → DataRecord(category=web)。
"""
from __future__ import annotations

import os

import yaml

from data_center.core.contract import DataRecord
from data_center.crawler.adapters import adapt_items
from data_center.crawler.generic_spider import GenericSpider
from data_center.crawler.playwright_fallback import PlaywrightFallback

_DEFAULT_CONFIG = os.path.join(
    os.path.dirname(__file__), "..", "..", "config", "sites.yaml"
)


class CrawlerRunner:
    """爬虫轨统一入口：读配置 → 分发 → 适配 → DataRecord。"""

    def __init__(self, config_path: str = _DEFAULT_CONFIG):
        self._sites: dict = self._load_config(config_path)
        self._spider = GenericSpider()
        self._pw = PlaywrightFallback()

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
        if site.get("js_render"):
            items = self._pw.fetch_and_parse(site)
        else:
            items = self._spider.fetch_and_parse(site)
        return adapt_items(items, site)

    def list_sites(self) -> list[str]:
        return list(self._sites.keys())
