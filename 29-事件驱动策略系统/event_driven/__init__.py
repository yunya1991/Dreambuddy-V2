"""event_driven — 事件驱动策略子交易系统（29 号子系统）核心包。

独立子交易系统，与 BCRM2.0、BDSM 平级。
核心职责：宏观事件信号生成 + 开仓/平仓 + 仓位管理（独立闭环）。

迁移记录：2026-10-04 从 23-四层闭环自进化交易架构/dreambuddy_evolution/engines/ 迁出。
"""

from __future__ import annotations

# --- 事件驱动策略核心 ---
from .event_driven_strategy import (
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

# --- 置信度评分 ---
from .conviction_scorer import ConvictionResult, ConvictionScorer

# --- 事件主导控制 ---
from .event_dominance_controller import DominanceDecision, EventDominanceController

# --- 事件案例库 ---
from .event_case_library import EventCase, EventCaseLibrary

__all__ = [
    # 常量
    "ELASTICITY_TREND_FOLLOW",
    "ELASTICITY_MEAN_REVERT",
    "ELASTICITY_NONE",
    "VALID_SIGNALS",
    "VALID_EVENT_TYPES",
    "EVENT_HALF_LIFE",
    "PHASE_THRESHOLDS",
    "PHASE_POSITION_MULT",
    # 策略核心
    "EventSignal",
    "EventDrivenSignal",
    "EventDrivenStrategy",
    "EventDrivenTrader",
    "compute_impulse",
    "neutral_event_signal",
    # 置信度
    "ConvictionResult",
    "ConvictionScorer",
    # 主导控制
    "DominanceDecision",
    "EventDominanceController",
    # 案例库
    "EventCase",
    "EventCaseLibrary",
]

__version__ = "1.0.0"
