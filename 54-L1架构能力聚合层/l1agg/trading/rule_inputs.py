# -*- coding: utf-8 -*-
"""L1-D 规则入参构造器（SPEC-54 §4.7 / L1D-03）。

只做「能力块 → direction_rule 入参」的字段投影：**不重算任何统计量**，
缺失或 `gate != ok` 的轴一律给 `None`，由 `direction_rule` 打降级旗标。
"""

from __future__ import annotations

import math
from typing import Any, Dict, Mapping, Optional

from ..direction_rule import canonical

_SLOPE_FIELDS = ("window", "slope", "se", "t", "r2", "hac_corrected", "degraded")


def two_sided_p(t_stat: Optional[float]) -> Optional[float]:
    """由 HAC t 换算双侧 p（正态近似，`erfc(|t|/√2)`）；不重估任何参数。"""
    if t_stat is None:
        return None
    return round(math.erfc(abs(float(t_stat)) / math.sqrt(2.0)), 8)


def _slope_table(block: Mapping[str, Any]) -> Optional[list]:
    rows = block.get("slope_table")
    if not rows:
        return None
    return [{key: row.get(key) for key in _SLOPE_FIELDS} for row in rows]


def _adx(block: Mapping[str, Any]) -> Optional[Dict[str, Any]]:
    adx = block.get("adx")
    if not isinstance(adx, Mapping) or adx.get("adx") is None:
        return None
    return {
        "adx14": adx.get("adx"),
        "plus_di": adx.get("plus_di"),
        "minus_di": adx.get("minus_di"),
    }


def _ema(block: Mapping[str, Any]) -> Optional[Dict[str, Any]]:
    ema = block.get("ema")
    if not isinstance(ema, Mapping):
        return None
    return {
        "ema12": ema.get("12"),
        "ema26": ema.get("26"),
        "ema50": ema.get("50"),
        "order": block.get("ema_order"),
    }


def build_inputs(
    capabilities: Mapping[str, Mapping[str, Any]],
    *,
    seasonality_years: Optional[float] = None,
    equilibrium_gap: Optional[Mapping[str, Any]] = None,
    forward_distribution: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    """能力块集合（`D-E15` / `D-E11` / `D-G22` / `D-E03`）→ 规则入参。

    `equilibrium_gap`（I35）与 `forward_distribution`（I36）由调用方按需透传：
    仅在显式提供时进入入参快照，缺省不改变既有回放字节（默认四轴口径不变）。
    """
    caps = capabilities or {}
    trend = caps.get("D-E15") or {}
    cycle_block = caps.get("D-E11") or {}
    significance = caps.get("D-G22") or {}
    seasonal = caps.get("D-E03") or {}

    trend_ok = trend.get("gate") == "ok"
    slope_table = _slope_table(trend) if trend_ok else None
    adx = _adx(trend) if trend_ok else None
    ema = _ema(trend) if trend_ok else None

    alignment = cycle_block.get("cycle_alignment") if cycle_block.get("gate") == "ok" else None
    same_direction_rate = None
    if isinstance(alignment, Mapping) and alignment.get("ratio") is not None:
        same_direction_rate = {
            "r": alignment.get("ratio"),
            "n": alignment.get("months", alignment.get("n")),
        }

    p_adj = significance.get("p_adj")
    if p_adj is None:
        p_adj = two_sided_p((significance.get("newey_west") or {}).get("t_nw"))

    seasonality = None
    if seasonal.get("gate") == "ok" and seasonality_years is not None:
        seasonality = {
            "depth_years": float(seasonality_years),
            "best_month": seasonal.get("best_month"),
            "seasonal_strength": seasonal.get("seasonal_strength"),
        }

    inputs: Dict[str, Any] = {
        "slope_table": slope_table,
        "adx": adx,
        "ema": ema,
        "same_direction_rate": same_direction_rate,
        "p_adj": p_adj,
        "seasonality": seasonality,
    }
    if equilibrium_gap is not None:
        inputs["equilibrium_gap"] = dict(equilibrium_gap)
    if forward_distribution is not None:
        inputs["forward_distribution"] = dict(forward_distribution)
    return canonical(inputs)


__all__ = ["build_inputs", "two_sided_p"]
