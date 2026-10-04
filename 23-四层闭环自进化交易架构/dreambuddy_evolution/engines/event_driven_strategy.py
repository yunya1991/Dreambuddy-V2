"""兼容层（向后兼容）：事件驱动策略已迁移至 29-事件驱动策略系统。

真实实现：29-事件驱动策略系统/event_driven/event_driven_strategy.py
迁移日期：2026-10-04
此文件仅做 re-export，请勿在此添加业务逻辑。
"""
from __future__ import annotations

import sys
from pathlib import Path

_29_dir = str(Path(__file__).resolve().parents[3] / "29-事件驱动策略系统")
if _29_dir not in sys.path:
    sys.path.insert(0, _29_dir)

from event_driven.event_driven_strategy import *  # noqa: F401,F403
from event_driven.event_driven_strategy import (  # noqa: F401
    ELASTICITY_MEAN_REVERT,
    ELASTICITY_NONE,
    ELASTICITY_TREND_FOLLOW,
    EVENT_HALF_LIFE,
    PHASE_POSITION_MULT,
    PHASE_THRESHOLDS,
    VALID_EVENT_TYPES,
    VALID_SIGNALS,
    EventDrivenSignal,
    EventDrivenStrategy,
    EventDrivenTrader,
    EventSignal,
    compute_impulse,
    neutral_event_signal,
)
