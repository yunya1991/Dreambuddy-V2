"""
dreambuddy_dal.protocols.position_repo — PositionRepository Protocol（持仓域）
对齐 TECHNICAL_DESIGN.md §2.2「2）PositionRepository：当前净持仓状态」
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime
from decimal import Decimal
from typing import List, Optional

from dreambuddy_dal.unified_models import PositionState, TradeDirection


class PositionRepository(ABC):
    """净持仓快照 Repository。"""

    @abstractmethod
    def upsert_position(self, position: PositionState) -> bool:
        """
        主键 position_id（symbol:dir:sub_sys）幂等写入。
        - 相同 position_id：覆盖 open_quantity / avg_entry_price / unrealized_pnl 等最新值
        """
        ...

    @abstractmethod
    def get_position(
        self,
        symbol: str,
        sub_system: Optional[str] = None,
        direction: Optional[TradeDirection] = None,
    ) -> Optional[PositionState]:
        """
        精确查一个持仓。
        - sub_system=None 时，若该 symbol:dir 有多个子系统持仓，抛 ValueError（由调用方明确子系统）
        """
        ...

    @abstractmethod
    def list_positions(
        self,
        sub_system: Optional[str] = None,
        *,
        symbol: Optional[str] = None,
    ) -> List[PositionState]:
        """
        持仓列表：
        - list_positions(sub_system="YIJING") → 该子系统全部持仓
        - list_positions(symbol="XAGUSDT") → 某币种跨子系统持仓汇总查询
        - list_positions() → 全部持仓
        """
        ...

    @abstractmethod
    def refresh_mark_price(
        self,
        position_id: str,
        mark_price: Decimal,
        unrealized_pnl: Decimal,
        refresh_ts: datetime,
        *,
        liquidation_price: Optional[Decimal] = None,
    ) -> bool:
        """
        轻量更新：只刷新 mark_price / unrealized_pnl / last_price_refresh_ts
        （避免每次刷新重写整行 upsert_position）
        """
        ...
