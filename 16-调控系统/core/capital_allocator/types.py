"""PACA 资金调配核心数据结构
================================

定义 CapitalAllocatorComponent 内部流转的全部数据类型：
- AllocatorMode:  调配模式（SHADOW 影子 / ACTIVE 实盘）
- HealthLevel:    健康等级（对齐 capital_control）
- CoinPerformance:  单币种绩效统计（Layer 1 产出）
- AllocationResult:  单币种资金调配结果（Layer 2+3 产出）
- AllocationSnapshot: 全局资金调配快照（evaluate() 输出）
"""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict


class AllocatorMode(str, Enum):
    """资金调配模式。

    - SHADOW: 影子模式（默认）——计算 PACA 仓位但不实际使用，仅记录对比
    - ACTIVE: 实盘模式——PACA 仓位实际影响开仓
    """

    SHADOW = "shadow"
    ACTIVE = "active"


class HealthLevel(str, Enum):
    """健康等级（对齐 capital_control）。"""

    HEALTHY = "HEALTHY"
    WARNING = "WARNING"
    CRITICAL = "CRITICAL"


@dataclass
class CoinPerformance:
    """单币种绩效统计（Layer 1 产出）。"""

    coin: str
    n_trades: int
    n_wins: int
    win_rate: float              # 胜率 = n_wins / n_trades
    avg_win_pct: float           # 平均盈利幅度
    avg_loss_pct: float          # 平均亏损幅度（绝对值，正数）
    w_l_ratio: float             # 盈亏比 = avg_win / avg_loss
    total_pnl: float             # 总盈亏 USDT
    last_trade_ts: float = 0.0   # 最近交易时间戳
    # Bayesian Shrinkage 后的值
    shrunk_win_rate: float = 0.0
    shrunk_w_l_ratio: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class AllocationResult:
    """单币种资金调配结果（Layer 2+3 产出）。"""

    coin: str
    source_tag: str               # bcrm/bdsm/evolution/strategy
    kelly_f: float                # 原始 Kelly 分数
    half_kelly_f: float           # Half-Kelly 分数
    position_pct: float           # 最终仓位比例 [0, MAX_PCT]
    subpool_budget: float         # 子池预算 USDT
    subpool_weight: float         # 子池权重
    expansion_mult: float         # 全局扩张乘数
    final_position_pct: float     # position_pct * expansion_mult
    fallback_used: bool = False
    fallback_reason: str = ""
    timestamp: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class AllocationSnapshot:
    """全局资金调配快照（evaluate() 输出，对齐 CapitalSnapshot 模式）。"""

    timestamp: str
    mode: AllocatorMode
    health: HealthLevel
    global_win_rate: float              # 全局胜率
    global_w_l_ratio: float              # 全局盈亏比
    expansion_mult: float                # 全局扩张乘数
    by_coin: Dict[str, AllocationResult]     # 按币种分组
    by_subpool: Dict[str, float]            # 按子池分组（权重）
    total_trades_analyzed: int
    recommendations: Dict[str, str] = field(default_factory=dict)
    extra: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "timestamp": self.timestamp,
            "mode": self.mode.value,
            "health": self.health.value,
            "global_win_rate": round(self.global_win_rate, 4),
            "global_w_l_ratio": round(self.global_w_l_ratio, 4),
            "expansion_mult": round(self.expansion_mult, 4),
            "by_coin": {k: v.to_dict() for k, v in self.by_coin.items()},
            "by_subpool": dict(self.by_subpool),
            "total_trades_analyzed": self.total_trades_analyzed,
            "recommendations": dict(self.recommendations),
            "extra": dict(self.extra),
        }


def now_iso() -> str:
    """生成 UTC ISO 时间戳字符串。"""
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


__all__ = [
    "AllocatorMode",
    "HealthLevel",
    "CoinPerformance",
    "AllocationResult",
    "AllocationSnapshot",
    "now_iso",
]
