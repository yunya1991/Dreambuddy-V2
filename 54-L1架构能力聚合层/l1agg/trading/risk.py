# -*- coding: utf-8 -*-
"""L1-X 风控五项 + `KILL_SWITCH`（SPEC-54 §4.7 / L1D-07）。

边界（ADR-V16）：
  - 本模块只做「开仓前闸门 + 拒单落账」，**不持有下单客户端**；真正下单由 22 执行引擎完成；
  - 五项上限是配置常量，改值必须升 `RISK_VERSION`（进记录供回放）；
  - `KILL_SWITCH=1` **只停新开仓**，平仓/减仓必须放行（否则会把人锁在仓里）；
  - 拒单顺序固定：kill_switch → max_daily_loss → max_positions → max_leverage
    → max_gross_exposure → max_notional（命中即返回，确定性）。
"""

from __future__ import annotations

import datetime as _dt
import os
from typing import Any, Dict, Mapping, Optional

from . import store

RISK_VERSION = "risk-1.0.0"
KILL_SWITCH_ENV = "L1_KILL_SWITCH"

KILL_SWITCH = "kill_switch"
MAX_DAILY_LOSS = "max_daily_loss"
MAX_POSITIONS = "max_positions"
MAX_LEVERAGE = "max_leverage"
MAX_GROSS_EXPOSURE = "max_gross_exposure"
CLUSTER_EXPOSURE = "cluster_exposure"
MAX_NOTIONAL = "max_notional"

REJECT_REASONS = (
    KILL_SWITCH,
    MAX_DAILY_LOSS,
    MAX_POSITIONS,
    MAX_LEVERAGE,
    MAX_GROSS_EXPOSURE,
    CLUSTER_EXPOSURE,
    MAX_NOTIONAL,
)

DEFAULT_LIMITS: Dict[str, float] = {
    "max_notional_usdt": 500.0,
    "max_daily_loss_usdt": 100.0,
    "max_positions": 3,
    "max_leverage": 2.0,
    "max_gross_exposure_usdt": 1500.0,
    "cluster_exposure_cap_pct": 0.50,
}


def kill_switch_active(value: Optional[Any] = None) -> bool:
    """`value` 缺省读环境变量 `L1_KILL_SWITCH`；`1/true/yes/on` 视为开启。"""
    if value is None:
        value = os.environ.get(KILL_SWITCH_ENV)
    if value is None:
        return False
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in ("1", "true", "yes", "on")


def check_order(
    *,
    notional_usdt: float,
    equity_usdt: float,
    open_positions: int = 0,
    gross_exposure_usdt: float = 0.0,
    daily_pnl_usdt: float = 0.0,
    cluster_exposure_usdt: Optional[float] = None,
    is_new: bool = True,
    kill_switch: Optional[Any] = None,
    limits: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    """五项上限 + 可选簇敞口闸门；返回 `{allowed, reject_reason, checks, limits, leverage}`。"""
    lim = dict(DEFAULT_LIMITS)
    if limits:
        lim.update({key: float(value) for key, value in limits.items()})
    notional = float(notional_usdt)
    equity = float(equity_usdt)
    leverage = round(notional / equity, 6) if equity > 0 else float("inf")

    base = {
        "rule_version": RISK_VERSION,
        "notional_usdt": round(notional, 8),
        "leverage": leverage,
        "limits": lim,
    }
    if not is_new:
        return {
            **base,
            "allowed": True,
            "reject_reason": None,
            "checks": {"reduce_only": "skipped"},
        }

    gross_after = float(gross_exposure_usdt) + notional
    cluster_after = (
        None if cluster_exposure_usdt is None else float(cluster_exposure_usdt) + notional
    )
    checks: Dict[str, Any] = {
        KILL_SWITCH: kill_switch_active(kill_switch),
        MAX_DAILY_LOSS: float(daily_pnl_usdt) <= -lim["max_daily_loss_usdt"],
        MAX_POSITIONS: int(open_positions) >= int(lim["max_positions"]),
        MAX_LEVERAGE: leverage > lim["max_leverage"],
        MAX_GROSS_EXPOSURE: gross_after > lim["max_gross_exposure_usdt"],
        CLUSTER_EXPOSURE: cluster_after is not None
        and gross_after > 0
        and cluster_after / gross_after > lim["cluster_exposure_cap_pct"],
        MAX_NOTIONAL: notional > lim["max_notional_usdt"],
    }
    reject_reason = next((name for name in REJECT_REASONS if checks[name]), None)
    return {
        **base,
        "allowed": reject_reason is None,
        "reject_reason": reject_reason,
        "checks": checks,
    }


def record_rejected_order(
    *,
    order_id: str,
    signal_id: int,
    symbol: str,
    side: str,
    qty: float,
    reject_reason: str,
    notional: Optional[float] = None,
    td_mode: Optional[str] = None,
    db_path: Optional[str] = None,
) -> str:
    """把拒单写入 `order` 表（`status='rejected'` + `reject_reason`），返回 `order_id`。"""
    if reject_reason not in REJECT_REASONS:
        raise ValueError(f"未知 reject_reason: {reject_reason}")
    conn = store.connect(db_path)
    try:
        conn.execute(
            'INSERT INTO "order" (order_id, signal_id, symbol, side, qty, notional,'
            " td_mode, reduce_only, status, reject_reason, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, 0, 'rejected', ?, ?)",
            (
                order_id,
                int(signal_id),
                symbol,
                "buy" if side == "buy" else "sell",
                float(qty),
                None if notional is None else float(notional),
                td_mode,
                reject_reason,
                _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds"),
            ),
        )
        conn.commit()
    finally:
        conn.close()
    return order_id


__all__ = [
    "DEFAULT_LIMITS",
    "KILL_SWITCH",
    "KILL_SWITCH_ENV",
    "MAX_DAILY_LOSS",
    "MAX_GROSS_EXPOSURE",
    "MAX_LEVERAGE",
    "MAX_NOTIONAL",
    "MAX_POSITIONS",
    "REJECT_REASONS",
    "RISK_VERSION",
    "check_order",
    "kill_switch_active",
    "record_rejected_order",
]
