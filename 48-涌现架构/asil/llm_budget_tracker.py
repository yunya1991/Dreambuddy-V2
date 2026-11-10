"""LLM 调用预算追踪 + 熔断。

SPEC v0.2 P0-1 + C12：Phase 1 硬约束零 LLM 消耗（目标 0%）。
Phase 2+ 启用实际预算（默认每日 50k tokens）。
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field


@dataclass
class LLMBudgetTracker:
    """LLM 预算追踪器。Phase 1 默认零消耗。"""

    daily_budget_tokens: int = 0  # Phase 1 默认 0
    pipeline_budget_tokens: int = 0  # Phase 1 默认 0
    daily_used: int = 0
    pipeline_used: int = 0
    reset_daily_after: float = field(default_factory=lambda: time.time() + 86400)

    # 熔断行为：True 时自动切回规则代理降级
    auto_downgrade: bool = True

    @property
    def is_phase1_zero(self) -> bool:
        """Phase 1 硬约束：预算 = 0 意味着不允许任何 LLM 调用。"""
        return self.daily_budget_tokens == 0

    def reset_daily(self) -> None:
        """每日零点重置。"""
        self.daily_used = 0
        self.pipeline_used = 0
        self.reset_daily_after = time.time() + 86400

    def reset_pipeline(self) -> None:
        """每 Pipeline 重置。"""
        self.pipeline_used = 0

    def record(self, tokens: int) -> None:
        """记录一次 LLM 调用消耗。"""
        if tokens < 0:
            raise ValueError("tokens must be non-negative")
        self.daily_used += tokens
        self.pipeline_used += tokens

    def check_daily(self) -> str:
        """检查每日预算。返回 'ok' / 'near_limit' / 'exceeded'。"""
        if self.daily_budget_tokens == 0:
            return "ok"  # Phase 1 不允许任何调用，record 不应该被触发
        ratio = self.daily_used / self.daily_budget_tokens
        if ratio >= 1.0:
            return "exceeded"
        if ratio >= 0.9:
            return "near_limit"
        return "ok"

    def check_pipeline(self) -> str:
        """检查单 Pipeline 预算。"""
        if self.pipeline_budget_tokens == 0:
            return "ok"
        ratio = self.pipeline_used / self.pipeline_budget_tokens
        if ratio >= 1.0:
            return "exceeded"
        if ratio >= 0.8:
            return "near_limit"
        return "ok"

    def should_downgrade(self) -> bool:
        """是否应自动切回规则代理降级。"""
        if not self.auto_downgrade:
            return False
        return self.check_daily() == "exceeded" or self.check_pipeline() == "exceeded"
