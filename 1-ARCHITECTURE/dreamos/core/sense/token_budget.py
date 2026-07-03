"""
DreamOS S层 — Token 预算管理器

设计:
    - 5 级预算状态（健康/警告/低/严重/耗尽）
    - 按阶段分配预算（S层/A层/C层/G层）
    - 低预算时自动降级（减少 LLM 调用、缩短 prompt）
    - 预算耗尽时建议切换到经典指标系统

预算档位（与 SKILL 文档对齐）:
    - lean:     3000 tokens — 精简模式
    - standard: 6000 tokens — 标准模式
    - full:    10000 tokens — 完整模式

S 层预算分配:
    - 规则识别: 0 tokens（零消耗）
    - LLM 识别:  ~500 tokens/次
"""

from __future__ import annotations

from typing import Dict, Optional
from enum import Enum


# 预算档位
BUDGET_MODES = {
    "lean": 3000,
    "standard": 6000,
    "full": 10000,
}


# 各层默认预算分配比例
LAYER_BUDGET_RATIO = {
    "sense": 0.10,    # S 层: 10%
    "arrange": 0.05,   # A 层: 5%
    "compute": 0.75,   # C 层: 75%
    "graph_store": 0.10,  # G 层: 10%
}


class BudgetLevel(str, Enum):
    """预算健康度等级"""
    HEALTHY = "healthy"        # 健康: >60% 剩余
    WARNING = "warning"        # 警告: 60%-40%
    LOW = "low"                # 低: 40%-20%
    CRITICAL = "critical"      # 严重: 20%-5%
    EXHAUSTED = "exhausted"    # 耗尽: <5%


class TokenBudgetManager:
    """Token 预算管理器

    用法:
        budget = TokenBudgetManager(mode="standard")

        # 检查是否可以调用 LLM
        if budget.can_afford(500):
            result = llm.chat(...)
            budget.consume(result.tokens_total, layer="sense")

        # 获取当前状态
        level = budget.level()
        # → BudgetLevel.HEALTHY
    """

    def __init__(self, mode: str = "standard",
                 total: Optional[int] = None,
                 layer_ratios: Optional[Dict[str, float]] = None):
        if total is not None:
            self.total = total
        else:
            self.total = BUDGET_MODES.get(mode, 6000)
        self.mode = mode
        self.used = 0
        self._layer_used: Dict[str, int] = {}
        self._layer_ratios = layer_ratios or LAYER_BUDGET_RATIO

    # ── 核心方法 ───────────────────────────────────

    @property
    def remaining(self) -> int:
        """剩余 token"""
        return max(0, self.total - self.used)

    @property
    def usage_ratio(self) -> float:
        """已用比例 0-1"""
        if self.total == 0:
            return 1.0
        return self.used / self.total

    @property
    def remaining_ratio(self) -> float:
        """剩余比例 0-1"""
        return 1.0 - self.usage_ratio

    def level(self) -> BudgetLevel:
        """当前预算等级"""
        ratio = self.remaining_ratio
        if ratio >= 0.6:
            return BudgetLevel.HEALTHY
        elif ratio >= 0.4:
            return BudgetLevel.WARNING
        elif ratio >= 0.2:
            return BudgetLevel.LOW
        elif ratio >= 0.05:
            return BudgetLevel.CRITICAL
        else:
            return BudgetLevel.EXHAUSTED

    def can_afford(self, estimated_tokens: int) -> bool:
        """是否能负担指定 token 消耗"""
        return self.remaining >= estimated_tokens

    def consume(self, tokens: int, layer: str = "unknown") -> int:
        """消耗 token，返回实际消耗"""
        actual = min(tokens, self.remaining)
        self.used += actual
        self._layer_used[layer] = self._layer_used.get(layer, 0) + actual
        return actual

    def reset(self) -> None:
        """重置预算"""
        self.used = 0
        self._layer_used.clear()

    # ── 分层预算 ───────────────────────────────────

    def layer_budget(self, layer: str) -> int:
        """某层的预算上限"""
        ratio = self._layer_ratios.get(layer, 0.0)
        return int(self.total * ratio)

    def layer_used(self, layer: str) -> int:
        """某层已用 token"""
        return self._layer_used.get(layer, 0)

    def layer_remaining(self, layer: str) -> int:
        """某层剩余 token"""
        return max(0, self.layer_budget(layer) - self.layer_used(layer))

    def can_afford_layer(self, layer: str, tokens: int) -> bool:
        """某层是否能负担"""
        return self.layer_remaining(layer) >= tokens and self.can_afford(tokens)

    # ── 降级建议 ───────────────────────────────────

    def should_degrade_llm(self) -> bool:
        """是否应该减少 LLM 调用"""
        return self.level() in (BudgetLevel.LOW, BudgetLevel.CRITICAL, BudgetLevel.EXHAUSTED)

    def should_switch_classic(self) -> bool:
        """是否建议切换到经典指标系统"""
        return self.level() == BudgetLevel.EXHAUSTED

    def degradation_level(self) -> int:
        """降级等级 0-3（0=正常，3=最严重）"""
        level = self.level()
        if level == BudgetLevel.HEALTHY:
            return 0
        elif level == BudgetLevel.WARNING:
            return 1
        elif level == BudgetLevel.LOW:
            return 2
        else:
            return 3

    # ── 诊断 ───────────────────────────────────────

    def summary(self) -> Dict[str, any]:
        """预算摘要"""
        return {
            "mode": self.mode,
            "total": self.total,
            "used": self.used,
            "remaining": self.remaining,
            "usage_ratio": round(self.usage_ratio, 3),
            "level": self.level().value,
            "degradation_level": self.degradation_level(),
            "should_degrade_llm": self.should_degrade_llm(),
            "should_switch_classic": self.should_switch_classic(),
            "layer_used": dict(self._layer_used),
        }

    def __repr__(self) -> str:
        return (f"<TokenBudget mode={self.mode} used={self.used}/{self.total} "
                f"level={self.level().value}>")
