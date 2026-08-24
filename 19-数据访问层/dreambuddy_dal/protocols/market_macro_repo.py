"""
dreambuddy_dal.protocols.market_macro_repo — 6 张宏观表 Repository
对齐 SCHEMA_DESIGN.md §5 宏观域 mm_ 前缀 6 张 WITHOUT ROWID 表
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime
from decimal import Decimal
from typing import List, Tuple


class MarketMacroRepository(ABC):
    """
    宏观 / 市场情绪数据仓储（写=18-数据获取中心；读=易经推理 / V15 / 经典指标）
    每张表 2 个方法：upsert_xxx + query_xxx_by_time
    """

    # ---------- 5.1 恐惧贪婪 ----------
    @abstractmethod
    def upsert_fear_greed(
        self, value: int, value_classification: str, ts: datetime
    ) -> bool: ...

    @abstractmethod
    def query_fear_greed_by_time(
        self, start_ts: datetime, end_ts: datetime
    ) -> List[Tuple[int, str, datetime]]: ...

    # ---------- 5.2 资金费率 ----------
    @abstractmethod
    def upsert_funding_rate(
        self,
        symbol: str,
        funding_rate: Decimal,
        funding_ts: datetime,
    ) -> bool: ...

    @abstractmethod
    def query_funding_by_time(
        self, symbol: str, start_ts: datetime, end_ts: datetime
    ) -> List[Tuple[str, Decimal, datetime]]: ...

    # ---------- 5.3 持仓量 ----------
    @abstractmethod
    def upsert_open_interest(
        self, symbol: str, open_interest: Decimal, sum_open_interest_value: Decimal, ts: datetime
    ) -> bool: ...

    @abstractmethod
    def query_open_interest_by_time(
        self, symbol: str, start_ts: datetime, end_ts: datetime
    ) -> List[Tuple[str, Decimal, Decimal, datetime]]: ...

    # ---------- 5.4 爆仓数据 ----------
    @abstractmethod
    def upsert_liquidation(
        self,
        symbol: str,
        order_quantity: Decimal,
        side: str,  # "BUY" / "SELL"
        price: Decimal,
        total_quantity: Decimal,
        ts: datetime,
    ) -> bool: ...

    @abstractmethod
    def query_liquidation_by_time(
        self, symbol: str, start_ts: datetime, end_ts: datetime
    ) -> List[Tuple[str, Decimal, str, Decimal, Decimal, datetime]]: ...

    # ---------- 5.5 多空比 ----------
    @abstractmethod
    def upsert_long_short_ratio(
        self, symbol: str, long_account: Decimal, short_account: Decimal,
        long_short_ratio: Decimal, ts: datetime,
    ) -> bool: ...

    @abstractmethod
    def query_long_short_ratio_by_time(
        self, symbol: str, start_ts: datetime, end_ts: datetime
    ) -> List[Tuple[str, Decimal, Decimal, Decimal, datetime]]: ...

    # ---------- 5.6 Taker 主动买卖量 ----------
    @abstractmethod
    def upsert_taker_volume(
        self, symbol: str, buy_vol: Decimal, sell_vol: Decimal,
        buy_sell_volume_diff: Decimal, buy_sell_volume_ratio: Decimal, ts: datetime,
    ) -> bool: ...

    @abstractmethod
    def query_taker_volume_by_time(
        self, symbol: str, start_ts: datetime, end_ts: datetime
    ) -> List[Tuple[str, Decimal, Decimal, Decimal, Decimal, datetime]]: ...
