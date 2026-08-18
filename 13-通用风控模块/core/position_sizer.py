"""
仓位管理层 (PositionSizer)
==========================
仓位计算与风险管理 — 决定开多大仓位。

核心能力：
    - 风险预算驱动的基础仓位计算
    - 置信度/波动率动态调整
    - 马丁加仓策略（可插拔）
    - 并发仓位限制
    - 仓位分级（轻仓/中仓/重仓）
"""

from typing import Any, Dict, List, Optional

from .context import (
    PositionSizeResult,
    RiskContext,
    Signal,
)
from .registry import RuleCategory, RuleRegistry


class PositionSizer:
    """仓位管理层

    负责计算合适的仓位大小，确保单笔交易风险在可接受范围内。

    计算流程：
        1. 基础风险预算 → risk_per_trade = equity × risk_pct
        2. 策略调整 → 基于置信度/波动率/战略
        3. 仓位转换 → 根据止损距离计算仓位大小
        4. 约束检查 → 最大仓位、最小仓位、并发限制

    使用方式：
        sizer = PositionSizer(registry, config)
        size = sizer.calculate(signal, context)
    """

    def __init__(
        self,
        registry: Optional[RuleRegistry] = None,
        config: Optional[Dict[str, Any]] = None,
    ):
        self.registry = registry if registry is not None else RuleRegistry()
        self.config = config or {}

    def calculate(
        self,
        signal: Signal,
        context: RiskContext,
        position_modifier: float = 1.0,
        extra: Optional[Dict[str, Any]] = None,
    ) -> PositionSizeResult:
        """计算仓位大小

        Args:
            signal: 交易信号
            context: 风控上下文
            position_modifier: 仓位调整系数（来自门禁降级）
            extra: 额外参数

        Returns:
            PositionSizeResult 仓位计算结果
        """
        extra = extra or {}
        result = PositionSizeResult()

        base_risk = self._calculate_base_risk(context)
        base_risk *= position_modifier

        adjusted_risk = base_risk
        details = {"base_risk": base_risk}

        rules = self.registry.get_enabled_rules(RuleCategory.POSITION)
        for rule_info in rules:
            handler = self.registry.get_handler(rule_info.name)
            if not handler:
                continue

            rule_config = self.config.get(rule_info.name, {})

            try:
                rule_result = handler(
                    signal=signal,
                    context=context,
                    base_risk=adjusted_risk,
                    config=rule_config,
                    extra=extra,
                )

                if hasattr(rule_result, "adjusted_risk"):
                    adjusted_risk = rule_result.adjusted_risk
                    details[f"{rule_info.name}_risk"] = adjusted_risk

                if hasattr(rule_result, "details"):
                    details.update(rule_result.details)

            except Exception as e:
                details[f"{rule_info.name}_error"] = str(e)

        entry_price = signal.entry_price or extra.get("current_price", 0)
        stop_loss = signal.stop_loss_price or extra.get("stop_loss_price", 0)

        if entry_price > 0 and stop_loss > 0:
            stop_distance_pct = abs(entry_price - stop_loss) / entry_price
        else:
            stop_distance_pct = self.config.get("default_stop_pct", 0.02)

        if stop_distance_pct > 0:
            base_size_usdt = adjusted_risk / stop_distance_pct
        else:
            base_size_usdt = adjusted_risk

        max_position_usdt = context.total_equity * self.config.get("max_position_pct", 0.25)
        base_size_usdt = min(base_size_usdt, max_position_usdt)
        base_size_usdt = max(base_size_usdt, self.config.get("min_position_usdt", 1.0))

        result.base_size_usdt = base_size_usdt
        result.risk_per_trade_usdt = adjusted_risk
        result.leverage = self.config.get("leverage", 1.0)
        result.position_tier = self._get_position_tier(base_size_usdt, context.total_equity)
        result.details = details

        if entry_price > 0:
            result.base_size_coins = base_size_usdt / entry_price

        result.max_addons = self.config.get("max_addons", 0)
        if result.max_addons > 0:
            result.addon_sizes = self._calculate_addon_sizes(base_size_usdt, result.max_addons)

        return result

    def _calculate_base_risk(self, context: RiskContext) -> float:
        """计算基础风险预算"""
        risk_pct = self.config.get("risk_per_trade_pct", 0.02)
        base_risk = context.total_equity * risk_pct

        max_risk = context.total_equity * self.config.get("max_risk_per_trade_pct", 0.05)
        return min(base_risk, max_risk)

    def _calculate_addon_sizes(self, base_size: float, max_addons: int) -> List[float]:
        """计算马丁加仓大小"""
        addon_pct = self.config.get("addon_pct", 0.5)
        sizes = []
        for i in range(1, max_addons + 1):
            sizes.append(base_size * addon_pct * i)
        return sizes

    def _get_position_tier(self, position_usdt: float, equity: float) -> str:
        """仓位分级"""
        if equity <= 0:
            return "trial"

        ratio = position_usdt / equity

        if ratio >= 0.20:
            return "heavy"
        elif ratio >= 0.10:
            return "medium"
        elif ratio >= 0.05:
            return "moderate"
        elif ratio >= 0.02:
            return "light"
        else:
            return "trial"

    def calculate_martin_addon(
        self,
        position: Any,
        context: RiskContext,
        addon_index: int,
    ) -> float:
        """计算马丁加仓大小

        Args:
            position: 当前持仓
            context: 风控上下文
            addon_index: 加仓序号（从1开始）

        Returns:
            加仓金额（USDT）
        """
        base_size = position.position_size * position.entry_price
        addon_pct = self.config.get("addon_pct", 0.5)
        addon_size = base_size * addon_pct * addon_index

        max_addon_usdt = context.total_equity * self.config.get("max_position_pct", 0.25)
        return min(addon_size, max_addon_usdt)
