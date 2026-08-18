"""
移动止盈核心数据结构
======================

定义 TrailingStopComponent 内部流转的全部数据类型：
- TrailingAction:  追踪动作枚举（HOLD / TRIGGER_CLOSE / ARM）
- TrailingStatus:  单持仓追踪状态枚举（IDLE / ARMED / TRIGGERED / CLOSED）
- TrailingState:   单持仓追踪状态（持久化用）
- TrailingResult:  单持仓追踪评估结果
- TrailingSnapshot: 全局追踪快照（由 evaluate 聚合输出）

并提供 ATR 追踪价计算辅助函数。
"""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional


# ---------------------------------------------------------------------------
# 枚举
# ---------------------------------------------------------------------------


class TrailingAction(str, Enum):
    """追踪评估输出的动作。"""

    HOLD = "HOLD"               # 无动作：未激活或未触发
    ARM = "ARM"                 # 激活追踪：本次评估首次达到 arm 阈值
    TRIGGER_CLOSE = "TRIGGER_CLOSE"  # 触发平仓：价格跌破追踪线


class TrailingStatus(str, Enum):
    """单持仓的追踪阶段状态。"""

    IDLE = "IDLE"               # 未激活：盈利未达 arm 阈值
    ARMED = "ARMED"             # 已激活：追踪运行中
    TRIGGERED = "TRIGGERED"     # 已触发：待执行平仓（防止重复触发）
    CLOSED = "CLOSED"           # 已平仓：追踪生命周期结束


# ---------------------------------------------------------------------------
# 单持仓追踪状态（持久化）
# ---------------------------------------------------------------------------


@dataclass
class TrailingState:
    """单持仓追踪状态——持久化到 JSON 文件，重启后恢复。

    主键：(system, coin, side)
    """

    system: str                              # 所属系统，如 v15_martin
    coin: str                                # 币种，如 BTC-USDT
    side: str                                # long / short
    status: TrailingStatus = TrailingStatus.IDLE

    entry_price: float = 0.0                 # 开仓均价
    leverage: float = 1.0                    # 杠杆倍数
    position_size: float = 0.0               # 仓位数量

    # 价格高点追踪（自激活后或自开仓后）
    peak_price: float = 0.0                  # 持仓期间最高价（做多） / 最低价（做空）
    peak_ts: str = ""                        # 峰值出现时间

    # 激活 & 追踪参数
    armed_ts: str = ""                       # 激活时间戳（ARM 时刻）
    arm_pnl_eff_pct: float = 0.0             # 激活时的有效收益率（含杠杆）
    atr_period: int = 14                     # ATR 周期
    atr_multiplier: float = 2.5              # ATR 倍数
    min_trail_pct: float = 0.03              # 最小追踪百分比（防 ATR 过小）
    arm_threshold_pct: float = 0.20          # 激活有效收益率阈值（含杠杆，默认 20%）

    # 追踪止损价（每次轮询更新）
    trailing_stop_price: float = 0.0
    current_atr: float = 0.0
    current_price: float = 0.0

    # 触发记录
    triggered_ts: str = ""
    triggered_price: float = 0.0
    trigger_reason: str = ""                 # "price_below_trail" / "price_above_trail"
    locked_profit_pct: float = 0.0           # 触发时相对开仓的有效收益率

    # 元数据
    created_ts: str = ""
    updated_ts: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)

    # ------------------------------------------------------------------
    # 辅助方法
    # ------------------------------------------------------------------

    @property
    def state_key(self) -> str:
        return f"{self.system}:{self.coin}:{self.side}"

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["status"] = self.status.value
        return d

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "TrailingState":
        status_raw = d.get("status", TrailingStatus.IDLE.value)
        try:
            status = TrailingStatus(status_raw)
        except ValueError:
            status = TrailingStatus.IDLE
        kwargs = dict(d)
        kwargs["status"] = status
        return cls(**kwargs)


# ---------------------------------------------------------------------------
# 评估结果 / 全局快照
# ---------------------------------------------------------------------------


@dataclass
class TrailingResult:
    """单持仓一次 evaluate 的输出结果。"""

    state_key: str
    system: str
    coin: str
    side: str
    action: TrailingAction
    status: TrailingStatus
    current_pnl_eff_pct: float = 0.0          # 当前有效收益率（含杠杆）
    peak_price: float = 0.0
    trailing_stop_price: float = 0.0
    current_atr: float = 0.0
    trail_distance_pct: float = 0.0            # 追踪距离占 peak_price 的百分比
    locked_profit_pct: float = 0.0             # 若触发，锁定的有效盈利
    reason: str = ""                           # 人类可读原因
    details: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "state_key": self.state_key,
            "system": self.system,
            "coin": self.coin,
            "side": self.side,
            "action": self.action.value,
            "status": self.status.value,
            "current_pnl_eff_pct": round(self.current_pnl_eff_pct, 4),
            "peak_price": round(self.peak_price, 4),
            "trailing_stop_price": round(self.trailing_stop_price, 4),
            "current_atr": round(self.current_atr, 6),
            "trail_distance_pct": round(self.trail_distance_pct, 4),
            "locked_profit_pct": round(self.locked_profit_pct, 4),
            "reason": self.reason,
            "details": dict(self.details),
        }


@dataclass
class TrailingSnapshot:
    """全局追踪快照——evaluate() 输出的主数据结构。"""

    timestamp: str
    by_state: Dict[str, TrailingResult]
    stats: "TrailingStats"
    recommendations: Dict[str, str] = field(default_factory=dict)
    extra: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "timestamp": self.timestamp,
            "stats": self.stats.to_dict(),
            "by_state": {k: v.to_dict() for k, v in self.by_state.items()},
            "recommendations": dict(self.recommendations),
            "extra": dict(self.extra),
        }


@dataclass
class TrailingStats:
    """追踪状态统计。"""

    total_positions: int = 0
    idle_count: int = 0
    armed_count: int = 0
    triggered_count: int = 0
    closed_count: int = 0
    triggered_total: int = 0       # 历史累计触发次数（持久化文件恢复）
    avg_armed_pnl_pct: float = 0.0  # 已激活仓位的平均激活时收益率
    avg_locked_profit_pct: float = 0.0  # 已触发仓位的平均锁定收益率

    def to_dict(self) -> Dict[str, Any]:
        return {
            "total_positions": self.total_positions,
            "idle_count": self.idle_count,
            "armed_count": self.armed_count,
            "triggered_count": self.triggered_count,
            "closed_count": self.closed_count,
            "triggered_total": self.triggered_total,
            "avg_armed_pnl_pct": round(self.avg_armed_pnl_pct, 4),
            "avg_locked_profit_pct": round(self.avg_locked_profit_pct, 4),
        }


# ---------------------------------------------------------------------------
# 辅助
# ---------------------------------------------------------------------------


def now_iso() -> str:
    """生成 UTC ISO 时间戳字符串。"""
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def calc_atr_trailing_price(
    is_long: bool,
    peak_price: float,
    atr_value: float,
    atr_multiplier: float,
    min_trail_pct: float,
) -> float:
    """计算 ATR 波动率自适应追踪止损价。

    追踪距离 = max(ATR × multiplier, peak_price × min_trail_pct)

    Args:
        is_long: 是否做多（True = long, False = short）
        peak_price: 开仓以来最高价（long）/ 最低价（short）
        atr_value: 当前 ATR 值
        atr_multiplier: ATR 倍数（默认 2.5）
        min_trail_pct: 最小追踪百分比（默认 3% = 0.03）

    Returns:
        追踪止损价
    """
    if peak_price <= 0 or atr_value < 0:
        return 0.0

    atr_distance = atr_value * atr_multiplier
    min_distance = peak_price * min_trail_pct
    trail_distance = max(atr_distance, min_distance)

    if is_long:
        return max(0.0, peak_price - trail_distance)
    else:
        return peak_price + trail_distance


def calc_pnl_eff_pct(
    is_long: bool,
    entry_price: float,
    current_price: float,
    leverage: float,
) -> float:
    """计算含杠杆的有效收益率（小数）。

    返回值如 0.25 表示 +25% 有效盈利（含杠杆）。
    """
    if entry_price <= 0 or leverage <= 0:
        return 0.0
    if is_long:
        raw = (current_price - entry_price) / entry_price
    else:
        raw = (entry_price - current_price) / entry_price
    return raw * leverage


__all__ = [
    "TrailingAction",
    "TrailingStatus",
    "TrailingState",
    "TrailingResult",
    "TrailingSnapshot",
    "TrailingStats",
    "calc_atr_trailing_price",
    "calc_pnl_eff_pct",
    "now_iso",
]
