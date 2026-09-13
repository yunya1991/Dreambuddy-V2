"""ScraplingEngine — 统一抓取引擎，适配 Scrapling 框架。

4 种 mode：
  - static:   原 requests 链路（向后兼容）
  - http:     Scrapling Fetcher（curl_cffi TLS 指纹模拟）
  - dynamic:  Scrapling DynamicFetcher（Playwright JS 渲染）
  - stealthy: Scrapling StealthyFetcher（Patchright + Cloudflare 绕过）

FAIL-OPEN 回退链：stealthy → dynamic → http → static → ""
所有异常被捕获并记录日志，不向上抛出。

lazy import scrapling：未安装时非 static mode 自动降级到 static。
"""
from __future__ import annotations

import logging
import time
from typing import Any

import requests

logger = logging.getLogger("data_center.crawler.scrapling_engine")

# mode 优先级（从高到低），用于回退链
_MODE_PRIORITY = ("stealthy", "dynamic", "http", "static")

# 通用请求超时（秒）
_DEFAULT_TIMEOUT = 30


class ScraplingEngine:
    """统一抓取引擎：按 mode 路由到不同实现，支持 FAIL-OPEN 回退。"""

    def __init__(self, adaptive: bool = False):
        self._adaptive = adaptive
        self._spider = None  # lazy init GenericSpider for static mode parsing

    # ------------------------------------------------------------------
    # 公共接口
    # ------------------------------------------------------------------
    def fetch_html(self, url: str, mode: str = "static", **kwargs) -> str:
        """抓取 URL 并返回 HTML 字符串。

        Args:
            url: 目标 URL
            mode: static | http | dynamic | stealthy
            **kwargs: 透传给底层 fetcher 的参数（timeout, headless, network_idle 等）

        Returns:
            HTML 字符串；所有 mode 均失败时返回空字符串。
        """
        if mode not in _MODE_PRIORITY:
            logger.warning("未知 mode=%r，回退到 static", mode)
            mode = "static"

        # 从请求的 mode 开始，逐级降级
        start_idx = _MODE_PRIORITY.index(mode)
        fallback_chain = _MODE_PRIORITY[start_idx:]

        last_error: Exception | None = None
        for attempt_mode in fallback_chain:
            try:
                html = self._fetch_by_mode(url, attempt_mode, **kwargs)
                if html:
                    if attempt_mode != mode:
                        logger.info(
                            "[ScraplingEngine] mode=%s 回退到 %s 成功 url=%s",
                            mode, attempt_mode, url,
                        )
                    return html
            except Exception as exc:  # noqa: BLE003 — FAIL-OPEN：捕获所有异常
                last_error = exc
                logger.warning(
                    "[ScraplingEngine] mode=%s 失败 url=%s: %s: %s",
                    attempt_mode, url, type(exc).__name__, str(exc)[:120],
                )
                continue

        # 所有 mode 均失败
        logger.error(
            "[ScraplingEngine] 所有 mode 均失败 url=%s last_error=%s: %s",
            url, type(last_error).__name__ if last_error else "None",
            str(last_error)[:120] if last_error else "",
        )
        return ""

    def parse(self, html: str, site: dict) -> list[dict]:
        """从 HTML 提取字段，返回 dict 列表。

        复用 GenericSpider 的解析逻辑。adaptive=True 时尝试 Scrapling 自适应。
        """
        if not html:
            return []

        adaptive = bool(site.get("adaptive", self._adaptive))

        if adaptive:
            return self._parse_adaptive(html, site)
        return self._parse_static(html, site)

    # ------------------------------------------------------------------
    # 各 mode 抓取实现
    # ------------------------------------------------------------------
    def _fetch_by_mode(self, url: str, mode: str, **kwargs) -> str:
        """按 mode 调用对应 fetcher，返回 HTML 字符串。"""
        timeout = kwargs.pop("timeout", _DEFAULT_TIMEOUT)

        if mode == "static":
            return self._fetch_static(url, timeout=timeout)
        elif mode == "http":
            return self._fetch_http(url, timeout=timeout, **kwargs)
        elif mode == "dynamic":
            return self._fetch_dynamic(url, timeout=timeout, **kwargs)
        elif mode == "stealthy":
            return self._fetch_stealthy(url, timeout=timeout, **kwargs)
        return ""

    def _fetch_static(self, url: str, timeout: int) -> str:
        """原 requests 链路（向后兼容）。"""
        resp = requests.get(url, timeout=timeout)
        if resp.status_code != 200:
            return ""
        return resp.text

    def _fetch_http(self, url: str, timeout: int, **kwargs) -> str:
        """Scrapling Fetcher（curl_cffi TLS 指纹模拟）。"""
        Fetcher = self._lazy_import("scrapling.fetchers", "Fetcher")
        if Fetcher is None:
            raise RuntimeError("scrapling not installed")

        page = Fetcher.get(url, timeout=timeout)
        body = getattr(page, "body", None)
        if body is None:
            return ""
        if isinstance(body, bytes):
            return body.decode("utf-8", errors="replace")
        return str(body)

    def _fetch_dynamic(self, url: str, timeout: int, **kwargs) -> str:
        """Scrapling DynamicFetcher（Playwright JS 渲染）。"""
        DynamicFetcher = self._lazy_import("scrapling.fetchers", "DynamicFetcher")
        if DynamicFetcher is None:
            raise RuntimeError("scrapling not installed")

        headless = kwargs.pop("headless", True)
        network_idle = kwargs.pop("network_idle", True)
        page = DynamicFetcher.fetch(
            url, headless=headless, network_idle=network_idle, timeout=timeout,
        )
        body = getattr(page, "body", None)
        if body is None:
            return ""
        if isinstance(body, bytes):
            return body.decode("utf-8", errors="replace")
        return str(body)

    def _fetch_stealthy(self, url: str, timeout: int, **kwargs) -> str:
        """Scrapling StealthyFetcher（Patchright + Cloudflare 绕过）。"""
        StealthyFetcher = self._lazy_import("scrapling.fetchers", "StealthyFetcher")
        if StealthyFetcher is None:
            raise RuntimeError("scrapling not installed")

        headless = kwargs.pop("headless", True)
        network_idle = kwargs.pop("network_idle", True)
        page = StealthyFetcher.fetch(
            url, headless=headless, network_idle=network_idle,
        )
        body = getattr(page, "body", None)
        if body is None:
            return ""
        if isinstance(body, bytes):
            return body.decode("utf-8", errors="replace")
        return str(body)

    # ------------------------------------------------------------------
    # 解析实现
    # ------------------------------------------------------------------
    def _parse_static(self, html: str, site: dict) -> list[dict]:
        """非自适应解析：复用 GenericSpider 逻辑。"""
        spider = self._get_spider()
        return spider.parse(html, site)

    def _parse_adaptive(self, html: str, site: dict) -> list[dict]:
        """自适应解析：用 Scrapling Selector，失败回退到 static 解析。"""
        selectors = site.get("selectors", {})
        item_sel = selectors.get("item")
        if not item_sel:
            return []

        try:
            Selector = self._lazy_import("scrapling", "Selector")
            if Selector is None:
                raise RuntimeError("scrapling not installed")

            # Scrapling Selector 初始化
            sel_type = "xml" if self._is_xml(html) else "html"
            root = Selector(text=html, type=sel_type) if sel_type == "xml" else Selector(text=html)

            items = root.css(item_sel)
            # 自适应：若未命中，尝试 find_similar
            if not items:
                items = root.find_similar(item_sel) if hasattr(root, "find_similar") else []

            if not items:
                return []

            field_selectors = {k: v for k, v in selectors.items() if k != "item"}
            results: list[dict] = []
            for item in items:
                fields = self._extract_fields_scrapling(item, field_selectors)
                if fields:
                    results.append(fields)
            return results
        except Exception as exc:  # noqa: BLE003 — 自适应失败回退到 static
            logger.warning(
                "[ScraplingEngine] adaptive parse 失败，回退 static: %s: %s",
                type(exc).__name__, str(exc)[:120],
            )
            return self._parse_static(html, site)

    def _extract_fields_scrapling(self, item: Any, field_selectors: dict) -> dict:
        """Scrapling Selector 字段提取（与 GenericSpider._extract_fields 逻辑一致）。"""
        fields: dict = {}
        for name, sel in field_selectors.items():
            value = self._extract_one_scrapling(item, sel)
            if value is not None:
                fields[name] = value
        return fields

    def _extract_one_scrapling(self, item: Any, sel: str) -> str | None:
        """按单个选择器提取值（Scrapling Selector API）。"""
        try:
            if sel == "text":
                return item.css("::text").get()
            if sel == "href":
                return item.attrib.get("href")
            return item.css(sel).get()
        except Exception:  # noqa: BLE003
            return None

    # ------------------------------------------------------------------
    # 辅助
    # ------------------------------------------------------------------
    def _get_spider(self):
        """lazy init GenericSpider。"""
        if self._spider is None:
            from data_center.crawler.generic_spider import GenericSpider
            self._spider = GenericSpider()
        return self._spider

    @staticmethod
    def _lazy_import(module: str, attr: str):
        """惰性导入 scrapling，失败返回 None。"""
        try:
            mod = __import__(module, fromlist=[attr])
            return getattr(mod, attr, None)
        except Exception:  # noqa: BLE003
            return None

    @staticmethod
    def _is_xml(text: str) -> bool:
        """检测内容是否为 XML（RSS/Atom）。"""
        stripped = text.lstrip()[:200].lower()
        return stripped.startswith("<?xml") or "<rss" in stripped or "<feed" in stripped
