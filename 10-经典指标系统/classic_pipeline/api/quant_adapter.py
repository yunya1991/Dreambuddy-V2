"""Quant Signal API 兼容层。

承接单体 quant/signals 路由的核心计算签名，委托给 classic_pipeline.signals.quant_signal。
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

import pandas as pd

from classic_pipeline.signals.quant_signal import (
    signal_confidence,
    strategy_weight,
    strategy_perf,
    vote,
    risk_gate,
    compute,
)


def compute_quant_signal(
    df: Optional[pd.DataFrame],
    config: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """计算 Quant 信号。"""
    return compute(df, config)


def compute_signal_confidence(
    strategy_id: str,
    group_id: str,
    tag: Any,
    features: Dict[str, Any],
    rules: Optional[Dict[str, Any]] = None,
) -> float:
    """基于规则的信号置信度计算。"""
    return signal_confidence(strategy_id, group_id, tag, features, rules)


def compute_strategy_weight(
    current: float,
    perf: Optional[Dict[str, Any]] = None,
    config: Optional[Dict[str, Any]] = None,
) -> float:
    """策略权重调整。"""
    return strategy_weight(current, perf, config)


def compute_strategy_perf(
    rets: List[float],
    config: Optional[Dict[str, Any]] = None,
) -> Dict[str, float]:
    """策略绩效计算。"""
    return strategy_perf(rets, config)


def vote_signals(
    strategy_signals: List[Dict[str, Any]],
    config: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """多策略投票。"""
    return vote(strategy_signals, config)


def risk_check(
    signal: Dict[str, Any],
    portfolio_state: Optional[Dict[str, Any]] = None,
    config: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """风险门控。"""
    return risk_gate(signal, portfolio_state, config)
