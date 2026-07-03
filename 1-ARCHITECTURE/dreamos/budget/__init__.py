"""
DreamOS Budget — 预算管理层

职责:
    - 全局 Token 预算管理（按周期/日/月/总计）
    - 层间预算分配与调度
    - 成本追踪与分析
    - 预算超限降级（切换到经典指标系统）

子模块:
    - global_budget.py  全局预算管理器
    - cost_tracker.py   成本追踪器

快速上手:
    from dreamos.budget import GlobalBudgetManager, CostTracker

    budget = GlobalBudgetManager(mode="standard")
    budget.begin_cycle("cycle_001")
    budget.consume(500, layer="sense")
    status = budget.status()

    tracker = CostTracker()
    tracker.record("cycle_001", "A0", 300, layer="compute")
    summary = tracker.summary()
"""

from dreamos.shared.state import State

from .global_budget import (
    GlobalBudgetManager, BudgetLevel, BUDGET_MODES,
    BudgetUsageRecord, DEFAULT_LAYER_RATIOS,
)
from .cost_tracker import CostTracker

__all__ = [
    # global budget
    "GlobalBudgetManager", "BudgetLevel", "BUDGET_MODES",
    "BudgetUsageRecord", "DEFAULT_LAYER_RATIOS",
    # cost tracking
    "CostTracker",
]
