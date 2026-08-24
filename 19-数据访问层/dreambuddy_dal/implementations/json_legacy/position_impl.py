"""JsonLegacyPositionRepository（P0 内存实现，薄适配）"""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Dict, List, Optional

from dreambuddy_dal.protocols.position_repo import PositionRepository
from dreambuddy_dal.unified_models import PositionState, TradeDirection

_POSITION_STORE: Dict[str, PositionState] = {}  # position_id → state


class JsonLegacyPositionRepository(PositionRepository):
    def upsert_position(self, position: PositionState) -> bool:
        _POSITION_STORE[position.position_id] = position
        return True

    def get_position(
        self,
        symbol: str,
        sub_system: Optional[str] = None,
        direction: Optional[TradeDirection] = None,
    ) -> Optional[PositionState]:
        matches: List[PositionState] = []
        for p in _POSITION_STORE.values():
            if p.symbol != symbol:
                continue
            if sub_system is not None and p.sub_system != sub_system:
                continue
            if direction is not None and p.direction != direction:
                continue
            matches.append(p)
        if len(matches) == 0:
            return None
        if len(matches) > 1:
            raise ValueError(
                f"get_position({symbol}, sub={sub_system}, dir={direction}) 命中 {len(matches)} 条，"
                f"请明确指定 sub_system / direction"
            )
        return matches[0]

    def list_positions(
        self,
        sub_system: Optional[str] = None,
        *,
        symbol: Optional[str] = None,
    ) -> List[PositionState]:
        out: List[PositionState] = []
        for p in _POSITION_STORE.values():
            if sub_system is not None and p.sub_system != sub_system:
                continue
            if symbol is not None and p.symbol != symbol:
                continue
            out.append(p)
        return out

    def refresh_mark_price(
        self,
        position_id: str,
        mark_price: Decimal,
        unrealized_pnl: Decimal,
        refresh_ts: datetime,
        *,
        liquidation_price: Optional[Decimal] = None,
    ) -> bool:
        p = _POSITION_STORE.get(position_id)
        if p is None:
            return False
        p.mark_price = mark_price
        p.unrealized_pnl = unrealized_pnl
        p.last_price_refresh_ts = refresh_ts
        if liquidation_price is not None:
            p.liquidation_price = liquidation_price
        return True


__all__ = ["JsonLegacyPositionRepository"]
