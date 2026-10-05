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

    注意:
        - enabled=False（默认）时，预算管理完全关闭：
          can_afford/can_afford_layer 始终返回 True，
          consume 不扣除，should_degrade_llm 始终返回 False。
        - 这是因为分析类任务可能较长，预算耗尽会导致 LLM 被跳过。
        - 如需启用预算控制，显式传 enabled=True。
    """

    # 预算关闭时的虚拟剩余量（足够大，不会触发任何限制）
    _UNLIMITED = 10**9

    def __init__(self, mode: str = "standard",
                 total: Optional[int] = None,
                 layer_ratios: Optional[Dict[str, float]] = None,
                 enabled: bool = False):
        if total is not None:
            self.total = total
        else:
            self.total = BUDGET_MODES.get(mode, 6000)
        self.mode = mode
        self.enabled = enabled
        self.used = 0
        self._layer_used: Dict[str, int] = {}
        self._layer_ratios = layer_ratios or LAYER_BUDGET_RATIO

    # ── 核心方法 ───────────────────────────────────

    @property
    def remaining(self) -> int:
        """剩余 token（预算关闭时返回虚拟大值）"""
        if not self.enabled:
            return self._UNLIMITED
        return max(0, self.total - self.used)

    @property
    def usage_ratio(self) -> float:
        """已用比例 0-1"""
        if not self.enabled:
            return 0.0
        if self.total == 0:
            return 1.0
        return self.used / self.total

    @property
    def remaining_ratio(self) -> float:
        """剩余比例 0-1"""
        if not self.enabled:
            return 1.0
        return 1.0 - self.usage_ratio

    def level(self) -> BudgetLevel:
        """当前预算等级（预算关闭时始终 HEALTHY）"""
        if not self.enabled:
            return BudgetLevel.HEALTHY
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
        """是否能负担指定 token 消耗（预算关闭时始终 True）"""
        if not self.enabled:
            return True
        return self.remaining >= estimated_tokens

    def consume(self, tokens: int, layer: str = "unknown") -> int:
        """消耗 token，返回实际消耗（预算关闭时不扣除，返回请求量）"""
        if not self.enabled:
            return tokens
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
        """某层的预算上限（预算关闭时返回虚拟大值）"""
        if not self.enabled:
            return self._UNLIMITED
        ratio = self._layer_ratios.get(layer, 0.0)
        return int(self.total * ratio)

    def layer_used(self, layer: str) -> int:
        """某层已用 token"""
        return self._layer_used.get(layer, 0)

    def layer_remaining(self, layer: str) -> int:
        """某层剩余 token（预算关闭时返回虚拟大值）"""
        if not self.enabled:
            return self._UNLIMITED
        return max(0, self.layer_budget(layer) - self.layer_used(layer))

    def can_afford_layer(self, layer: str, tokens: int) -> bool:
        """某层是否能负担（预算关闭时始终 True）"""
        if not self.enabled:
            return True
        return self.layer_remaining(layer) >= tokens and self.can_afford(tokens)

    # ── 降级建议 ───────────────────────────────────

    def should_degrade_llm(self) -> bool:
        """是否应该减少 LLM 调用（预算关闭时始终 False）"""
        if not self.enabled:
            return False
        return self.level() in (BudgetLevel.LOW, BudgetLevel.CRITICAL, BudgetLevel.EXHAUSTED)

    def should_switch_classic(self) -> bool:
        """是否建议切换到经典指标系统（预算关闭时始终 False）"""
        if not self.enabled:
            return False
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
