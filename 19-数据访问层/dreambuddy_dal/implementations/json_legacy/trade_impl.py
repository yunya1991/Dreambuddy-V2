"""
JsonLegacyTradeRepository：现状薄适配 + P0 内存 dict 实现（模拟现有 trading_utils.jsonl）
⚠️ P0-only：真实接入 P1
"""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Dict, List, Optional

from dreambuddy_dal.protocols.trade_repo import TradeRepository
from dreambuddy_dal.unified_models import (
    CloseInfo,
    DailyStats,
    ExitReason,
    TradeRecord,
    TradeStatus,
)

# ─── 进程内伪存储（P0 期：替代现状 JSONL；P1 期改为读现状 JSON）──────
_TRADE_STORE: Dict[str, TradeRecord] = {}
_DAILY_STATS_STORE: Dict[tuple, DailyStats] = {}  # (stat_date,symbol,sub_sys,strategy)→DailyStats


class JsonLegacyTradeRepository(TradeRepository):
    """薄适配：P0 用内存 dict；API 与 Protocol 完全一致，不抛异常"""

    # -------------- 写 --------------
    def add_trade(self, trade: TradeRecord) -> Optional[str]:
        # 幂等：若已存在同 id 不覆盖（UNIQUE 语义）
        if trade.trade_id in _TRADE_STORE:
            return trade.trade_id
        _TRADE_STORE[trade.trade_id] = trade
        return trade.trade_id

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
        if trade_id not in _TRADE_STORE:
            return None
        t = _TRADE_STORE[trade_id]
        info = CloseInfo(
            exit_reason=exit_reason, exit_price=exit_price, close_ts=close_ts,
            realized_pnl=realized_pnl, slippage_bps=slippage_bps, execution_id=execution_id,
        )
        t.close_info = info
        t.status = TradeStatus.CLOSED
        return info

    def add_or_update_daily_stats(self, stats: DailyStats) -> bool:
        key = (stats.stat_date, stats.symbol, stats.sub_system, stats.strategy_name)
        _DAILY_STATS_STORE[key] = stats
        return True

    # -------------- 读 --------------
    def get_trade(self, trade_id: str) -> Optional[TradeRecord]:
        return _TRADE_STORE.get(trade_id)

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
        results: List[TradeRecord] = []
        for t in _TRADE_STORE.values():
            if symbol is not None and t.symbol != symbol:
                continue
            if start_ts is not None and t.entry_ts < start_ts:
                continue
            if end_ts is not None and t.entry_ts > end_ts:
                continue
            if strategy is not None and t.strategy_name != strategy:
                continue
            if status is not None and t.status != status:
                continue
            results.append(t)
            if len(results) >= limit:
                break
        return results

    def get_daily_stats(
        self,
        symbol: str,
        stat_date: str,
        *,
        sub_system: Optional[str] = None,
        strategy_name: Optional[str] = None,
    ) -> Optional[DailyStats]:
        for key, s in _DAILY_STATS_STORE.items():
            sd, sy, ss, st = key
            if sy != symbol or sd != stat_date:
                continue
            if sub_system is not None and ss != sub_system:
                continue
            if strategy_name is not None and st != strategy_name:
                continue
            return s
        return None


__all__ = ["JsonLegacyTradeRepository"]
