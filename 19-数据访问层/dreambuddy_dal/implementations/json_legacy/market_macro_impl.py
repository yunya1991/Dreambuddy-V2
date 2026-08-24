"""JsonLegacyMarketMacroRepository（P0 内存 6 宏观列表）"""
from __future__ import annotations

from datetime import datetime
from typing import List

from dreambuddy_dal.protocols.market_macro_repo import MarketMacroRepository


class JsonLegacyMarketMacroRepository(MarketMacroRepository):
    """P0 阶段 6 宏观域薄实现，upsert append 列表；query 全扫筛选"""

    def __init__(self):
        self._fg: List[tuple] = []
        self._funding: List[tuple] = []
        self._oi: List[tuple] = []
        self._liq: List[tuple] = []
        self._lsr: List[tuple] = []
        self._tv: List[tuple] = []

    # ---------- 5.1 恐惧贪婪 ----------
    def upsert_fear_greed(self, value: int, value_classification: str, ts: datetime) -> bool:
        self._fg.append((value, value_classification, ts))
        return True

    def query_fear_greed_by_time(self, start_ts, end_ts):
        return [(v, c, t) for v, c, t in self._fg if start_ts <= t <= end_ts]

    # ---------- 5.2 资金费率 ----------
    def upsert_funding_rate(self, symbol, funding_rate, funding_ts) -> bool:
        self._funding.append((symbol, funding_rate, funding_ts))
        return True

    def query_funding_by_time(self, symbol, start_ts, end_ts):
        return [(s, r, t) for s, r, t in self._funding
                if s == symbol and start_ts <= t <= end_ts]

    # ---------- 5.3 持仓量 ----------
    def upsert_open_interest(self, symbol, oi, sum_v, ts) -> bool:
        self._oi.append((symbol, oi, sum_v, ts))
        return True

    def query_open_interest_by_time(self, symbol, start_ts, end_ts):
        return [row for row in self._oi
                if row[0] == symbol and start_ts <= row[3] <= end_ts]

    # ---------- 5.4 爆仓 ----------
    def upsert_liquidation(self, symbol, qty, side, price, total, ts) -> bool:
        self._liq.append((symbol, qty, side, price, total, ts))
        return True

    def query_liquidation_by_time(self, symbol, start_ts, end_ts):
        return [r for r in self._liq
                if r[0] == symbol and start_ts <= r[5] <= end_ts]

    # ---------- 5.5 多空比 ----------
    def upsert_long_short_ratio(self, symbol, long_a, short_a, ratio, ts) -> bool:
        self._lsr.append((symbol, long_a, short_a, ratio, ts))
        return True

    def query_long_short_ratio_by_time(self, symbol, start_ts, end_ts):
        return [r for r in self._lsr
                if r[0] == symbol and start_ts <= r[4] <= end_ts]

    # ---------- 5.6 Taker 主动买卖量 ----------
    def upsert_taker_volume(self, symbol, buy, sell, diff, ratio, ts) -> bool:
        self._tv.append((symbol, buy, sell, diff, ratio, ts))
        return True

    def query_taker_volume_by_time(self, symbol, start_ts, end_ts):
        return [r for r in self._tv
                if r[0] == symbol and start_ts <= r[5] <= end_ts]


__all__ = ["JsonLegacyMarketMacroRepository"]
