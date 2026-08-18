"""
门禁规则集
==========
事前门禁的默认规则实现。

包含：
    1. daily_drawdown_circuit_breaker - 日回撤熔断 (P0)
    2. leverage_cap_check             - 杠杆上限检查 (P0)
    3. concurrent_position_limit      - 并发仓位限制
    4. consecutive_losses_limit       - 连续亏损限制
    5. blackout_period_check          - 黑窗时段检查
    6. confidence_minimum             - 最低置信度检查
    7. drawdown_warning_degrade       - 回撤警告降级
    8. strategy_exclusion_check       - 战略排除检查
"""

from typing import Dict, Any, Optional
from datetime import datetime, timezone

try:
    from ..core.context import (
        Signal,
        RiskContext,
        RiskCheckResult,
        ReasonCode,
        Direction,
    )
    from ..core.registry import RuleRegistry, RuleCategory
except ImportError:
    from core.context import (
        Signal,
        RiskContext,
        RiskCheckResult,
        ReasonCode,
        Direction,
    )
    from core.registry import RuleRegistry, RuleCategory


def register_default_gate_rules(registry: RuleRegistry, config: Optional[Dict[str, Any]] = None):
    """注册所有默认门禁规则

    Args:
        registry: 规则注册表
        config: 全局配置
    """
    gate_config = (config or {}).get("gate", {})

    registry.register(
        name="daily_drawdown_circuit_breaker",
        category=RuleCategory.GATE,
        handler=daily_drawdown_circuit_breaker,
        priority=5,
        description="日回撤熔断 - 当日回撤超过阈值时全天禁止开仓",
    )

    registry.register(
        name="leverage_cap_check",
        category=RuleCategory.GATE,
        handler=leverage_cap_check,
        priority=10,
        description="杠杆上限检查 - 确保杠杆不超过最大限制",
    )

    registry.register(
        name="concurrent_position_limit",
        category=RuleCategory.GATE,
        handler=concurrent_position_limit,
        priority=20,
        description="并发仓位限制 - 限制同时持有的仓位数量",
    )

    registry.register(
        name="consecutive_losses_limit",
        category=RuleCategory.GATE,
        handler=consecutive_losses_limit,
        priority=25,
        description="连续亏损限制 - 连续亏损达到阈值时暂停开仓",
    )

    registry.register(
        name="blackout_period_check",
        category=RuleCategory.GATE,
        handler=blackout_period_check,
        priority=30,
        description="黑窗时段检查 - 宏观数据发布等高风险时段禁止开仓",
    )

    registry.register(
        name="confidence_minimum",
        category=RuleCategory.GATE,
        handler=confidence_minimum,
        priority=50,
        description="最低置信度检查 - 信号置信度不足时降级或拒绝",
    )

    registry.register(
        name="drawdown_warning_degrade",
        category=RuleCategory.GATE,
        handler=drawdown_warning_degrade,
        priority=60,
        description="回撤警告降级 - 回撤达到警告线时仓位减半",
    )


def daily_drawdown_circuit_breaker(
    signal: Signal,
    context: RiskContext,
    config: Dict[str, Any],
    extra: Optional[Dict[str, Any]] = None,
) -> RiskCheckResult:
    """日回撤熔断规则

    当日回撤超过阈值时，全天禁止开仓。

    阈值：
        - 硬熔断: max_daily_drawdown_pct (默认 10%)
    """
    max_dd = config.get("max_daily_drawdown_pct", 0.10)
    current_dd = context.daily_drawdown_pct

    if current_dd >= max_dd:
        return RiskCheckResult.fail_result(
            reason_code=ReasonCode.HARD_FAIL_DRAWDOWN_CIRCUIT_BREAKER,
            message=f"日回撤 {current_dd:.2%} 超过熔断阈值 {max_dd:.2%}，全天禁止开仓"
        )

    return RiskCheckResult.pass_result()


def leverage_cap_check(
    signal: Signal,
    context: RiskContext,
    config: Dict[str, Any],
    extra: Optional[Dict[str, Any]] = None,
) -> RiskCheckResult:
    """杠杆上限检查规则"""
    max_leverage = config.get("max_leverage", 10.0)
    signal_leverage = extra.get("leverage", config.get("default_leverage", 1.0))

    if signal_leverage > max_leverage:
        return RiskCheckResult.fail_result(
            reason_code=ReasonCode.HARD_FAIL_LEVERAGE_EXCEEDS_CAP,
            message=f"杠杆 {signal_leverage}x 超过上限 {max_leverage}x"
        )

    return RiskCheckResult.pass_result()


def concurrent_position_limit(
    signal: Signal,
    context: RiskContext,
    config: Dict[str, Any],
    extra: Optional[Dict[str, Any]] = None,
) -> RiskCheckResult:
    """并发仓位限制规则"""
    max_positions = config.get("max_concurrent_positions", 5)

    if signal.coin in context.positions:
        return RiskCheckResult.pass_result("已有同币种持仓，允许加仓")

    if context.active_positions_count >= max_positions:
        return RiskCheckResult.fail_result(
            reason_code=ReasonCode.HARD_FAIL_CONCURRENT_LIMIT,
            message=f"并发仓位 {context.active_positions_count} 达到上限 {max_positions}"
        )

    return RiskCheckResult.pass_result()


def consecutive_losses_limit(
    signal: Signal,
    context: RiskContext,
    config: Dict[str, Any],
    extra: Optional[Dict[str, Any]] = None,
) -> RiskCheckResult:
    """连续亏损限制规则"""
    max_consecutive = config.get("max_consecutive_losses", 5)

    if context.consecutive_losses >= max_consecutive:
        return RiskCheckResult.fail_result(
            reason_code=ReasonCode.HARD_FAIL_CONSECUTIVE_LOSSES,
            message=f"连续亏损 {context.consecutive_losses} 次，达到上限 {max_consecutive}"
        )

    return RiskCheckResult.pass_result()


def blackout_period_check(
    signal: Signal,
    context: RiskContext,
    config: Dict[str, Any],
    extra: Optional[Dict[str, Any]] = None,
) -> RiskCheckResult:
    """黑窗时段检查规则

    检查当前是否在黑窗时段（如宏观数据发布前后）。
    """
    blackout_windows = config.get("blackout_windows", [])

    if not blackout_windows:
        return RiskCheckResult.pass_result()

    now = datetime.now(timezone.utc)
    current_hour = now.hour
    current_minute = now.minute
    current_time = current_hour * 60 + current_minute

    for window in blackout_windows:
        start = window.get("start", "")
        end = window.get("end", "")

        try:
            start_h, start_m = map(int, start.split(":"))
            end_h, end_m = map(int, end.split(":"))
            start_min = start_h * 60 + start_m
            end_min = end_h * 60 + end_m

            if start_min <= current_time <= end_min:
                return RiskCheckResult.fail_result(
                    reason_code=ReasonCode.HARD_FAIL_BLACKOUT,
                    message=f"当前处于黑窗时段 {start}-{end} UTC，禁止开仓"
                )
        except (ValueError, AttributeError):
            continue

    return RiskCheckResult.pass_result()


def confidence_minimum(
    signal: Signal,
    context: RiskContext,
    config: Dict[str, Any],
    extra: Optional[Dict[str, Any]] = None,
) -> RiskCheckResult:
    """最低置信度检查规则

    - 低于硬阈值 → 拒绝
    - 低于软阈值 → 警告，仓位降级
    """
    hard_min = config.get("confidence_hard_min", 0.2)
    soft_min = config.get("confidence_soft_min", 0.4)

    if signal.confidence < hard_min:
        return RiskCheckResult.fail_result(
            reason_code=ReasonCode.FAIL_LOW_DIM,
            message=f"信号置信度 {signal.confidence:.2f} 低于硬阈值 {hard_min:.2f}"
        )

    if signal.confidence < soft_min:
        modifier = signal.confidence / soft_min
        return RiskCheckResult.degrade_result(
            reason_code=ReasonCode.SOFT_WARN_LOW_CONFIDENCE,
            modifier=modifier,
            message=f"信号置信度 {signal.confidence:.2f} 低于软阈值 {soft_min:.2f}，仓位×{modifier:.2f}"
        )

    return RiskCheckResult.pass_result()


def drawdown_warning_degrade(
    signal: Signal,
    context: RiskContext,
    config: Dict[str, Any],
    extra: Optional[Dict[str, Any]] = None,
) -> RiskCheckResult:
    """回撤警告降级规则

    回撤达到警告线时，仓位减半。

    阈值：
        - 5% ~ 8%: 警告，仓位减半
        - 8% ~ 10%: 仅允许减仓
    """
    warn_1 = config.get("drawdown_warn_1", 0.05)
    warn_2 = config.get("drawdown_warn_2", 0.08)
    current_dd = context.daily_drawdown_pct

    if current_dd >= warn_2:
        return RiskCheckResult.degrade_result(
            reason_code=ReasonCode.DEGRADE_DRAWDOWN_WARNING,
            modifier=0.25,
            message=f"日回撤 {current_dd:.2%} 达到严重警告线 {warn_2:.2%}，仓位×0.25"
        )

    if current_dd >= warn_1:
        return RiskCheckResult.degrade_result(
            reason_code=ReasonCode.DEGRADE_DRAWDOWN_WARNING,
            modifier=0.5,
            message=f"日回撤 {current_dd:.2%} 达到警告线 {warn_1:.2%}，仓位减半"
        )

    return RiskCheckResult.pass_result()


def strategy_exclusion_check(
    signal: Signal,
    context: RiskContext,
    config: Dict[str, Any],
    extra: Optional[Dict[str, Any]] = None,
) -> RiskCheckResult:
    """战略排除检查规则"""
    excluded_strategies = config.get("excluded_strategies", [])
    excluded_coins = config.get("excluded_coins", [])

    if signal.strategy and signal.strategy in excluded_strategies:
        return RiskCheckResult.fail_result(
            reason_code=ReasonCode.HARD_FAIL_STRATEGY_EXCLUDED,
            message=f"策略 '{signal.strategy}' 已被排除"
        )

    if signal.coin in excluded_coins:
        return RiskCheckResult.fail_result(
            reason_code=ReasonCode.HARD_FAIL_STRATEGY_EXCLUDED,
            message=f"币种 '{signal.coin}' 已被排除"
        )

    return RiskCheckResult.pass_result()
