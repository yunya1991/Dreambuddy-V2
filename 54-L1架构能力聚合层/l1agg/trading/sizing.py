# -*- coding: utf-8 -*-
"""L1-D 持仓管理：vol targeting → target position（SPEC-54 §4.7 / L1D-06）。

口径（确定性，无 LLM / 无随机）：
    scale      = clip(target_vol / max(volatility, min_vol), 0, max_vol_scale)
    notional   = equity_usdt × strength × scale
    qty        = notional / price（允许 8 位小数）
    风控       = `risk.check_order` 五项闸门；越界不截断、直接拒（`reject_reason`）

`volatility` 必须来自 L1-S 的统计块（本模块不重算波动率）；`direction=0` 不下单。
"""

from __future__ import annotations

from typing import Any, Dict, Mapping, Optional

from . import risk

SIZING_VERSION = "size-1.0.0"
TARGET_VOL = 0.02
MAX_VOL_SCALE = 3.0
MIN_VOL = 1e-4
NO_DIRECTION = "no_direction"


def vol_scale(
    volatility: float,
    *,
    target_vol: float = TARGET_VOL,
    min_vol: float = MIN_VOL,
    max_scale: float = MAX_VOL_SCALE,
) -> float:
    """低波动放大、高波动收缩；上限 `max_scale` 防止零波动无限放大。"""
    vol = max(float(volatility), float(min_vol))
    return round(min(float(max_scale), float(target_vol) / vol), 6)


def target_position(
    direction: int,
    strength: float,
    *,
    price: float,
    equity_usdt: float,
    volatility: float,
    open_positions: int = 0,
    gross_exposure_usdt: float = 0.0,
    daily_pnl_usdt: float = 0.0,
    cluster_exposure_usdt: Optional[float] = None,
    is_new: bool = True,
    kill_switch: Optional[Any] = None,
    limits: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    """返回内部仓位建议：`{allowed, reject_reason, direction, qty, notional_usdt, ...}`。"""
    side = int(direction)
    if side not in (-1, 0, 1):
        raise ValueError("direction 必须 ∈ {-1,0,1}")
    size = float(strength)
    if not 0.0 <= size <= 1.0:
        raise ValueError("strength 必须 ∈ [0,1]")
    px = float(price)
    if px <= 0:
        raise ValueError("price 必须 > 0")
    equity = float(equity_usdt)
    if equity <= 0:
        raise ValueError("equity_usdt 必须 > 0")

    base = {
        "sizing_version": SIZING_VERSION,
        "direction": side,
        "strength": size,
        "price": px,
        "equity_usdt": equity,
        "volatility": float(volatility),
        "target_vol": TARGET_VOL,
        "vol_scale": vol_scale(volatility),
    }
    if side == 0:
        return {
            **base,
            "allowed": False,
            "reject_reason": NO_DIRECTION,
            "notional_usdt": 0.0,
            "qty": 0.0,
            "leverage": 0.0,
        }

    notional = round(equity * size * base["vol_scale"], 8)
    decision = risk.check_order(
        notional_usdt=notional,
        equity_usdt=equity,
        open_positions=open_positions,
        gross_exposure_usdt=gross_exposure_usdt,
        daily_pnl_usdt=daily_pnl_usdt,
        cluster_exposure_usdt=cluster_exposure_usdt,
        is_new=is_new,
        kill_switch=kill_switch,
        limits=limits,
    )
    return {
        **base,
        **decision,
        "qty": round(notional / px, 8) if decision["allowed"] else 0.0,
    }


__all__ = [
    "MAX_VOL_SCALE",
    "MIN_VOL",
    "NO_DIRECTION",
    "SIZING_VERSION",
    "TARGET_VOL",
    "target_position",
    "vol_scale",
]
