"""
dreambuddy_dal.protocols.trade_repo — TradeRepository Protocol（交易域）
严格对齐 TECHNICAL_DESIGN.md §2.2「1）TradeRepository：交易记录（核心账本）」方法签名
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime
from decimal import Decimal
from typing import List, Optional

from dreambuddy_dal.unified_models import (
    CloseInfo,
    DailyStats,
    ExitReason,
    TradeRecord,
    TradeStatus,
)


class TradeRepository(ABC):
    """交易账本 Repository 抽象（DAL 唯一出口）。"""

    # ------------------------------------------------------------------
    # 写入类
    # ------------------------------------------------------------------
    @abstractmethod
    def add_trade(self, trade: TradeRecord) -> Optional[str]:
        """
        新增一笔交易。
        :return: trade_id（成功）/ None（失败，用于 DualWrite 新败不阻塞场景）
        """
        ...

    @abstractmethod
    def close_position(
        self,
        trade_id: str,
        exit_reason: ExitReason,
        exit_price: Decimal,
        close_ts: datetime,
        realized_pnl: Decimal,
        *,
        slippage_bps: int = 0,
        execution_id: Optional[str] = None,
    ) -> Optional[CloseInfo]:
        """
        按 trade_id 标记 CLOSED，写入 CloseInfo。
        :return: 完整 CloseInfo 或 None（DualWrite 新败返回 None）
        """
        ...

    @abstractmethod
    def add_or_update_daily_stats(self, stats: DailyStats) -> bool:
        """tr_daily_stats 幂等 upsert（主键 stat_date+symbol+sub_sys+strategy）。返回 True/False"""
        ...

    # ------------------------------------------------------------------
    # 查询类
    # ------------------------------------------------------------------
    @abstractmethod
    def get_trade(self, trade_id: str) -> Optional[TradeRecord]:
        """按 trade_id 查；不存在返回 None"""
        ...

    @abstractmethod
    def query_trades(
        self,
        symbol: Optional[str] = None,
        *,
        start_ts: Optional[datetime] = None,
        end_ts: Optional[datetime] = None,
        strategy: Optional[str] = None,
        status: Optional[TradeStatus] = None,
        limit: int = 1000,
    ) -> List[TradeRecord]:
        """
        交易查询。参数有默认值意味着"该条件不限制"。
        - P0 JsonLegacyImpl：O(n) 扫描。P1 SqliteImpl：通过 idx_trades_symbol_time 命中 O(log n)。
        """
        ...

    @abstractmethod
    def get_daily_stats(
        self,
        symbol: str,
        stat_date: str,
        *,
        sub_system: Optional[str] = None,
        strategy_name: Optional[str] = None,
    ) -> Optional[DailyStats]:
        """按日主键查询每日统计快照"""
        ...
