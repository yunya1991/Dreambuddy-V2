"""
DreamOS Budget — 全局预算管理器

职责:
    1. 全周期 Token 预算管理
    2. 层间预算分配与调度
    3. 预算超限检测与降级
    4. 成本追踪与报告

与 S 层 token_budget 的区别:
    S 层的 TokenBudgetManager 是单周期内 S 层的预算管理
    本模块是全局的、跨周期的预算总控

预算分级:
    - per_cycle: 单次执行的预算上限
    - per_day: 每日预算上限
    - per_month: 每月预算上限
    - total: 总预算（可选）

降级策略:
    - 预算充足: 正常执行
    - 预算预警: 减少可选节点
    - 预算紧张: 跳过 LLM 识别，纯规则模式
    - 预算耗尽: 切换到经典指标系统（零 Token）
"""

from __future__ import annotations

import time
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field
from datetime import datetime, date, timedelta


# ============================================================
# 预算档位
# ============================================================

BUDGET_MODES = {
    "lean": {
        "per_cycle": 3000,
        "per_day": 30000,
        "per_month": 500000,
    },
    "standard": {
        "per_cycle": 6000,
        "per_day": 60000,
        "per_month": 1000000,
    },
    "full": {
        "per_cycle": 10000,
        "per_day": 100000,
        "per_month": 2000000,
    },
}


# ============================================================
# 预算状态
# ============================================================

class BudgetLevel(str):
    """预算健康度"""
    HEALTHY = "healthy"        # 充足
    WARNING = "warning"        # 预警
    TIGHT = "tight"            # 紧张
    CRITICAL = "critical"      # 严重不足
    EXHAUSTED = "exhausted"    # 耗尽


# ============================================================
# 层预算分配比例
# ============================================================

DEFAULT_LAYER_RATIOS = {
    "sense": 0.10,       # S 层: 10%
    "arrange": 0.05,      # A 层: 5%
    "compute": 0.75,      # C 层: 75%
    "graph_store": 0.05,  # G 层: 5%
    "evolution": 0.05,    # E 层: 5%
}


# ============================================================
# 预算使用记录
# ============================================================

@dataclass
class BudgetUsageRecord:
    """预算使用记录"""
    cycle_id: str
    tokens: int
    layer: str = "unknown"
    timestamp: float = field(default_factory=time.time)
    status: str = "success"   # success / degraded / failed

    def to_dict(self) -> Dict[str, Any]:
        return {
            "cycle_id": self.cycle_id,
            "tokens": self.tokens,
            "layer": self.layer,
            "timestamp": self.timestamp,
            "status": self.status,
        }


# ============================================================
# 全局预算管理器
# ============================================================

class GlobalBudgetManager:
    """全局预算管理器

    管理全周期、跨天、跨月的 Token 预算。

    用法:
        budget = GlobalBudgetManager(mode="standard")

        # 开始一个周期
        budget.begin_cycle()

        # 消耗 Token
        budget.consume(500, layer="sense")

        # 检查是否可以调用 LLM
        if budget.can_afford(1000, layer="compute"):
            ...

        # 结束周期
        budget.end_cycle(tokens_total=3500)

        # 获取状态
        status = budget.status()
        # → {"level": "healthy", "per_cycle_used": 3500, ...}
    """

    def __init__(self,
                 mode: str = "standard",
                 per_cycle: Optional[int] = None,
                 per_day: Optional[int] = None,
                 per_month: Optional[int] = None,
                 total: Optional[int] = None,
                 layer_ratios: Optional[Dict[str, float]] = None):
        self._mode = mode
        mode_conf = BUDGET_MODES.get(mode, BUDGET_MODES["standard"])

        self._per_cycle = per_cycle or mode_conf["per_cycle"]
        self._per_day = per_day or mode_conf["per_day"]
        self._per_month = per_month or mode_conf["per_month"]
        self._total = total
        self._layer_ratios = layer_ratios or DEFAULT_LAYER_RATIOS

        # 使用计数
        self._cycle_used: int = 0
        self._day_used: int = 0
        self._month_used: int = 0
        self._total_used: int = 0
        self._current_cycle_id: str = ""
        self._current_date: str = ""
        self._current_month: str = ""

        # 层使用记录
        self._layer_usage: Dict[str, int] = {}

        # 历史记录
        self._history: List[BudgetUsageRecord] = []
        self._max_history = 1000

        # 当前周期内的层使用
        self._cycle_layer_used: Dict[str, int] = {}

        self._init_today()

    # ── 周期管理 ───────────────────────────────────

    def begin_cycle(self, cycle_id: str = "") -> str:
        """开始一个新的预算周期

        Args:
            cycle_id: 周期 ID（空则自动生成）

        Returns:
            cycle_id
        """
        self._check_date_rollover()
        self._cycle_used = 0
        self._cycle_layer_used = {}
        self._current_cycle_id = cycle_id or f"cycle_{int(time.time())}"
        return self._current_cycle_id

    def end_cycle(self, tokens_total: Optional[int] = None,
                  status: str = "success") -> int:
        """结束当前周期

        Args:
            tokens_total: 实际总消耗（None=用累积值）
            status: 周期状态 (success/degraded/failed)

        Returns:
            本周期消耗的 token
        """
        used = tokens_total if tokens_total is not None else self._cycle_used
        self._day_used += used
        self._month_used += used
        if self._total is not None:
            self._total_used += used

        # 记录历史
        self._history.append(BudgetUsageRecord(
            cycle_id=self._current_cycle_id,
            tokens=used,
            status=status,
        ))
        if len(self._history) > self._max_history:
            self._history = self._history[-self._max_history:]

        self._current_cycle_id = ""
        self._cycle_used = 0
        self._cycle_layer_used = {}
        return used

    # ── Token 消耗 ────────────────────────────────

    def consume(self, tokens: int, layer: str = "unknown") -> int:
        """消耗 Token

        Args:
            tokens: 消耗的 token 数
            layer: 所属层

        Returns:
            实际消耗的 token 数（受预算限制）
        """
        self._check_date_rollover()

        # 计算可消耗的最大数量
        remaining = self.remaining_per_cycle
        actual = min(tokens, max(0, remaining))

        self._cycle_used += actual

        # 层统计
        self._cycle_layer_used[layer] = self._cycle_layer_used.get(layer, 0) + actual
        self._layer_usage[layer] = self._layer_usage.get(layer, 0) + actual

        return actual

    def can_afford(self, tokens: int, layer: Optional[str] = None) -> bool:
        """检查是否能负担指定消耗"""
        if self.remaining_per_cycle < tokens:
            return False
        if self.remaining_per_day < tokens:
            return False
        if self.remaining_per_month < tokens:
            return False
        if self._total is not None and self.remaining_total < tokens:
            return False
        if layer:
            layer_budget = self.layer_budget_per_cycle(layer)
            layer_used = self._cycle_layer_used.get(layer, 0)
            if layer_budget - layer_used < tokens:
                return False
        return True

    # ── 剩余预算 ──────────────────────────────────

    @property
    def per_cycle_budget(self) -> int:
        return self._per_cycle

    @property
    def used_per_cycle(self) -> int:
        return self._cycle_used

    @property
    def remaining_per_cycle(self) -> int:
        return max(0, self._per_cycle - self._cycle_used)

    @property
    def used_per_day(self) -> int:
        return self._day_used + self._cycle_used

    @property
    def remaining_per_day(self) -> int:
        return max(0, self._per_day - self.used_per_day)

    @property
    def used_per_month(self) -> int:
        return self._month_used + self._cycle_used

    @property
    def remaining_per_month(self) -> int:
        return max(0, self._per_month - self.used_per_month)

    @property
    def remaining_total(self) -> int:
        if self._total is None:
            return 999999999
        return max(0, self._total - (self._total_used + self._cycle_used))

    # ── 层预算 ────────────────────────────────────

    def layer_budget_per_cycle(self, layer: str) -> int:
        """某层的周期预算"""
        ratio = self._layer_ratios.get(layer, 0.0)
        return int(self._per_cycle * ratio)

    def layer_used_per_cycle(self, layer: str) -> int:
        """某层本周期已用"""
        return self._cycle_layer_used.get(layer, 0)

    def layer_remaining_per_cycle(self, layer: str) -> int:
        """某层本周期剩余"""
        return max(0, self.layer_budget_per_cycle(layer) - self.layer_used_per_cycle(layer))

    # ── 预算状态 ──────────────────────────────────

    def level(self) -> str:
        """当前预算健康度（按最紧张的维度）"""
        levels = []
        # 周期预算
        cycle_ratio = self.used_per_cycle / max(1, self._per_cycle)
        levels.append(self._ratio_to_level(cycle_ratio))
        # 日预算
        day_ratio = self.used_per_day / max(1, self._per_day)
        levels.append(self._ratio_to_level(day_ratio))
        # 月预算
        month_ratio = self.used_per_month / max(1, self._per_month)
        levels.append(self._ratio_to_level(month_ratio))

        # 返回最差的状态
        order = [BudgetLevel.EXHAUSTED, BudgetLevel.CRITICAL,
                 BudgetLevel.TIGHT, BudgetLevel.WARNING, BudgetLevel.HEALTHY]
        for lvl in order:
            if lvl in levels:
                return lvl
        return BudgetLevel.HEALTHY

    def _ratio_to_level(self, ratio: float) -> str:
        if ratio >= 0.95:
            return BudgetLevel.EXHAUSTED
        elif ratio >= 0.8:
            return BudgetLevel.CRITICAL
        elif ratio >= 0.6:
            return BudgetLevel.TIGHT
        elif ratio >= 0.4:
            return BudgetLevel.WARNING
        return BudgetLevel.HEALTHY

    def should_degrade_llm(self) -> bool:
        """是否应该减少 LLM 调用"""
        return self.level() in (BudgetLevel.TIGHT, BudgetLevel.CRITICAL, BudgetLevel.EXHAUSTED)

    def should_use_classic_only(self) -> bool:
        """是否应该只用经典指标（零 Token）"""
        return self.level() == BudgetLevel.EXHAUSTED

    def degradation_level(self) -> int:
        """降级等级 0-3"""
        level = self.level()
        if level == BudgetLevel.HEALTHY:
            return 0
        elif level == BudgetLevel.WARNING:
            return 1
        elif level == BudgetLevel.TIGHT:
            return 2
        else:
            return 3

    # ── 状态报告 ──────────────────────────────────

    def status(self) -> Dict[str, Any]:
        """预算状态报告"""
        return {
            "mode": self._mode,
            "level": self.level(),
            "degradation_level": self.degradation_level(),
            "should_degrade_llm": self.should_degrade_llm(),
            "should_use_classic_only": self.should_use_classic_only(),
            "per_cycle": {
                "budget": self._per_cycle,
                "used": self.used_per_cycle,
                "remaining": self.remaining_per_cycle,
                "usage_ratio": round(self.used_per_cycle / max(1, self._per_cycle), 3),
            },
            "per_day": {
                "budget": self._per_day,
                "used": self.used_per_day,
                "remaining": self.remaining_per_day,
                "usage_ratio": round(self.used_per_day / max(1, self._per_day), 3),
            },
            "per_month": {
                "budget": self._per_month,
                "used": self.used_per_month,
                "remaining": self.remaining_per_month,
                "usage_ratio": round(self.used_per_month / max(1, self._per_month), 3),
            },
            "layer_usage": dict(self._cycle_layer_used),
            "current_cycle": self._current_cycle_id,
        }

    # ── 内部方法 ──────────────────────────────────

    def _init_today(self):
        today = date.today()
        self._current_date = today.isoformat()
        self._current_month = today.strftime("%Y-%m")

    def _check_date_rollover(self):
        """检查日期变化，重置日/月计数"""
        today = date.today()
        today_str = today.isoformat()
        month_str = today.strftime("%Y-%m")

        if today_str != self._current_date:
            self._day_used = 0
            self._current_date = today_str

        if month_str != self._current_month:
            self._month_used = 0
            self._current_month = month_str

    # ── 历史查询 ──────────────────────────────────

    def history(self, limit: int = 20) -> List[Dict[str, Any]]:
        """获取历史使用记录"""
        return [r.to_dict() for r in self._history[-limit:]]

    @property
    def total_cycles(self) -> int:
        return len(self._history)

    def __repr__(self) -> str:
        return (f"<GlobalBudget mode={self._mode} "
                f"cycle={self.used_per_cycle}/{self._per_cycle} "
                f"level={self.level()}>")
