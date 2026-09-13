"""Bitcoin ETF Flow 采集器 — farside.co.uk 免费 HTML 表格。

数据源: https://farside.co.uk/bitcoin-etf-flow-all-data/
- 无需 API key，免费
- HTML 表格每日更新，按发行商拆分 ETF 净流入/流出
- 用于 AGI 蓝图 Phase4.3 ETF 资金流信号 + 五维设计 D7

解析策略：
  1. ScraplingEngine static mode 抓取 HTML
  2. Scrapy Selector 解析 <table> 行列
  3. 汇总总净流入 + per-issuer 数据
"""
from __future__ import annotations

from datetime import datetime, timezone

from data_center.collectors._base import BaseCollector
from data_center.core.contract import DataRecord, validate_record

FARSIDE_URL = "https://farside.co.uk/bitcoin-etf-flow-all-data/"


def _now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat()


class EtfFlowCollector(BaseCollector):
    """Bitcoin ETF 每日净流入/流出采集器。"""

    source = "etf_flow"
    category = "finance"

    def is_available(self) -> bool:
        return True  # 免费 HTML 页面

    def fetch(self, params: dict) -> list[DataRecord]:
        url = params.get("url", FARSIDE_URL)
        html = self._fetch_html(url)
        if not html:
            return []
        items = self._parse_html(html)
        if not items:
            return []
        return self._build_records(items)

    def _fetch_html(self, url: str) -> str:
        """用 ScraplingEngine stealthy mode 绕过 Cloudflare 抓取 HTML。"""
        # farside.co.uk 有 Cloudflare 防护，必须用 stealthy mode
        try:
            from data_center.crawler.scrapling_engine import ScraplingEngine
            engine = ScraplingEngine()
            html = engine.fetch_html(url, mode="stealthy")
            if html and len(html) > 1000:
                return html
            # stealthy 失败则回退到 http mode
            html = engine.fetch_html(url, mode="http")
            if html and len(html) > 1000:
                return html
        except Exception:
            pass
        # 最终回退到 requests（大概率被 Cloudflare 拦截，但保留兜底）
        try:
            import requests
            resp = requests.get(url, timeout=20,
                                headers={"User-Agent": "Mozilla/5.0"})
            resp.raise_for_status()
            return resp.text
        except Exception:
            return ""

    def _parse_html(self, html: str) -> list[dict]:
        """解析 farside 表格，返回 per-date ETF flow 列表。"""
        try:
            from scrapy import Selector
        except ImportError:
            return []

        sel = Selector(text=html)
        table = sel.css("table")
        if not table:
            return []

        # 提取表头（发行商名称）— farside 文本嵌套在 <span class="tabletext"> 中
        headers = table.css("th *::text").getall()
        if not headers:
            headers = table.css("th::text").getall()
        # 清理表头
        headers = [h.strip() for h in headers if h.strip()]

        # 提取数据行
        items: list[dict] = []
        for row in table.css("tr"):
            # 用 *::text 捕获嵌套 span 中的文本
            cells_raw = row.css("td")
            if len(cells_raw) < 3:
                continue
            cells = []
            for cell in cells_raw:
                text = "".join(cell.css("*::text").getall()).strip()
                cells.append(text)

            date_str = cells[0]
            if not date_str or date_str.lower() in ("total", "sum"):
                continue

            # 每列对应一个发行商
            flows: dict[str, float] = {}
            for i, val in enumerate(cells[1:], 1):
                header = headers[i] if i < len(headers) else f"col_{i}"
                val = val.strip().replace(",", "")
                try:
                    flows[header] = float(val)
                except (ValueError, TypeError):
                    flows[header] = 0.0

            items.append({"date": date_str, **flows})

        return items

    def _build_records(self, items: list[dict]) -> list[DataRecord]:
        if not items:
            return []

        # 取最近 N 天数据
        recent = items[-30:]
        ts = _now_iso()

        # 最新一天数据作为 metrics
        latest = recent[-1]
        total_flow = sum(v for k, v in latest.items() if k != "date" and isinstance(v, (int, float)))

        # 构建 timeseries
        ts_list = []
        for item in recent:
            daily_total = sum(v for k, v in item.items() if k != "date" and isinstance(v, (int, float)))
            ts_list.append({
                "date": item["date"],
                "total_flow": daily_total,
                **{k: v for k, v in item.items() if k != "date"},
            })

        rec = DataRecord(
            source="etf_flow",
            category="finance",
            sub_category="etf_flow",
            timestamp=ts,
            metrics={
                "latest_date": latest["date"],
                "latest_total_flow_btc": total_flow,
                "total_net_flow": total_flow,  # 下游 query_etf_flow 期望的字段名
                "record_count": len(recent),
            },
            events=[],
            timeseries=ts_list,
            raw={
                "source": "farside.co.uk",
                "latest": latest,
            },
        )
        validate_record(rec)
        return [rec]
