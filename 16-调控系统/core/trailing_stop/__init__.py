"""
TrailingStopComponent 包入口
=============================

统一导出类型和主组件，使用方式::

    from trailing_stop import (
        TrailingStopComponent,
        TrailingAction,
        TrailingStatus,
        TrailingSnapshot,
        TrailingState,
        TrailingResult,
        TrailingStats,
    )
"""

from .types import (
    TrailingAction,
    TrailingResult,
    TrailingSnapshot,
    TrailingState,
    TrailingStats,
    TrailingStatus,
    calc_atr_trailing_price,
    calc_pnl_eff_pct,
    now_iso,
)
from .component import TrailingStopComponent

__all__ = [
    "TrailingStopComponent",
    "TrailingAction",
    "TrailingStatus",
    "TrailingSnapshot",
    "TrailingState",
    "TrailingResult",
    "TrailingStats",
    "calc_atr_trailing_price",
    "calc_pnl_eff_pct",
    "now_iso",
]
