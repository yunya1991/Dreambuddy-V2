"""
资金调控核心数据结构
====================

定义 CapitalControlComponent 内部流转的全部数据类型：
- CapitalMode:  调控模式（固定金额 / 动态资金）
- AccountType:  账户类型枚举（OKX 实盘/OKX 模拟/Hyperliquid/Aster）
- CapitalResult: 单系统资金查询结果（由各 rule handler 返回）
- CapitalSnapshot: 全局资金快照（由 evaluate 聚合输出）

并提供健康等级判定 assess_health() 辅助函数。
"""

from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional


# ---------------------------------------------------------------------------
# 枚举
# ---------------------------------------------------------------------------


class CapitalMode(str, Enum):
    """资金调控模式。

    - FIXED:   固定金额模式——始终使用 capital_control.json 的静态预算
    - DYNAMIC: 动态资金模式（默认）——优先实时查询，失败时三级降级
    """

    FIXED = "fixed"
    DYNAMIC = "dynamic"


class AccountType(str, Enum):
    """账户类型枚举，对应 4 类物理账户。"""

    OKX_LIVE = "okx_live"
    OKX_SIMULATED = "okx_simulated"
    HYPERLIQUID = "hyperliquid"
    ASTER = "aster"
    UNKNOWN = "unknown"


class HealthLevel(str, Enum):
    """健康等级。"""

    HEALTHY = "HEALTHY"
    WARNING = "WARNING"
    CRITICAL = "CRITICAL"


# ---------------------------------------------------------------------------
# 结果 / 快照
# ---------------------------------------------------------------------------


@dataclass
class CapitalResult:
    """单交易系统（单账户）的资金查询结果。

    由每条 capital rule handler 产出。
    """

    system: str
    account_type: AccountType
    mode: CapitalMode
    total_eq: float
    avail_balance: float
    used_margin: float
    used_pct: float
    fallback_used: bool = False
    fallback_reason: str = ""
    timestamp: str = ""
    extra: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["account_type"] = self.account_type.value
        d["mode"] = self.mode.value
        return d


@dataclass
class CapitalSnapshot:
    """全局资金快照——evaluate() 输出的主数据结构。"""

    timestamp: str
    mode: CapitalMode
    by_system: Dict[str, CapitalResult]
    total_equity: float
    total_avail: float
    total_used: float
    overall_used_pct: float
    health: HealthLevel
    recommendations: Dict[str, str] = field(default_factory=dict)
    by_account: Dict[str, CapitalResult] = field(default_factory=dict)
    extra: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "timestamp": self.timestamp,
            "mode": self.mode.value,
            "health": self.health.value,
            "by_system": {k: v.to_dict() for k, v in self.by_system.items()},
            "by_account": {k: v.to_dict() for k, v in self.by_account.items()},
            "totals": {
                "total_equity": round(self.total_equity, 2),
                "total_avail": round(self.total_avail, 2),
                "total_used": round(self.total_used, 2),
                "overall_used_pct": round(self.overall_used_pct, 2),
            },
            "recommendations": dict(self.recommendations),
            "extra": dict(self.extra),
        }


# ---------------------------------------------------------------------------
# 辅助
# ---------------------------------------------------------------------------


def now_iso() -> str:
    """生成 UTC ISO 时间戳字符串。"""
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def assess_health(
    overall_used_pct: float,
    any_system_fallback: bool,
    any_system_unavailable: bool,
    thresholds: Optional[Dict[str, float]] = None,
) -> HealthLevel:
    """按 Spec 3.4 节判定全局健康等级。

    Args:
        overall_used_pct:   全局保证金使用率（0-100 的百分比）
        any_system_fallback: 是否存在任一系统降级到静态值
        any_system_unavailable: 是否存在任一系统 equity 查询不可用（total_eq=0 且 fallback）
        thresholds: 可选阈值覆盖，键: healthy_used_pct_max / warning_used_pct_max
    """
    t = thresholds or {}
    healthy_max = float(t.get("healthy_used_pct_max", 50.0))
    warning_max = float(t.get("warning_used_pct_max", 80.0))

    if overall_used_pct >= warning_max or any_system_unavailable:
        return HealthLevel.CRITICAL
    if overall_used_pct >= healthy_max or any_system_fallback:
        return HealthLevel.WARNING
    return HealthLevel.HEALTHY


def calc_margin_pressure(used_pct: float) -> str:
    """将单系统保证金使用率映射为 LOW / MEDIUM / HIGH。"""
    if used_pct >= 80.0:
        return "HIGH"
    if used_pct >= 50.0:
        return "MEDIUM"
    return "LOW"


__all__ = [
    "CapitalMode",
    "AccountType",
    "HealthLevel",
    "CapitalResult",
    "CapitalSnapshot",
    "assess_health",
    "calc_margin_pressure",
    "now_iso",
]
