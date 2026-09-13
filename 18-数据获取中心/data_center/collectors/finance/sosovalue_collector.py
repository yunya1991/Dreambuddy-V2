"""SoSoValue ETF 看板采集器 — stealthy 爬虫。

数据源: https://sosovalue.com
- 可视化 ETF 看板，多日趋势图表
- 与 farside ETF flow 交叉验证
- 需 JS 渲染，Cloudflare 可能防护

Scrapling stealthy mode 绕过反爬。
"""
from __future__ import annotations

from datetime import datetime, timezone

from data_center.collectors._base import BaseCollector
from data_center.core.contract import DataRecord, validate_record

SOSO_URL = "https://sosovalue.com/assets/etf/spot-btc-etf"

# SoSoValue ETF 页面 CSS 选择器
_SELECTORS = {
    "item": "table tbody tr, [class*='etf-row']",
    "name": "td:first-child::text, [class*='etf-name']::text",
    "flow": "td:nth-child(2)::text, [class*='flow']::text",
    "aum": "td:nth-child(3)::text, [class*='aum']::text",
    "change": "td:nth-child(4)::text, [class*='change']::text",
}


def _now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat()


class SoSoValueCollector(BaseCollector):
    """SoSoValue ETF 看板采集器。"""

    source = "sosovalue"
    category = "finance"

    def is_available(self) -> bool:
        return True  # stealthy mode

    def fetch(self, params: dict) -> list[DataRecord]:
        url = params.get("url", SOSO_URL)
        try:
            from data_center.crawler.scrapling_engine import ScraplingEngine
            engine = ScraplingEngine()
            html = engine.fetch_html(url, mode="stealthy")
            if not html:
                return []
            site = {"selectors": _SELECTORS, "adaptive": True}
            items = engine.parse(html, site)
        except Exception:
            return []  # fail-open

        if not items:
            return []

        ts = _now_iso()
        # 提取扁平 metrics
        metrics: dict[str, float | str] = {"item_count": len(items)}
        for i, item in enumerate(items[:10]):
            for k, v in item.items():
                metrics_key = f"item_{i}_{k}"
                try:
                    metrics[metrics_key] = float(v) if isinstance(v, (int, float, str)) and str(v).replace(".", "").replace("-", "").isdigit() else str(v)[:100]
                except (ValueError, TypeError):
                    metrics[metrics_key] = str(v)[:100]

        rec = DataRecord(
            source="sosovalue",
            category="finance",
            sub_category="etf_dashboard",
            timestamp=ts,
            metrics=metrics,
            events=[],
            timeseries=[],
            raw={"source": "sosovalue.com", "items": items[:20]},
        )
        validate_record(rec)
        return [rec]
