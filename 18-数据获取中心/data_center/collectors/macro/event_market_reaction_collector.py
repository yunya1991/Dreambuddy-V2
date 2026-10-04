"""EventMarketReactionCollector — 宏观事件前后资产价格快照采集。

在 FOMC/CPI/NFP 等事件发生前后，采集关键资产（黄金/BTC/美元/10Y美债）的价格，
用于分析事件对市场的影响，为"利空出尽"等模式识别提供数据。

支持资产：gold, btc, dxy, us10y
数据源（纯爬虫，无需 API Key）：
  Yahoo Finance quote 页面 → 当前价格
  Yahoo Finance history 页面 → 历史收盘价

FAIL-OPEN：所有异常被捕获，失败时返回空列表。
"""
from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timedelta, timezone

from data_center.collectors._base import BaseCollector
from data_center.core.contract import DataRecord, validate_record
from data_center.crawler.scrapling_engine import ScraplingEngine

logger = logging.getLogger(__name__)

# 资产 → Yahoo Finance 页面 URL
_SYMBOL_URLS = {
    "gold": "https://finance.yahoo.com/quote/GC=F/",
    "btc": "https://finance.yahoo.com/quote/BTC-USD/",
    "dxy": "https://finance.yahoo.com/quote/DX-Y.NYB/",
    "us10y": "https://finance.yahoo.com/quote/%5ETNX/",
}

# Yahoo Finance chart API（返回 JSON，无需认证）
# period1/period2 为 Unix 时间戳
_CHART_API_TEMPLATE = (
    "https://query1.finance.yahoo.com/v8/finance/chart/{ticker}"
    "?period1={p1}&period2={p2}&interval=1d"
)

# 资产 → Yahoo ticker
_TICKER_MAP = {
    "gold": "GC=F",
    "btc": "BTC-USD",
    "dxy": "DX-Y.NYB",
    "us10y": "^TNX",
}

_engine = ScraplingEngine()


def _parse_price_from_html(html: str) -> float | None:
    """从 Yahoo Finance quote 页面 HTML 解析当前价格。

    Yahoo 在页面中嵌入 JSON 数据，包含 "regularMarketPrice" 字段。
    """
    if not html:
        return None

    # 方法1：从内嵌 JSON 中提取 regularMarketPrice
    # Yahoo Finance 页面中有 <script> 标签包含 JSON 数据
    patterns = [
        r'"regularMarketPrice":\s*\{"raw":\s*([\d.]+)',
        r'"regularMarketPrice":\s*([\d.]+)',
        r'data-symbol="[^"]*"[^>]*data-price="([\d.]+)"',
        r'"currentPrice":\s*([\d.]+)',
    ]
    for pattern in patterns:
        m = re.search(pattern, html)
        if m:
            try:
                return float(m.group(1))
            except ValueError:
                continue

    # 方法2：从 HTML 元素中提取（fallback）
    try:
        from bs4 import BeautifulSoup

        root = BeautifulSoup(html, "html.parser")
        # Yahoo Finance 的价格通常在 [data-test="qsp-price"] 或 .fin-streamer
        price_el = root.select_one('[data-test="qsp-price"]')
        if not price_el:
            price_el = root.select_one('[data-field="regularMarketPrice"]')
        if not price_el:
            # 尝试 fin-streamer 标签
            price_el = root.select_one('fin-streamer[data-symbol]')
        if price_el:
            return _parse_number(price_el.get_text(strip=True))
    except Exception:
        pass

    return None


def _parse_number(text: str) -> float | None:
    """从字符串解析数字。"""
    if not text:
        return None
    text = text.strip().replace(",", "").replace("%", "").replace("$", "")
    m = re.search(r"-?[\d.]+", text)
    if m:
        try:
            return float(m.group(0))
        except ValueError:
            return None
    return None


def _fetch_price_data(symbol: str, start_date: str, end_date: str) -> list[dict]:
    """获取资产在指定日期范围内的历史收盘价。

    优先用 Yahoo Finance chart API（JSON），降级用 HTML 爬取。

    Returns:
        [{"date": "YYYY-MM-DD", "close": float}, ...]
    """
    ticker = _TICKER_MAP.get(symbol)
    if not ticker:
        return []

    # 方法1：Yahoo Finance Chart API（JSON，无需认证）
    try:
        dt_start = datetime.strptime(start_date, "%Y-%m-%d")
        dt_end = datetime.strptime(end_date, "%Y-%m-%d")
        p1 = int(dt_start.timestamp())
        p2 = int(dt_end.timestamp())

        url = _CHART_API_TEMPLATE.format(ticker=ticker, p1=p1, p2=p2)
        raw = _engine.fetch_html(url, mode="http", timeout=15)

        if raw:
            data = json.loads(raw)
            result = data.get("chart", {}).get("result")
            if result and isinstance(result, list) and result:
                timestamps = result[0].get("timestamp", [])
                indicators = result[0].get("indicators", {})
                closes = indicators.get("quote", [{}])[0].get("close", [])

                prices = []
                for ts, close in zip(timestamps, closes):
                    if close is not None:
                        dt = datetime.fromtimestamp(ts)
                        prices.append({
                            "date": dt.strftime("%Y-%m-%d"),
                            "close": round(float(close), 4),
                        })
                if prices:
                    return prices
    except (json.JSONDecodeError, KeyError, ValueError, TypeError) as e:
        logger.debug("[Price] Yahoo Chart API 失败 %s: %s", symbol, e)
    except Exception as e:
        logger.debug("[Price] Yahoo Chart API 异常 %s: %s", symbol, e)

    # 方法2：从 quote 页面爬取当前价格（仅返回单日数据）
    try:
        url = _SYMBOL_URLS.get(symbol)
        if not url:
            return []
        html = _engine.fetch_html(url, mode="http", timeout=20)
        price = _parse_price_from_html(html)
        if price is not None:
            return [{"date": datetime.now().strftime("%Y-%m-%d"), "close": price}]
    except Exception as e:
        logger.warning("[Price] HTML 爬取失败 %s: %s", symbol, e)

    return []


class EventMarketReactionCollector(BaseCollector):
    """事件前后价格快照采集器（纯爬虫）。"""

    source = "event_reaction"
    category = "macro"

    SUPPORTED_SYMBOLS = ("gold", "btc", "dxy", "us10y")

    def is_available(self) -> bool:
        return True

    def fetch(self, params: dict) -> list[DataRecord]:
        """采集事件前后价格快照。

        Args:
            params: {
                "symbol": "gold" | "btc" | "dxy" | "us10y",
                "event_date": "YYYY-MM-DD",
                "days_before": int (默认 1),
                "days_after": int (默认 1),
            }
        """
        symbol = params.get("symbol")
        event_date_str = params.get("event_date")

        if symbol not in self.SUPPORTED_SYMBOLS or not event_date_str:
            return []

        days_before = int(params.get("days_before", 1))
        days_after = int(params.get("days_after", 1))

        try:
            event_date = datetime.strptime(event_date_str, "%Y-%m-%d").date()
        except ValueError:
            return []

        start_date = (event_date - timedelta(days=days_before + 3)).strftime("%Y-%m-%d")
        end_date = (event_date + timedelta(days=days_after + 3)).strftime("%Y-%m-%d")

        try:
            prices = _fetch_price_data(symbol, start_date, end_date)
        except Exception as e:
            logger.warning("%s 价格采集失败，FAIL-OPEN: %s", symbol, e)
            return []
        if not prices:
            return []

        # 找到事件日、前一日、后一日的价格
        price_before = None
        price_event = None
        price_after = None

        for p in prices:
            p_date = datetime.strptime(p["date"], "%Y-%m-%d").date()
            if p_date < event_date:
                price_before = p["close"]
            elif p_date == event_date:
                price_event = p["close"]
            elif p_date > event_date and price_after is None:
                price_after = p["close"]

        if price_event is None:
            return []

        # 涨跌幅：事件后 vs 事件日
        change_pct = ((price_after - price_event) / price_event * 100) if price_after else 0.0

        rec = DataRecord(
            source="event_reaction",
            category="macro",
            sub_category=symbol,
            timestamp=datetime.now(timezone.utc).astimezone().isoformat(),
            metrics={
                "event_date": event_date_str,
                "price_before": price_before or 0.0,
                "price_event": price_event,
                "price_after": price_after or 0.0,
                "change_pct": round(change_pct, 4),
            },
            events=[],
            timeseries=prices,
            raw={
                "symbol": symbol,
                "event_date": event_date_str,
                "days_before": days_before,
                "days_after": days_after,
            },
        )
        validate_record(rec)
        return [rec]
