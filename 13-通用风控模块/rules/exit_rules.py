"""
离场规则集
==========
离场决策的默认规则实现。

四大优先级：
    P0 - 安全硬退出
    P1 - 价值-风险评估
    P2 - 三重屏障
    P3 - 行为约束
"""

from typing import Dict, Any, Optional
from dataclasses import dataclass

try:
    from ..core.context import (
        PositionState,
        MarketSnapshot,
        RiskContext,
        ExitResult,
        ExitAction,
        ExitPriority,
        Direction,
    )
    from ..core.registry import RuleRegistry, RuleCategory
except ImportError:
    from core.context import (
        PositionState,
        MarketSnapshot,
        RiskContext,
        ExitResult,
        ExitAction,
        ExitPriority,
        Direction,
    )
    from core.registry import RuleRegistry, RuleCategory


def register_default_exit_rules(registry: RuleRegistry, config: Optional[Dict[str, Any]] = None):
    """注册所有默认离场规则

    Args:
        registry: 规则注册表
        config: 全局配置
    """
    exit_config = (config or {}).get("exit", {})

    registry.register(
        name="max_loss_stop",
        category=RuleCategory.EXIT,
        handler=max_loss_stop,
        priority=5,
        description="最大亏损止损 - P0安全硬退出，亏损达到阈值立即平仓",
    )

    registry.register(
        name="max_hold_time",
        category=RuleCategory.EXIT,
        handler=max_hold_time,
        priority=10,
        description="最大持仓时间 - P0安全硬退出，持仓超过最大时间平仓",
    )

    registry.register(
        name="liquidation_buffer",
        category=RuleCategory.EXIT,
        handler=liquidation_buffer,
        priority=8,
        description="强平安全缓冲 - P0安全硬退出，接近强平价时平仓",
    )

    registry.register(
        name="stop_loss_barrier",
        category=RuleCategory.EXIT,
        handler=stop_loss_barrier,
        priority=20,
        description="止损屏障 - P2三重屏障之止损",
    )

    registry.register(
        name="take_profit_barrier",
        category=RuleCategory.EXIT,
        handler=take_profit_barrier,
        priority=25,
        description="止盈屏障 - P2三重屏障之止盈",
    )

    registry.register(
        name="trailing_stop",
        category=RuleCategory.EXIT,
        handler=trailing_stop,
        priority=35,
        description="跟踪止损 - P3行为约束，移动止盈",
    )

    registry.register(
        name="time_barrier",
        category=RuleCategory.EXIT,
        handler=time_barrier,
        priority=30,
        description="时间屏障 - P2三重屏障之时间",
    )


def max_loss_stop(
    position: PositionState,
    market: Optional[MarketSnapshot],
    context: Optional[RiskContext],
    config: Dict[str, Any],
    extra: Optional[Dict[str, Any]] = None,
) -> Optional[ExitResult]:
    """最大亏损止损规则 (P0)

    亏损达到最大阈值时立即平仓。
    """
    max_loss_pct = config.get("max_loss_pct", 0.10)
    leverage = position.leverage or 1.0
    eff_loss = abs(position.pnl_eff)

    if eff_loss >= max_loss_pct * leverage:
        return ExitResult(
            action=ExitAction.CLOSE,
            priority=ExitPriority.P0_L0_HARD,
            reason=f"最大亏损止损: 有效亏损 {eff_loss:.2%} >= {max_loss_pct * leverage:.2%}",
            details={"max_loss_pct": max_loss_pct, "eff_loss": eff_loss},
        )

    return None


def max_hold_time(
    position: PositionState,
    market: Optional[MarketSnapshot],
    context: Optional[RiskContext],
    config: Dict[str, Any],
    extra: Optional[Dict[str, Any]] = None,
) -> Optional[ExitResult]:
    """最大持仓时间规则 (P0)

    持仓时间超过阈值时平仓。
    """
    max_hold_sec = config.get("max_hold_sec", 7 * 24 * 3600)

    if position.position_age_sec >= max_hold_sec:
        days = position.position_age_sec / 86400
        max_days = max_hold_sec / 86400
        return ExitResult(
            action=ExitAction.CLOSE,
            priority=ExitPriority.P0_L0_HARD,
            reason=f"最大持仓时间: {days:.1f}天 >= {max_days:.1f}天",
            details={"max_hold_sec": max_hold_sec, "position_age_sec": position.position_age_sec},
        )

    return None


def liquidation_buffer(
    position: PositionState,
    market: Optional[MarketSnapshot],
    context: Optional[RiskContext],
    config: Dict[str, Any],
    extra: Optional[Dict[str, Any]] = None,
) -> Optional[ExitResult]:
    """强平安全缓冲规则 (P0)

    价格接近强平价时提前平仓，避免被强制平仓。
    """
    if position.liq_price <= 0:
        return None

    buffer_pct = config.get("liquidation_buffer_pct", 0.05)
    current_price = position.current_price

    if position.is_long:
        distance_to_liq = (current_price - position.liq_price) / current_price
    else:
        distance_to_liq = (position.liq_price - current_price) / current_price

    if distance_to_liq <= buffer_pct:
        return ExitResult(
            action=ExitAction.CLOSE,
            priority=ExitPriority.P0_L0_HARD,
            reason=f"强平缓冲触发: 距强平价 {distance_to_liq:.2%} <= {buffer_pct:.2%}",
            details={"liq_price": position.liq_price, "distance_to_liq": distance_to_liq},
        )

    return None


def stop_loss_barrier(
    position: PositionState,
    market: Optional[MarketSnapshot],
    context: Optional[RiskContext],
    config: Dict[str, Any],
    extra: Optional[Dict[str, Any]] = None,
) -> Optional[ExitResult]:
    """止损屏障规则 (P2)

    基于ATR或固定百分比的止损。
    """
    method = config.get("stop_method", "atr")
    atr_multiplier = config.get("atr_stop_multiplier", 2.0)
    stop_pct = config.get("stop_loss_pct", 0.03)

    entry_price = position.entry_price
    current_price = position.current_price

    if method == "atr":
        atr_value = entry_price * position.atr_pct
        stop_distance = atr_value * atr_multiplier
    else:
        stop_distance = entry_price * stop_pct

    if position.is_long:
        stop_price = entry_price - stop_distance
        if current_price <= stop_price:
            return ExitResult(
                action=ExitAction.CLOSE,
                priority=ExitPriority.P2_TRIPLE_BARRIER,
                reason=f"止损屏障触发: 价格 {current_price} <= 止损价 {stop_price:.2f}",
                details={"stop_price": stop_price, "method": method},
            )
    else:
        stop_price = entry_price + stop_distance
        if current_price >= stop_price:
            return ExitResult(
                action=ExitAction.CLOSE,
                priority=ExitPriority.P2_TRIPLE_BARRIER,
                reason=f"止损屏障触发: 价格 {current_price} >= 止损价 {stop_price:.2f}",
                details={"stop_price": stop_price, "method": method},
            )

    return None


def take_profit_barrier(
    position: PositionState,
    market: Optional[MarketSnapshot],
    context: Optional[RiskContext],
    config: Dict[str, Any],
    extra: Optional[Dict[str, Any]] = None,
) -> Optional[ExitResult]:
    """止盈屏障规则 (P2)

    基于盈亏比或固定百分比的止盈，优先减仓而非全部平仓。
    """
    method = config.get("tp_method", "rr")
    rr_ratio = config.get("rr_ratio", 2.0)
    tp_pct = config.get("take_profit_pct", 0.06)
    reduce_frac = config.get("tp_reduce_frac", 0.5)

    entry_price = position.entry_price
    current_price = position.current_price

    if method == "pct":
        tp_distance = entry_price * tp_pct
    else:
        stop_pct = config.get("stop_loss_pct", 0.03)
        tp_distance = entry_price * stop_pct * rr_ratio

    if position.is_long:
        tp_price = entry_price + tp_distance
        if current_price >= tp_price:
            return ExitResult(
                action=ExitAction.REDUCE,
                priority=ExitPriority.P2_TRIPLE_BARRIER,
                reason=f"止盈屏障触发: 价格 {current_price} >= 止盈价 {tp_price:.2f}",
                reduce_frac=reduce_frac,
                details={"tp_price": tp_price, "method": method, "reduce_frac": reduce_frac},
            )
    else:
        tp_price = entry_price - tp_distance
        if current_price <= tp_price:
            return ExitResult(
                action=ExitAction.REDUCE,
                priority=ExitPriority.P2_TRIPLE_BARRIER,
                reason=f"止盈屏障触发: 价格 {current_price} <= 止盈价 {tp_price:.2f}",
                reduce_frac=reduce_frac,
                details={"tp_price": tp_price, "method": method, "reduce_frac": reduce_frac},
            )

    return None


def trailing_stop(
    position: PositionState,
    market: Optional[MarketSnapshot],
    context: Optional[RiskContext],
    config: Dict[str, Any],
    extra: Optional[Dict[str, Any]] = None,
) -> Optional[ExitResult]:
    """跟踪止损规则 (P3)

    盈利达到一定幅度后启动跟踪止损，保护利润。
    """
    arm_pct = config.get("trailing_arm_pct", 0.03)
    trail_pct = config.get("trailing_pct", 0.02)

    current_price = position.current_price
    mfe_pnl_pct = position.mfe_pnl_pct

    if position.is_long:
        if mfe_pnl_pct >= arm_pct and not position.trailing_armed:
            return ExitResult(
                action=ExitAction.HOLD,
                priority=ExitPriority.P3_BEHAVIORAL,
                reason="跟踪止损已激活",
                details={"trailing_armed": True, "arm_pct": arm_pct},
            )

        if position.trailing_armed and position.trailing_stop_price > 0:
            if current_price <= position.trailing_stop_price:
                return ExitResult(
                    action=ExitAction.CLOSE,
                    priority=ExitPriority.P3_BEHAVIORAL,
                    reason=f"跟踪止损触发: 价格 {current_price} <= 跟踪止损价 {position.trailing_stop_price:.2f}",
                    details={"trailing_stop_price": position.trailing_stop_price},
                )
    else:
        if mfe_pnl_pct >= arm_pct and not position.trailing_armed:
            return ExitResult(
                action=ExitAction.HOLD,
                priority=ExitPriority.P3_BEHAVIORAL,
                reason="跟踪止损已激活",
                details={"trailing_armed": True, "arm_pct": arm_pct},
            )

        if position.trailing_armed and position.trailing_stop_price > 0:
            if current_price >= position.trailing_stop_price:
                return ExitResult(
                    action=ExitAction.CLOSE,
                    priority=ExitPriority.P3_BEHAVIORAL,
                    reason=f"跟踪止损触发: 价格 {current_price} >= 跟踪止损价 {position.trailing_stop_price:.2f}",
                    details={"trailing_stop_price": position.trailing_stop_price},
                )

    return None


def time_barrier(
    position: PositionState,
    market: Optional[MarketSnapshot],
    context: Optional[RiskContext],
    config: Dict[str, Any],
    extra: Optional[Dict[str, Any]] = None,
) -> Optional[ExitResult]:
    """时间屏障规则 (P2)

    持仓达到一定时间且盈利达标时触发离场。
    """
    time_barrier_sec = config.get("time_barrier_sec", 24 * 3600)
    min_profit_pct = config.get("time_barrier_min_profit_pct", 0.01)

    if position.position_age_sec >= time_barrier_sec:
        if position.unrealized_pnl_pct >= min_profit_pct:
            hours = position.position_age_sec / 3600
            return ExitResult(
                action=ExitAction.REDUCE,
                priority=ExitPriority.P2_TRIPLE_BARRIER,
                reason=f"时间屏障触发: 持仓 {hours:.1f}小时，盈利 {position.unrealized_pnl_pct:.2%}",
                reduce_frac=0.5,
                details={
                    "time_barrier_sec": time_barrier_sec,
                    "position_age_sec": position.position_age_sec,
                    "min_profit_pct": min_profit_pct,
                },
            )

    return None
