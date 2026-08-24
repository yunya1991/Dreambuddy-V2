"""爬虫轨 — Scrapy Selector + Playwright 覆盖无 API 的官网/新闻站。

对外入口：from data_center.crawler import CrawlerRunner
"""
from data_center.crawler.runner import CrawlerRunner

__all__ = ["CrawlerRunner"]
