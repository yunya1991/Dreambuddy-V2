"""
仓位规则集
==========
仓位计算的默认规则实现。

包含：
    1. confidence_based_adjustment  - 置信度仓位调整
    2. volatility_based_adjustment  - 波动率仓位调整
    3. martin_addon_calculator      - 马丁加仓计算
    4. max_position_cap             - 最大仓位限制
    5. min_position_floor           - 最小仓位下限
"""

from typing import Dict, Any, Optional, List
from dataclasses import dataclass

try:
    from ..core.context import (
        Signal,
        RiskContext,
        Direction,
    )
    from ..core.registry import RuleRegistry, RuleCategory
except ImportError:
    from core.context import (
        Signal,
        RiskContext,
        Direction,
    )
    from core.registry import RuleRegistry, RuleCategory


@dataclass
class PositionRuleResult:
    """仓位规则结果"""
    adjusted_risk: float
    details: Dict[str, Any]


def register_default_position_rules(registry: RuleRegistry, config: Optional[Dict[str, Any]] = None):
    """注册所有默认仓位规则

    Args:
        registry: 规则注册表
        config: 全局配置
    """
    position_config = (config or {}).get("position", {})

    registry.register(
        name="confidence_based_adjustment",
        category=RuleCategory.POSITION,
        handler=confidence_based_adjustment,
        priority=10,
        description="置信度仓位调整 - 高置信度加仓，低置信度减仓",
    )

    registry.register(
        name="volatility_based_adjustment",
        category=RuleCategory.POSITION,
        handler=volatility_based_adjustment,
        priority=20,
        description="波动率仓位调整 - 高波动减仓，低波动加仓",
    )

    registry.register(
        name="max_position_cap",
        category=RuleCategory.POSITION,
        handler=max_position_cap,
        priority=90,
        description="最大仓位限制 - 单笔仓位不超过总权益的一定比例",
    )


def confidence_based_adjustment(
    signal: Signal,
    context: RiskContext,
    base_risk: float,
    config: Dict[str, Any],
    extra: Optional[Dict[str, Any]] = None,
) -> PositionRuleResult:
    """置信度仓位调整规则

    基于信号置信度动态调整风险预算：
    - 高置信度(>0.8): 风险×1.2
    - 中置信度(0.4-0.8): 风险×1.0
    - 低置信度(0.2-0.4): 风险×0.5
    """
    confidence = signal.confidence

    if confidence >= 0.8:
        multiplier = config.get("high_conf_multiplier", 1.2)
    elif confidence >= 0.6:
        multiplier = config.get("mid_high_conf_multiplier", 1.0)
    elif confidence >= 0.4:
        multiplier = config.get("mid_conf_multiplier", 1.0)
    else:
        multiplier = config.get("low_conf_multiplier", 0.5)

    adjusted = base_risk * multiplier

    return PositionRuleResult(
        adjusted_risk=adjusted,
        details={
            "confidence": confidence,
            "confidence_multiplier": multiplier,
        }
    )


def volatility_based_adjustment(
    signal: Signal,
    context: RiskContext,
    base_risk: float,
    config: Dict[str, Any],
    extra: Optional[Dict[str, Any]] = None,
) -> PositionRuleResult:
    """波动率仓位调整规则

    基于市场波动率动态调整风险预算：
    - 高波动时降低仓位
    - 低波动时可适当增加仓位
    """
    extra = extra or {}
    atr_pct = extra.get("atr_pct", 0.02)
    baseline_atr = config.get("baseline_atr_pct", 0.02)

    if atr_pct <= 0:
        atr_pct = baseline_atr

    ratio = baseline_atr / atr_pct
    ratio = max(0.3, min(2.0, ratio))

    adjusted = base_risk * ratio

    return PositionRuleResult(
        adjusted_risk=adjusted,
        details={
            "atr_pct": atr_pct,
            "baseline_atr": baseline_atr,
            "volatility_multiplier": ratio,
        }
    )


def max_position_cap(
    signal: Signal,
    context: RiskContext,
    base_risk: float,
    config: Dict[str, Any],
    extra: Optional[Dict[str, Any]] = None,
) -> PositionRuleResult:
    """最大仓位限制规则

    确保单笔仓位不超过总权益的一定比例。
    """
    max_pos_pct = config.get("max_position_pct", 0.25)
    max_position_usdt = context.total_equity * max_pos_pct

    extra = extra or {}
    entry_price = signal.entry_price or extra.get("current_price", 0)
    stop_loss = signal.stop_loss_price or extra.get("stop_loss_price", 0)

    if entry_price > 0 and stop_loss > 0:
        stop_distance_pct = abs(entry_price - stop_loss) / entry_price
    else:
        stop_distance_pct = config.get("default_stop_pct", 0.02)

    if stop_distance_pct > 0:
        current_position_size = base_risk / stop_distance_pct
    else:
        current_position_size = base_risk

    if current_position_size > max_position_usdt:
        adjusted_risk = max_position_usdt * stop_distance_pct
        capped = True
    else:
        adjusted_risk = base_risk
        capped = False

    return PositionRuleResult(
        adjusted_risk=adjusted_risk,
        details={
            "max_position_usdt": max_position_usdt,
            "max_position_pct": max_pos_pct,
            "position_capped": capped,
        }
    )


def min_position_floor(
    signal: Signal,
    context: RiskContext,
    base_risk: float,
    config: Dict[str, Any],
    extra: Optional[Dict[str, Any]] = None,
) -> PositionRuleResult:
    """最小仓位下限规则

    确保仓位不低于最小交易单位。
    """
    min_position_usdt = config.get("min_position_usdt", 1.0)

    extra = extra or {}
    entry_price = signal.entry_price or extra.get("current_price", 0)
    stop_loss = signal.stop_loss_price or extra.get("stop_loss_price", 0)

    if entry_price > 0 and stop_loss > 0:
        stop_distance_pct = abs(entry_price - stop_loss) / entry_price
    else:
        stop_distance_pct = config.get("default_stop_pct", 0.02)

    if stop_distance_pct > 0:
        current_position_size = base_risk / stop_distance_pct
    else:
        current_position_size = base_risk

    if current_position_size < min_position_usdt:
        adjusted_risk = min_position_usdt * stop_distance_pct
        floored = True
    else:
        adjusted_risk = base_risk
        floored = False

    return PositionRuleResult(
        adjusted_risk=adjusted_risk,
        details={
            "min_position_usdt": min_position_usdt,
            "position_floored": floored,
        }
    )
