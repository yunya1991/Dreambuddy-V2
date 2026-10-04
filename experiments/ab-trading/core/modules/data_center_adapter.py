"""
数据采集中心适配器 (DataCenterClient)

位置: experiments/ab-trading/core/modules/data_center_adapter.py

对接 18-数据获取中心/data_center.db，为 F 链模块提供基本面数据源。
替代 FundamentalAPIClient 的 HTTP 调用，改为本地 SQLite 查询。

数据源映射:
- F1 新闻: gdelt (news, bitcoin crypto) + odaily_newsflash
- F2 资金流: coinglass (funding_rate) + deribit (options OI) + panewslab (etf_institutional)
- F3 情绪: fear_greed (crypto_fear_greed) + fear_greed_enhanced
- F4 链上: mempool (btc_onchain) + blockchain_info (btc_basics) + panewslab (cycle_signals) + theblockbeats (bottom_signal_di)
- F5 宏观: fred (CPI/PPI/M2/FEDFUNDS) + yfinance (^VIX/SPY/GLD) + econ_calendar

FAIL-OPEN: 查询失败返回 None 或默认值，不阻断调用方。
"""

import json
import sqlite3
import os
from pathlib import Path
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field


# ============================================================
# 数据路径解析
# ============================================================

def _resolve_db_path() -> Optional[str]:
    """解析 data_center.db 路径 (FAIL-OPEN)"""
    here = os.path.dirname(os.path.abspath(__file__))
    # experiments/ab-trading/core/modules/ → dreambuddy-v2/18-数据获取中心/data_center.db
    candidates = [
        os.path.join(here, "..", "..", "..", "..", "18-数据获取中心", "data_center.db"),
        os.path.join(here, "..", "..", "..", "..", "..", "18-数据获取中心", "data_center.db"),
    ]
    for p in candidates:
        ap = os.path.abspath(p)
        if os.path.isfile(ap):
            return ap
    return None


_DB_PATH = _resolve_db_path()


# ============================================================
# 数据结构
# ============================================================

@dataclass
class FearGreedData:
    """恐贪指数数据"""
    value: float = 50.0
    label: str = "NEUTRAL"
    momentum: Optional[float] = None
    volatility: Optional[float] = None
    funding: Optional[float] = None
    capital_flow: Optional[float] = None


@dataclass
class NewsItem:
    """新闻条目"""
    title: str = ""
    url: str = ""
    source_domain: str = ""
    source_country: str = ""
    event_type: str = ""
    sentiment: float = 0.5  # 0-1
    is_important: bool = False
    tickers_hit: str = ""


@dataclass
class FundFlowData:
    """资金流数据"""
    funding_rate: float = 0.0
    options_oi: float = 0.0
    btc_etf_aum: float = 0.0
    btc_etf_daily_flow: float = 0.0
    eth_etf_aum: float = 0.0
    eth_etf_daily_flow: float = 0.0
    etf_stale: bool = True


@dataclass
class OnchainData:
    """链上数据"""
    difficulty: float = 0.0
    hashrate: float = 0.0
    total_btc: float = 0.0
    market_cap_usd: float = 0.0
    mempool_count: float = 0.0
    tip_height: float = 0.0
    difficulty_progress_pct: float = 0.0
    # 周期信号
    cycle_hit_ratio: Optional[float] = None
    mvrv_value: Optional[float] = None
    puell_multiple: Optional[float] = None
    # 底部信号
    bottom_signal_score: Optional[float] = None
    bottom_signal_status: str = ""


@dataclass
class MacroData:
    """宏观数据"""
    vix: Optional[float] = None
    spy_price: Optional[float] = None
    gld_price: Optional[float] = None
    dollar_index: Optional[float] = None
    cpi: Optional[float] = None
    ppi: Optional[float] = None
    fed_funds_rate: Optional[float] = None
    m2: Optional[float] = None
    industrial_production: Optional[float] = None
    treasury_yield_10y_2y: Optional[float] = None
    fed_balance_sheet: Optional[float] = None


# ============================================================
# DataCenterClient
# ============================================================

class DataCenterClient:
    """
    数据采集中心客户端

    直接查询 18-数据获取中心/data_center.db，为 F 链模块提供数据。
    FAIL-OPEN: DB 不可用时所有方法返回默认值。
    """

    def __init__(self, db_path: str = None):
        self.db_path = db_path or _DB_PATH
        self._available = self.db_path is not None and os.path.isfile(self.db_path)
        if self._available:
            print(f"[DataCenter] DB connected: {self.db_path}")
        else:
            print("[DataCenter] DB not found (FAIL-OPEN)")

    def is_available(self) -> bool:
        return self._available

    def _query_latest(self, source: str, sub_category: str = None, category: str = None) -> Optional[Dict]:
        """查询最新一条记录 (FAIL-OPEN)"""
        if not self._available:
            return None
        try:
            conn = sqlite3.connect(self.db_path)
            conn.row_factory = sqlite3.Row
            sql = "SELECT * FROM records WHERE source=?"
            params: List[Any] = [source]
            if sub_category:
                sql += " AND sub_category=?"
                params.append(sub_category)
            if category:
                sql += " AND category=?"
                params.append(category)
            sql += " ORDER BY id DESC LIMIT 1"
            row = conn.execute(sql, params).fetchone()
            conn.close()
            return dict(row) if row else None
        except Exception as e:
            print(f"[DataCenter] query error ({source}): {e}")
            return None

    def _query_latest_n(self, source: str, n: int, sub_category: str = None) -> List[Dict]:
        """查询最新 N 条记录 (FAIL-OPEN)"""
        if not self._available:
            return []
        try:
            conn = sqlite3.connect(self.db_path)
            conn.row_factory = sqlite3.Row
            sql = "SELECT * FROM records WHERE source=?"
            params: List[Any] = [source]
            if sub_category:
                sql += " AND sub_category=?"
                params.append(sub_category)
            sql += " ORDER BY id DESC LIMIT ?"
            params.append(n)
            rows = conn.execute(sql, params).fetchall()
            conn.close()
            return [dict(r) for r in rows]
        except Exception as e:
            print(f"[DataCenter] query error ({source}): {e}")
            return []

    @staticmethod
    def _parse_json(field_val: str) -> Dict:
        """安全解析 JSON 字段"""
        if not field_val:
            return {}
        try:
            return json.loads(field_val) if isinstance(field_val, str) else (field_val or {})
        except Exception:
            return {}

    # ============================================================
    # F1 新闻
    # ============================================================

    def get_news(self, limit: int = 10) -> List[NewsItem]:
        """获取最新新闻 (gdelt + odaily_newsflash)"""
        items: List[NewsItem] = []

        # odaily 快讯 (含情绪标签)
        odaily_rows = self._query_latest_n("odaily_newsflash", limit)
        for r in odaily_rows:
            m = self._parse_json(r.get("metrics"))
            items.append(NewsItem(
                title=m.get("od_title_hash", ""),
                source_domain="odaily",
                event_type=m.get("od_event_type", ""),
                sentiment=float(m.get("od_policy_sentiment_0_1", 0.5)),
                is_important=str(m.get("od_is_important", "")).lower() == "true",
                tickers_hit=m.get("od_tickers_hit_csl", ""),
            ))

        # gdelt 新闻
        gdelt_rows = self._query_latest_n("gdelt", max(0, limit - len(items)))
        for r in gdelt_rows:
            m = self._parse_json(r.get("metrics"))
            items.append(NewsItem(
                title="",
                url=m.get("url", ""),
                source_domain=m.get("domain", ""),
                source_country=m.get("sourcecountry", ""),
                sentiment=0.5,  # gdelt 无情绪标签
            ))

        return items[:limit]

    # ============================================================
    # F2 资金流
    # ============================================================

    def get_fund_flow(self) -> FundFlowData:
        """获取资金流数据 (coinglass + deribit + panewslab etf)"""
        data = FundFlowData()

        # deribit 期权 OI
        deribit = self._query_latest("deribit", sub_category="options")
        if deribit:
            m = self._parse_json(deribit.get("metrics"))
            data.options_oi = float(m.get("oi", 0.0))

        # panewslab ETF
        etf = self._query_latest("panewslab", sub_category="etf_institutional")
        if etf:
            m = self._parse_json(etf.get("metrics"))
            data.btc_etf_aum = float(m.get("btc_etf_total_aum_usd", 0.0))
            data.btc_etf_daily_flow = float(m.get("btc_etf_daily_flow_usd", 0.0))
            data.eth_etf_aum = float(m.get("eth_etf_total_aum_usd", 0.0))
            data.eth_etf_daily_flow = float(m.get("eth_etf_daily_flow_usd", 0.0))
            data.etf_stale = bool(m.get("etf_stale", True))

        # 注: coinglass funding_rate 在 DB 中只有 item_count，实际费率需从 mkt 获取
        # funding_rate 由调用方从 mkt 传入

        return data

    # ============================================================
    # F3 情绪
    # ============================================================

    def get_fear_greed(self) -> FearGreedData:
        """获取恐贪指数 + 增强维度"""
        data = FearGreedData()

        # 基础恐贪指数
        fg = self._query_latest("fear_greed", sub_category="crypto_fear_greed")
        if fg:
            m = self._parse_json(fg.get("metrics"))
            data.value = float(m.get("value", 50.0))
            if data.value > 75:
                data.label = "GREED"
            elif data.value > 55:
                data.label = "GREED"
            elif data.value < 25:
                data.label = "FEAR"
            elif data.value < 45:
                data.label = "FEAR"
            else:
                data.label = "NEUTRAL"

        # 增强维度
        fg_enh = self._query_latest("fear_greed_enhanced", sub_category="fear_greed_enhanced")
        if fg_enh:
            m = self._parse_json(fg_enh.get("metrics"))
            data.momentum = float(m.get("momentum", 0.0)) if m.get("momentum") is not None else None
            data.volatility = float(m.get("volatility", 0.0)) if m.get("volatility") is not None else None
            data.funding = float(m.get("funding", 0.0)) if m.get("funding") is not None else None
            data.capital_flow = float(m.get("capital_flow", 0.0)) if m.get("capital_flow") is not None else None

        return data

    # ============================================================
    # F4 链上
    # ============================================================

    def get_onchain(self) -> OnchainData:
        """获取链上数据 (mempool + blockchain_info + panewslab cycle + theblockbeats)"""
        data = OnchainData()

        # mempool 链上基础
        mempool = self._query_latest("mempool", sub_category="btc_onchain")
        if mempool:
            m = self._parse_json(mempool.get("metrics"))
            data.difficulty_progress_pct = float(m.get("difficulty_progress_pct", 0.0))
            data.mempool_count = float(m.get("mempool_count", 0.0))
            data.tip_height = float(m.get("tip_height", 0.0))

        # blockchain_info
        bi = self._query_latest("blockchain_info", sub_category="btc_basics")
        if bi:
            m = self._parse_json(bi.get("metrics"))
            data.market_cap_usd = float(m.get("market_cap_usd", 0.0))
            data.total_btc = float(m.get("total_btc", 0.0))

        # panewslab 周期信号
        cycle = self._query_latest("panewslab", sub_category="cycle_signals")
        if cycle:
            m = self._parse_json(cycle.get("metrics"))
            data.cycle_hit_ratio = float(m.get("bottom_hit_ratio_pct", 0.0)) if m.get("bottom_hit_ratio_pct") is not None else None
            data.mvrv_value = float(m.get("bottom_mvrv_value", 0.0)) if m.get("bottom_mvrv_value") is not None else None
            data.puell_multiple = float(m.get("bottom_puell-multiple_value", 0.0)) if m.get("bottom_puell-multiple_value") is not None else None

        # theblockbeats 底部信号
        bottom = self._query_latest("theblockbeats_dataview", sub_category="bottom_signal_di")
        if bottom:
            m = self._parse_json(bottom.get("metrics"))
            data.bottom_signal_score = float(m.get("score", 0.0)) if m.get("score") is not None else None
            data.bottom_signal_status = str(m.get("status", ""))

        return data

    # ============================================================
    # F5 宏观
    # ============================================================

    def get_macro(self) -> MacroData:
        """获取宏观数据 (fred + yfinance + econ_calendar)"""
        data = MacroData()

        # yfinance ^VIX (timeseries 字段含 close)
        vix = self._query_latest("yfinance", sub_category="^VIX")
        if vix:
            ts = self._parse_json(vix.get("timeseries"))
            if isinstance(ts, list) and ts:
                last = ts[-1] if isinstance(ts[-1], dict) else {}
                data.vix = float(last.get("close", 0.0)) if last.get("close") is not None else None

        # yfinance SPY
        spy = self._query_latest("yfinance", sub_category="SPY")
        if spy:
            m = self._parse_json(spy.get("metrics"))
            data.spy_price = float(m.get("price", 0.0)) if m.get("price") is not None else None

        # yfinance GLD
        gld = self._query_latest("yfinance", sub_category="GLD")
        if gld:
            m = self._parse_json(gld.get("metrics"))
            data.gld_price = float(m.get("price", 0.0)) if m.get("price") is not None else None

        # yfinance 美元指数
        dxy = self._query_latest("yfinance", sub_category="DX-Y.NYB")
        if dxy:
            m = self._parse_json(dxy.get("metrics"))
            data.dollar_index = float(m.get("price", 0.0)) if m.get("price") is not None else None

        # fred CPI
        cpi = self._query_latest("fred", sub_category="CPIAUCSL")
        if cpi:
            m = self._parse_json(cpi.get("metrics"))
            data.cpi = float(m.get("value", 0.0)) if m.get("value") is not None else None

        # fred PPI
        ppi = self._query_latest("fred", sub_category="PPIACO")
        if ppi:
            m = self._parse_json(ppi.get("metrics"))
            data.ppi = float(m.get("value", 0.0)) if m.get("value") is not None else None

        # fred 联邦基金利率
        ff = self._query_latest("fred", sub_category="FEDFUNDS")
        if ff:
            m = self._parse_json(ff.get("metrics"))
            data.fed_funds_rate = float(m.get("value", 0.0)) if m.get("value") is not None else None

        # fred M2
        m2 = self._query_latest("fred", sub_category="M2SL")
        if m2:
            m = self._parse_json(m2.get("metrics"))
            data.m2 = float(m.get("value", 0.0)) if m.get("value") is not None else None

        # fred 工业产出
        ip = self._query_latest("fred", sub_category="INDPRO")
        if ip:
            m = self._parse_json(ip.get("metrics"))
            data.industrial_production = float(m.get("value", 0.0)) if m.get("value") is not None else None

        # fred 10年-2年国债利差
        t10y2y = self._query_latest("fred", sub_category="T10Y2YM")
        if t10y2y:
            m = self._parse_json(t10y2y.get("metrics"))
            data.treasury_yield_10y_2y = float(m.get("value", 0.0)) if m.get("value") is not None else None

        # fred 美联储资产负债表
        walcl = self._query_latest("fred", sub_category="WALCL")
        if walcl:
            m = self._parse_json(walcl.get("metrics"))
            data.fed_balance_sheet = float(m.get("value", 0.0)) if m.get("value") is not None else None

        return data


# ============================================================
# 单例
# ============================================================

_dc_client: Optional[DataCenterClient] = None


def get_data_center_client() -> DataCenterClient:
    """获取 DataCenterClient 单例"""
    global _dc_client
    if _dc_client is None:
        _dc_client = DataCenterClient()
    return _dc_client
