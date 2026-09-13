"""ScraplingEngine 单元测试。

覆盖：
  - 4 种 mode 正常路径（mock scrapling）
  - FAIL-OPEN 回退链
  - lazy import 降级（scrapling 未安装）
  - parse 自适应/非自适应
  - 异常日志记录
"""
from __future__ import annotations

import logging
from unittest.mock import MagicMock, patch

import pytest

from data_center.crawler.scrapling_engine import ScraplingEngine


@pytest.fixture
def engine():
    return ScraplingEngine()


class TestFetchHtmlModes:
    """4 种 mode 正常路径。"""

    def test_static_mode_uses_requests(self, engine):
        """static mode 走 requests，返回 HTML。"""
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = "<html>static</html>"
        with patch("data_center.crawler.scrapling_engine.requests.get", return_value=mock_resp):
            html = engine.fetch_html("http://example.com", mode="static")
        assert html == "<html>static</html>"

    def test_http_mode_uses_scrapling_fetcher(self, engine):
        """http mode 走 Scrapling Fetcher。"""
        mock_page = MagicMock()
        mock_page.body = b"<html>http</html>"
        mock_fetcher = MagicMock()
        mock_fetcher.get.return_value = mock_page
        with patch.dict("sys.modules", {"scrapling": MagicMock(), "scrapling.fetchers": MagicMock(Fetcher=mock_fetcher)}):
            html = engine.fetch_html("http://example.com", mode="http")
        assert html == "<html>http</html>"

    def test_dynamic_mode_uses_dynamic_fetcher(self, engine):
        """dynamic mode 走 Scrapling DynamicFetcher。"""
        mock_page = MagicMock()
        mock_page.body = b"<html>dynamic</html>"
        mock_df = MagicMock()
        mock_df.fetch.return_value = mock_page
        with patch.dict("sys.modules", {"scrapling": MagicMock(), "scrapling.fetchers": MagicMock(DynamicFetcher=mock_df)}):
            html = engine.fetch_html("http://example.com", mode="dynamic")
        assert html == "<html>dynamic</html>"

    def test_stealthy_mode_uses_stealthy_fetcher(self, engine):
        """stealthy mode 走 Scrapling StealthyFetcher。"""
        mock_page = MagicMock()
        mock_page.body = b"<html>stealthy</html>"
        mock_sf = MagicMock()
        mock_sf.fetch.return_value = mock_page
        with patch.dict("sys.modules", {"scrapling": MagicMock(), "scrapling.fetchers": MagicMock(StealthyFetcher=mock_sf)}):
            html = engine.fetch_html("http://example.com", mode="stealthy")
        assert html == "<html>stealthy</html>"

    def test_unknown_mode_falls_back_to_static(self, engine):
        """未知 mode 回退到 static。"""
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = "<html>fallback</html>"
        with patch("data_center.crawler.scrapling_engine.requests.get", return_value=mock_resp):
            html = engine.fetch_html("http://example.com", mode="unknown_mode")
        assert html == "<html>fallback</html>"


class TestFailOpenChain:
    """FAIL-OPEN 回退链。"""

    def test_stealthy_failure_falls_back_to_dynamic(self, engine):
        """stealthy 失败 → dynamic 成功。"""
        mock_page = MagicMock()
        mock_page.body = b"<html>dynamic</html>"
        mock_df = MagicMock()
        mock_df.fetch.return_value = mock_page
        mock_sf = MagicMock()
        mock_sf.fetch.side_effect = RuntimeError("cloudflare block")

        fake_fetchers = MagicMock(DynamicFetcher=mock_df, StealthyFetcher=mock_sf)
        with patch.dict("sys.modules", {"scrapling": MagicMock(), "scrapling.fetchers": fake_fetchers}):
            html = engine.fetch_html("http://example.com", mode="stealthy")
        assert html == "<html>dynamic</html>"

    def test_all_modes_fail_returns_empty(self, engine):
        """所有 mode 失败 → 返回空字符串，不抛异常。"""
        mock_resp = MagicMock()
        mock_resp.status_code = 500  # static 也失败

        # 让所有 scrapling fetcher 抛异常
        mock_sf = MagicMock()
        mock_sf.fetch.side_effect = RuntimeError("blocked")
        mock_df = MagicMock()
        mock_df.fetch.side_effect = RuntimeError("blocked")
        mock_fetcher = MagicMock()
        mock_fetcher.get.side_effect = RuntimeError("blocked")
        fake_fetchers = MagicMock(
            StealthyFetcher=mock_sf, DynamicFetcher=mock_df, Fetcher=mock_fetcher,
        )

        with patch("data_center.crawler.scrapling_engine.requests.get", return_value=mock_resp), \
             patch.dict("sys.modules", {"scrapling": MagicMock(), "scrapling.fetchers": fake_fetchers}):
            html = engine.fetch_html("http://example.com", mode="stealthy")
        assert html == ""

    def test_scrapling_not_installed_falls_back_to_static(self, engine):
        """scrapling 未安装时，非 static mode 降级到 static。"""
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = "<html>static_fallback</html>"
        with patch("data_center.crawler.scrapling_engine.requests.get", return_value=mock_resp), \
             patch.object(engine, "_lazy_import", return_value=None):
            html = engine.fetch_html("http://example.com", mode="http")
        assert html == "<html>static_fallback</html>"


class TestParse:
    """解析方法。"""

    def test_parse_static_reuses_generic_spider(self, engine):
        """非自适应解析复用 GenericSpider。"""
        # item 选中 <a> 标签，href 取自身属性
        html = '<html><body><a class="item" href="/link">title</a></body></html>'
        site = {
            "selectors": {
                "item": ".item",
                "title": "text",
                "link": "href",
            }
        }
        results = engine.parse(html, site)
        assert len(results) == 1
        assert results[0]["title"] == "title"
        assert results[0]["link"] == "/link"

    def test_parse_empty_html_returns_empty(self, engine):
        """空 HTML 返回空列表。"""
        assert engine.parse("", {}) == []

    def test_parse_adaptive_falls_back_on_failure(self, engine):
        """自适应解析失败回退到 static。"""
        html = '<html><body><div class="item"><a href="/link">title</a></div></body></html>'
        site = {
            "adaptive": True,
            "selectors": {
                "item": ".item",
                "title": "text",
                "link": "href",
            }
        }
        # scrapling 未安装 → adaptive 失败 → 回退 static
        with patch.dict("sys.modules", {}):
            results = engine.parse(html, site)
        assert len(results) == 1
        assert results[0]["title"] == "title"


class TestLogging:
    """日志记录。"""

    def test_failure_is_logged(self, engine, caplog):
        """mode 失败时记录 warning 日志。"""
        mock_resp = MagicMock()
        mock_resp.status_code = 500
        # 让所有 scrapling fetcher 抛异常，触发回退链日志
        mock_sf = MagicMock()
        mock_sf.fetch.side_effect = RuntimeError("blocked")
        mock_df = MagicMock()
        mock_df.fetch.side_effect = RuntimeError("blocked")
        mock_fetcher = MagicMock()
        mock_fetcher.get.side_effect = RuntimeError("blocked")

        def fake_lazy_import(module, attr):
            if attr == "StealthyFetcher":
                return mock_sf
            if attr == "DynamicFetcher":
                return mock_df
            if attr == "Fetcher":
                return mock_fetcher
            return None

        with caplog.at_level(logging.WARNING, logger="data_center.crawler.scrapling_engine"):
            with patch("data_center.crawler.scrapling_engine.requests.get", return_value=mock_resp), \
                 patch.object(engine, "_lazy_import", side_effect=fake_lazy_import):
                engine.fetch_html("http://example.com", mode="stealthy")
        assert any("失败" in rec.message for rec in caplog.records)
