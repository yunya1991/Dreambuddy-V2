"""YFinance collector — 迁移自 flow_collector.fetch_yahoo_symbol。

用 yfinance 库薄封装替代手写 Yahoo Finance HTTP，产出统一 DataRecord。
覆盖 flow_collector 中 DXY（DX-Y.NYB）、美债收益率（^TNX）等 yahoo 标的。
"""
from __future__ import annotations

from datetime import datetime, timezone

import yfinance as yf

from data_center.collectors._base import BaseCollector
from data_center.core.contract import DataRecord, validate_record


class YFinanceCollector(BaseCollector):
    source = "yfinance"
    category = "finance"

    def fetch(self, params: dict) -> list[DataRecord]:
        symbol = params["symbol"]
        tkr = yf.Ticker(symbol)
        hist = tkr.history(period="5d")
        if hist is None or hist.empty:
            return []

        close = float(hist["Close"].dropna().iloc[-1])
        last_idx = hist.index[-1]
        date = str(last_idx.date() if hasattr(last_idx, "date") else last_idx)
        currency = str(hist.attrs.get("currency", "")) if hasattr(hist, "attrs") else ""

        rec = DataRecord(
            source="yfinance",
            category="finance",
            sub_category=symbol,
            timestamp=datetime.now(timezone.utc).astimezone().isoformat(),
            metrics={"symbol": symbol, "price": close, "currency": currency, "date": date},
            events=[],
            timeseries=[{"date": date, "close": close}],
            raw={"symbol": symbol, "period": "5d"},
        )
        validate_record(rec)
        return [rec]
