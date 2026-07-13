"""
事前门禁层 (PreTradeGate)
========================
交易前风控检查 — 决定是否允许开仓。

门禁优先级（与知识库对齐）：
    战略门禁(P0) → 杠杆门禁(P0) → 评分门禁 → 执行风险门禁 → 账户层门禁

任一阻断 = SKIP（Fail-Closed 原则）。
"""

from typing import Dict, List, Optional, Any
from dataclasses import dataclass

from .context import (
    Signal,
    RiskContext,
    RiskCheckResult,
    ReasonCode,
    Direction,
)
from .registry import RuleRegistry, RuleCategory


class PreTradeGate:
    """事前门禁层

    负责在交易执行前进行全面的风控检查，确保交易符合所有风险约束。

    门禁层级（按优先级执行）：
        1. 战略门禁 - 最高优先级，战略排除直接阻断
        2. 杠杆门禁 - 杠杆上限检查
        3. 评分门禁 - 多维度评分阈值
        4. 执行风险门禁 - 滑点、边缘值检查
        5. 账户层门禁 - 回撤、并发、连续亏损等

    使用方式：
        gate = PreTradeGate(registry, config)
        result = gate.check(signal, context)
        if result.passed:
            # 允许交易
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
        signal: Signal,
        context: RiskContext,
        extra: Optional[Dict[str, Any]] = None,
    ) -> RiskCheckResult:
        """执行事前风控检查

        按优先级顺序执行所有启用的门禁规则，遇到失败立即返回。

        Args:
            signal: 交易信号
            context: 风控上下文
            extra: 额外参数

        Returns:
            RiskCheckResult 检查结果
        """
        extra = extra or {}
        position_modifier = 1.0
        last_warn_reason = None

        rules = self.registry.get_enabled_rules(RuleCategory.GATE)

        for rule_info in rules:
            handler = self.registry.get_handler(rule_info.name)
            if not handler:
                continue

            rule_config = self.config.get(rule_info.name, {})

            try:
                result = handler(
                    signal=signal,
                    context=context,
                    config=rule_config,
                    extra=extra,
                )

                if not result.passed:
                    return result

                if result.position_modifier != 1.0:
                    position_modifier *= result.position_modifier

                if result.reason_code != ReasonCode.PASS:
                    last_warn_reason = result

            except Exception as e:
                return RiskCheckResult.fail_result(
                    reason_code=ReasonCode.HARD_FAIL_MISSING_CORE_DATA,
                    message=f"门禁规则 '{rule_info.name}' 执行失败: {e}"
                )

        result = RiskCheckResult.pass_result("所有门禁通过")
        result.position_modifier = position_modifier

        if last_warn_reason:
            result.reason_code = last_warn_reason.reason_code
            result.risk_level = last_warn_reason.risk_level
            result.details["warnings"] = last_warn_reason.message

        return result

    def check_batch(
        self,
        signals: List[Signal],
        context: RiskContext,
    ) -> Dict[str, RiskCheckResult]:
        """批量检查多个信号"""
        results = {}
        for signal in signals:
            results[signal.coin] = self.check(signal, context)
        return results
