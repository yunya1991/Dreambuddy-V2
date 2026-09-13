"""TrendFollowingEngine 包 — 趋势跟踪 + 正金字塔加仓 + 2N 止损

归属：dreambuddy_evolution/engines/trend_following/（独立包，HC-TF-08）
参考：SPEC-趋势跟踪正金字塔与网格策略落地.md Phase B
"""
from dreambuddy_evolution.engines.trend_following.trend_following_engine import (
    ATRStopCalculator,
    DonchianChannel,
    PyramidingPositionSizer,
    TrendExitRule,
    TrendFollowingEngine,
)

__all__ = [
    "TrendFollowingEngine",
    "DonchianChannel",
    "ATRStopCalculator",
    "PyramidingPositionSizer",
    "TrendExitRule",
]
