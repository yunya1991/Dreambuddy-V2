# -*- coding: utf-8 -*-
"""L1-D 平仓规则（SPEC-54 §4.7 `exit_rule` / L1D-04）。

四条规则任一触发即平，确定性纯函数：
  1. `sign(total)` 与持仓方向相反（方向反转）；
  2. `abs(total) < exit_threshold(=12)` 且连续 `hysteresis_confirm_bars(=2)` 根（迟滞防抖）；
  3. `adx14 < 20` 且 `ema_order == "mixed"`（趋势结构瓦解）；
  4. 硬止损（由 L1-X 风控给出，`stop_triggered=True`），**不受 `min_hold_bars` 限制**。

规则 1–3 需持仓满 `min_hold_bars(=6)` 才生效，避免短窗口噪声直接推翻持仓。
"""

from __future__ import annotations

from typing import Any, Dict, Mapping, Optional

from ..direction_rule import DEFAULT_PARAMS, _sign, params_hash

STOP_LOSS = "stop_loss"
DIRECTION_FLIP = "direction_flip"
FLAT_CONFIRM = "flat_confirm"
STRUCTURE_BREAKDOWN = "structure_breakdown"
MIN_HOLD_GUARD = "min_hold_guard"
ADX_WEAK = 20.0


def evaluate(
    position_direction: int,
    *,
    total: float,
    duration_bars: Optional[int] = None,
    low_bars: int = 0,
    adx14: Optional[float] = None,
    ema_order: Optional[str] = None,
    stop_triggered: bool = False,
    params: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    """返回 `{exit, reason, low_bars, blocked_by_min_hold, flags, rule_version, params_hash}`。"""
    direction = int(position_direction)
    if direction not in (-1, 1):
        raise ValueError("position_direction 必须 ∈ {-1,1}")
    p = dict(params or DEFAULT_PARAMS)

    base = {
        "rule_version": p["version"],
        "params_hash": params_hash(p),
        "position_direction": direction,
    }
    if stop_triggered:
        return {
            **base,
            "exit": True,
            "reason": STOP_LOSS,
            "low_bars": int(low_bars),
            "blocked_by_min_hold": False,
            "flags": ["stop_loss_bypass"],
        }

    exit_threshold = float(p["exit_threshold"])
    confirm_bars = int(p["hysteresis_confirm_bars"])
    min_hold = int(p["min_hold_bars"])

    low = int(low_bars) + 1 if abs(float(total)) < exit_threshold else 0
    flags = []
    if duration_bars is None:
        flags.append("duration_unknown")
    duration_ok = duration_bars is None or int(duration_bars) >= min_hold

    reason: Optional[str] = None
    if _sign(total) == -direction:
        reason = DIRECTION_FLIP
    elif low >= confirm_bars:
        reason = FLAT_CONFIRM
    elif adx14 is not None and float(adx14) < ADX_WEAK and ema_order == "mixed":
        reason = STRUCTURE_BREAKDOWN

    if reason is None:
        return {
            **base,
            "exit": False,
            "reason": None,
            "low_bars": low,
            "blocked_by_min_hold": False,
            "flags": flags,
        }

    if not duration_ok:
        return {
            **base,
            "exit": False,
            "reason": MIN_HOLD_GUARD,
            "low_bars": low,
            "blocked_by_min_hold": True,
            "flags": flags + [f"pending:{reason}"],
        }

    return {
        **base,
        "exit": True,
        "reason": reason,
        "low_bars": low,
        "blocked_by_min_hold": False,
        "flags": flags,
    }


__all__ = [
    "ADX_WEAK",
    "DIRECTION_FLIP",
    "FLAT_CONFIRM",
    "MIN_HOLD_GUARD",
    "STOP_LOSS",
    "STRUCTURE_BREAKDOWN",
    "evaluate",
]
