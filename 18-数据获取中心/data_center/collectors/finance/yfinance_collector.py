"""YFinance collector — 迁移自 flow_collector.fetch_yahoo_symbol。

用 yfinance 库薄封装替代手写 Yahoo Finance HTTP，产出统一 DataRecord。
覆盖 flow_collector 中 DXY（DX-Y.NYB）、美债收益率（^TNX）等 yahoo 标的。

🆕 Phase A3：新增 stock_info / stock_financials 路由，为 CoinFundamentalRanker
   提供美股基本面数据（PE 比率、利润率、营收增长、ROE 等）。

fail-open：任何异常 → 返回空列表，不阻塞调度器。
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
        route = params.get("route")
        try:
            if route == "stock_info":
                return self._fetch_stock_info(params.get("symbol", ""))
            if route == "stock_financials":
                return self._fetch_stock_financials(params.get("symbol", ""))
            # 默认：原有价格获取逻辑（向后兼容，无 route 参数时）
            return self._fetch_price(params)
        except Exception:
            # fail-open：任何异常 → 空列表
            return []

    # ------------------------------------------------------------------
    # 原有路由：价格获取（向后兼容）
    # ------------------------------------------------------------------
    def _fetch_price(self, params: dict) -> list[DataRecord]:
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

    # ------------------------------------------------------------------
    # 🆕 Phase A3：stock_info 路由
    # ------------------------------------------------------------------
    def _fetch_stock_info(self, symbol: str) -> list[DataRecord]:
        """yf.Ticker(symbol).info → PE / margins / ROE / marketCap / revenueGrowth。

        用于 CoinFundamentalRanker 的 Earnings Stability + PE Mean Reversion +
        Revenue Growth + Profitability Quality 信号。
        """
        if not symbol:
            return []
        tkr = yf.Ticker(symbol)
        info = tkr.info
        if not isinstance(info, dict) or not info:
            return []

        def _num(key: str) -> float:
            v = info.get(key)
            if v is None:
                return 0.0
            try:
                return float(v)
            except (TypeError, ValueError):
                return 0.0

        def _str(key: str) -> str:
            v = info.get(key)
            return str(v) if v is not None else ""

        now = datetime.now(timezone.utc).astimezone().isoformat()
        rec = DataRecord(
            source="yfinance",
            category="finance",
            sub_category=f"stock_info_{symbol}",
            timestamp=now,
            metrics={
                "symbol": symbol,
                "trailingPE": _num("trailingPE"),
                "forwardPE": _num("forwardPE"),
                "operatingMargins": _num("operatingMargins"),
                "returnOnEquity": _num("returnOnEquity"),
                "marketCap": _num("marketCap"),
                "revenueGrowth": _num("revenueGrowth"),
                "longName": _str("longName"),
                "currency": _str("currency"),
            },
            events=[],
            timeseries=[],
            raw={"route": "stock_info", "symbol": symbol},
        )
        validate_record(rec)
        return [rec]

    # ------------------------------------------------------------------
    # 🆕 Phase A3：stock_financials 路由
    # ------------------------------------------------------------------
    def _fetch_stock_financials(self, symbol: str) -> list[DataRecord]:
        """yf.Ticker(symbol).financials → 营收/盈利季度 DataFrame → 时序列。

        用于 CoinFundamentalRanker 的 Earnings Stability 信号（4Q Sharpe）。
        """
        if not symbol:
            return []
        tkr = yf.Ticker(symbol)
        financials = tkr.financials
        if financials is None or financials.empty:
            return []

        # 提取关键行（可能不存在）
        def _row(name: str):
            if name in financials.index:
                return financials.loc[name]
            return None

        revenue_row = _row("Total Revenue")
        net_income_row = _row("Net Income")
        ebitda_row = _row("EBITDA")

        # 按列（季度日期）生成 timeseries
        ts = []
        for col in financials.columns:
            try:
                date_str = str(col.date()) if hasattr(col, "date") else str(col)
            except Exception:
                date_str = str(col)
            entry = {"date": date_str}
            if revenue_row is not None:
                try:
                    entry["revenue"] = float(revenue_row[col])
                except (TypeError, ValueError):
                    entry["revenue"] = 0.0
            else:
                entry["revenue"] = 0.0
            if net_income_row is not None:
                try:
                    entry["net_income"] = float(net_income_row[col])
                except (TypeError, ValueError):
                    entry["net_income"] = 0.0
            else:
                entry["net_income"] = 0.0
            if ebitda_row is not None:
                try:
                    entry["ebitda"] = float(ebitda_row[col])
                except (TypeError, ValueError):
                    entry["ebitda"] = 0.0
            else:
                entry["ebitda"] = 0.0
            ts.append(entry)

        # 列按时间倒序排列（yfinance 默认最新在前），反转使最旧在前
        ts.reverse()

        now = datetime.now(timezone.utc).astimezone().isoformat()
        rec = DataRecord(
            source="yfinance",
            category="finance",
            sub_category=f"stock_financials_{symbol}",
            timestamp=now,
            metrics={
                "symbol": symbol,
                "quarters": len(ts),
                "latest_revenue": ts[-1]["revenue"] if ts else 0.0,
                "latest_net_income": ts[-1]["net_income"] if ts else 0.0,
            },
            events=[],
            timeseries=ts,
            raw={"route": "stock_financials", "symbol": symbol},
        )
        validate_record(rec)
        return [rec]
