"""
事后离场层 (ExitEngine)
========================
持仓风控与离场决策 — 决定何时离场。

四大优先级（与经典离场系统对齐）：
    P0 - L0 安全硬退出（永远一票否决）
    P1 - L1/L2 价值-风险评估（主体）
    P2 - Triple Barrier（三重屏障）
    P3 - 执行层行为约束
"""

from typing import Dict, List, Optional, Any
from dataclasses import dataclass

from .context import (
    PositionState,
    MarketSnapshot,
    RiskContext,
    ExitResult,
    ExitAction,
    ExitPriority,
    Direction,
)
from .registry import RuleRegistry, RuleCategory


class ExitEngine:
    """事后离场引擎

    对持仓进行持续的风险监控和离场决策，确保盈利最大化、亏损最小化。

    四层离场体系（按优先级执行，高优先级优先触发）：
        P0 - 安全硬退出：最大持仓时间、最大亏损、强平缓冲、周线反转
        P1 - 价值-风险评估：持仓风险/价值评估、动作映射
        P2 - 三重屏障：止损屏障、止盈屏障、时间屏障
        P3 - 行为约束：跟踪止损、分批减仓、冷却机制

    使用方式：
        engine = ExitEngine(registry, config)
        result = engine.check(position, market, context)
        if result.action == ExitAction.CLOSE:
            # 平仓
    """

    def __init__(
        self,
        registry: Optional[RuleRegistry] = None,
        config: Optional[Dict[str, Any]] = None,
    ):
        self.registry = registry if registry is not None else RuleRegistry()
        self.config = config or {}

    def check(
        self,
        position: PositionState,
        market: Optional[MarketSnapshot] = None,
        context: Optional[RiskContext] = None,
        extra: Optional[Dict[str, Any]] = None,
    ) -> ExitResult:
        """离场决策检查

        按优先级（P0→P3）执行所有启用的离场规则，返回最高优先级的离场动作。

        Args:
            position: 持仓状态
            market: 市场快照
            context: 风控上下文
            extra: 额外参数

        Returns:
            ExitResult 离场决策结果
        """
        extra = extra or {}
        best_result = ExitResult(action=ExitAction.HOLD, reason="")

        priority_order = [
            ExitPriority.P0_L0_HARD,
            ExitPriority.P1_VALUE_RISK,
            ExitPriority.P2_TRIPLE_BARRIER,
            ExitPriority.P3_BEHAVIORAL,
        ]

        rules = self.registry.get_enabled_rules(RuleCategory.EXIT)

        for rule_info in rules:
            handler = self.registry.get_handler(rule_info.name)
            if not handler:
                continue

            rule_config = self.config.get(rule_info.name, {})

            try:
                result = handler(
                    position=position,
                    market=market,
                    context=context,
                    config=rule_config,
                    extra=extra,
                )

                if not result or result.action == ExitAction.HOLD:
                    continue

                if self._is_higher_priority(result.priority, best_result.priority):
                    best_result = result

                if result.priority == ExitPriority.P0_L0_HARD:
                    break

            except Exception as e:
                continue

        return best_result

    def check_batch(
        self,
        positions: List[PositionState],
        market_map: Optional[Dict[str, MarketSnapshot]] = None,
        context: Optional[RiskContext] = None,
    ) -> Dict[str, ExitResult]:
        """批量检查多个持仓"""
        results = {}
        market_map = market_map or {}

        for position in positions:
            market = market_map.get(position.coin)
            results[position.coin] = self.check(position, market, context)

        return results

    def _is_higher_priority(self, p1: ExitPriority, p2: ExitPriority) -> bool:
        """判断p1是否比p2优先级高"""
        priority_order = {
            ExitPriority.P0_L0_HARD: 0,
            ExitPriority.P1_VALUE_RISK: 1,
            ExitPriority.P2_TRIPLE_BARRIER: 2,
            ExitPriority.P3_BEHAVIORAL: 3,
        }
        return priority_order.get(p1, 99) < priority_order.get(p2, 99)

    def calculate_stop_loss_price(
        self,
        position: PositionState,
        method: str = "atr",
    ) -> float:
        """计算止损价格

        Args:
            position: 持仓状态
            method: 止损方法 ('atr' | 'pct' | 'fixed')

        Returns:
            止损价格
        """
        if method == "pct":
            stop_pct = self.config.get("stop_loss_pct", 0.03)
            if position.is_long:
                return position.entry_price * (1 - stop_pct)
            else:
                return position.entry_price * (1 + stop_pct)

        if method == "atr":
            atr_mult = self.config.get("atr_stop_multiplier", 2.0)
            atr_value = position.entry_price * position.atr_pct
            if position.is_long:
                return position.entry_price - atr_value * atr_mult
            else:
                return position.entry_price + atr_value * atr_mult

        return position.entry_price * 0.97

    def calculate_take_profit_price(
        self,
        position: PositionState,
        method: str = "rr",
    ) -> float:
        """计算止盈价格

        Args:
            position: 持仓状态
            method: 止盈方法 ('rr' | 'pct' | 'atr')

        Returns:
            止盈价格
        """
        if method == "pct":
            tp_pct = self.config.get("take_profit_pct", 0.06)
            if position.is_long:
                return position.entry_price * (1 + tp_pct)
            else:
                return position.entry_price * (1 - tp_pct)

        if method == "rr":
            rr_ratio = self.config.get("rr_ratio", 2.0)
            stop_price = self.calculate_stop_loss_price(position)
            stop_distance = abs(position.entry_price - stop_price)
            if position.is_long:
                return position.entry_price + stop_distance * rr_ratio
            else:
                return position.entry_price - stop_distance * rr_ratio

        return position.entry_price * 1.03
