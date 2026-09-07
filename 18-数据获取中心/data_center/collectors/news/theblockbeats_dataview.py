"""TheBlockBeats DataView 页面直抓采集器（SDK 轨）。

使用 Playwright Chromium headless 渲染 https://www.theblockbeats.info/dataview，
等待 AJAX 完成 + 懒加载触发（总 ~27s），然后把整页 HTML 交给 dataview_html_parser 结构化解析，
最后产出符合 DataRecord 契约的 4 类记录（ECharts卡片元信息 / 市场脉动指数 / 抄底逃顶11信号 / 链上净流入Top10）。

作为 BaseCollector 子类，既可被 Dispatcher 统一调度，也可独立运行。
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from data_center.collectors._base import BaseCollector
from data_center.core.contract import DataRecord


DATAVIEW_URL = "https://www.theblockbeats.info/dataview"


class TheBlockBeatsDataviewCollector(BaseCollector):
    """律动 Dataview 直抓采集器。"""

    source = "theblockbeats_dataview"
    category = "web"  # 多维度混合（DAO/天/地/将/法），子类返回会区分具体 category

    def __init__(self, config: dict | None = None):
        super().__init__(config or {})
        self._render_timeout_ms = int(self.config.get("render_timeout_ms", 70_000))
        self._idle_after_dom_ms = int(self.config.get("idle_after_dom_ms", 22_000))
        self._viewport = self.config.get("viewport", {"width": 1440, "height": 2200})
        self._locale = self.config.get("locale", "zh-CN")
        self._user_agent = self.config.get(
            "user_agent",
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
        )

    # ──────────────────────────────────────────────────────────────────────
    # BaseCollector 接口
    # ──────────────────────────────────────────────────────────────────────
    def is_available(self) -> bool:
        try:
            from playwright.sync_api import sync_playwright  # noqa: F401
            import dataclasses as _  # dataview_html_parser 依赖
            return True
        except Exception:
            return False

    def fetch(self, params: dict | None = None) -> list[DataRecord]:
        """采集一次 dataview 页面，返回 DataRecord 列表。

        params 可选键：
          - url: 覆盖默认 dataview URL
          - html_override: 直接提供 HTML 字符串（调试/测试用，跳过 Playwright）
        """
        params = params or {}
        url = params.get("url", DATAVIEW_URL)

        if "html_override" in params and params["html_override"]:
            html = params["html_override"]
        else:
            html = self._render_with_playwright(url)

        if not html:
            return []

        # 延迟导入：playwright 环境可能没装，只有真正爬的时候才需要
        # dataview_html_parser 与 data_center 目录同级（项目根）
        import sys as _sys
        from pathlib import Path as _Path
        _parent = str(_Path(__file__).resolve().parents[3])  # 18-数据获取中心/
        if _parent not in _sys.path:
            _sys.path.insert(0, _parent)
        from dataview_html_parser import parse, to_records  # type: ignore[import-not-found]

        ts = datetime.now(timezone.utc).astimezone().isoformat()
        data = parse(html)
        return to_records(data, source=self.source, ts=ts)

    # ──────────────────────────────────────────────────────────────────────
    # Playwright 渲染
    # ──────────────────────────────────────────────────────────────────────
    def _render_with_playwright(self, url: str) -> str:
        try:
            from playwright.sync_api import sync_playwright
        except Exception:
            return ""
        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True)
                try:
                    ctx = browser.new_context(
                        viewport=self._viewport,
                        user_agent=self._user_agent,
                        locale=self._locale,
                    )
                    page = ctx.new_page()
                    try:
                        page.goto(url, wait_until="domcontentloaded",
                                  timeout=self._render_timeout_ms)
                    except Exception:
                        # domcontentloaded 超时不致命（律动服务器慢），继续等 AJAX
                        pass
                    page.wait_for_timeout(self._idle_after_dom_ms)
                    # 滚动到底部触发懒加载（净流入榜单通常在页尾）
                    try:
                        page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                        page.wait_for_timeout(4000)
                        page.evaluate("window.scrollTo(0, 0)")
                        page.wait_for_timeout(1500)
                    except Exception:
                        pass
                    html = page.content()
                    return html
                finally:
                    try:
                        browser.close()
                    except Exception:
                        pass
        except Exception:
            return ""


# ──────────────────────────────────────────────────────────────────────────────
#  独立运行入口：python -m data_center.collectors.news.theblockbeats_dataview
# ──────────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":  # pragma: no cover
    import json, sys

    col = TheBlockBeatsDataviewCollector()
    if not col.is_available():
        print("[x] Playwright 未安装，无法运行。请先执行 playwright install chromium")
        sys.exit(1)
    print("[*] 开始采集 theblockbeats dataview (playwright render ~27s)...", flush=True)
    recs = col.fetch()
    print(f"[✓] 采集完成，返回 {len(recs)} 条 DataRecord")
    for r in recs:
        line = json.dumps({
            "source": r.source,
            "category": r.category,
            "sub_category": r.sub_category,
            "metrics": r.metrics,
        }, ensure_ascii=False)
        print("  -", line[:240])
