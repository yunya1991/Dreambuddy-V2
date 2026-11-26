"""
Level 0 路径代价计算器 (§1.5.5 · MVP 即部署)
蓝图: 四层闭环进化架构-最小阻力路径总览.md §1.5.5

d* = argmin_{d ∈ {long, short, WAIT}} [ d^T · g_MVP · d ]
  多开代价 = g_up = R_up
  空开代价 = g_down = R_down
  WAIT代价 = R_smooth × R_reflexivity

g_MVP = diag(R_up, R_down, R_smooth, R_flow, R_reflexivity)

F4 wait 口径校准（默认 legacy，行为不变）:
  legacy     : wait = R_smooth × R_reflexivity（两维乘积，量纲系统性低于单维）
  calibrated : wait = (1 − R_smooth) × R_reflexivity，且要求
               min(R_up, R_down) ≤ wait × (1 − margin) 才交易，否则 WAIT（中性区）
  开关: EVOLUTION_DSTAR_WAIT_MODE=legacy|calibrated（默认 legacy）
        EVOLUTION_DSTAR_WAIT_MARGIN=0.30（默认 0.30）
  依据: scripts/backtest_ri_gate.py + 云端真实 K 线 walk-forward（见
        docs/FIXLIST-ri-tier-dstar-20261118.md F4）
"""

import math
import os
from typing import Any

import numpy as np

_WAIT_MODE_ENV = "EVOLUTION_DSTAR_WAIT_MODE"
_WAIT_MARGIN_ENV = "EVOLUTION_DSTAR_WAIT_MARGIN"
_DEFAULT_WAIT_MARGIN = 0.30
_REFL_NORM_ENV = "EVOLUTION_DSTAR_REFL_NORM"
_WAIT_SCALE_ENV = "EVOLUTION_DSTAR_WAIT_SCALE"
_DEFAULT_WAIT_SCALE = 2.0


def _wait_mode() -> str:
    mode = str(os.getenv(_WAIT_MODE_ENV, "legacy")).strip().lower()
    return mode if mode in ("legacy", "calibrated") else "legacy"


def _wait_margin() -> float:
    try:
        v = float(os.getenv(_WAIT_MARGIN_ENV, _DEFAULT_WAIT_MARGIN))
    except (TypeError, ValueError):
        return _DEFAULT_WAIT_MARGIN
    return max(0.0, min(0.9, v))


def _refl_norm_enabled() -> bool:
    """R_reflexivity 历史分位归一化开关（默认 0，保持旧口径）。"""
    return os.getenv(_REFL_NORM_ENV, "0").strip().lower() in ("1", "true", "on", "yes")


def _wait_scale() -> float:
    try:
        v = float(os.getenv(_WAIT_SCALE_ENV, _DEFAULT_WAIT_SCALE))
    except (TypeError, ValueError):
        return _DEFAULT_WAIT_SCALE
    return max(0.1, min(5.0, v))


def compute_g_diag(r_vector: dict[str, Any]) -> np.ndarray:
    """
    构建对角黎曼度规 g_MVP (5×5).
    FAIL-OPEN: 任一维 NaN/缺失 → 0.50 + ε 兜底.
    """
    dims = ["R_up", "R_down", "R_smooth", "R_flow", "R_reflexivity"]
    diag_vals = []
    for d in dims:
        v = float(r_vector.get(d, 0.50))
        if math.isnan(v) or math.isinf(v):
            v = 0.50
        v = max(0.01, v)  # 防止 0 导致 det(g)=0 退化
        diag_vals.append(v)
    return np.diag(np.array(diag_vals, dtype=np.float64))


def _pick(costs: dict[str, float], wait_mode: str, wait_margin: float) -> str:
    """按口径选出方向；返回 long/short/WAIT。"""
    best_dir = "long" if costs["long"] <= costs["short"] else "short"
    if wait_mode == "calibrated":
        # 中性区：方向代价须比等待代价低出 margin 才动手
        if costs[best_dir] <= costs["wait"] * (1.0 - wait_margin):
            return best_dir
        return "WAIT"
    d_star_raw = min(costs, key=costs.get)
    return "WAIT" if d_star_raw == "wait" else d_star_raw


def compute_d_star(
    r_vector: dict[str, Any],
    wait_mode: str | None = None,
    wait_margin: float | None = None,
) -> dict[str, Any]:
    """
    Level 0 最优方向: argmin 代价方向.

    返回: {d_star, costs, confidence,
           d_star_calibrated, costs_calibrated, wait_mode, wait_margin}
    confidence = 1 - (min_cost / sum_costs) 越大越自信.
    """
    mode = (
        _wait_mode()
        if wait_mode is None
        else (wait_mode if wait_mode in ("legacy", "calibrated") else "legacy")
    )
    margin = _wait_margin() if wait_margin is None else float(wait_margin)

    R_up = float(r_vector.get("R_up", 0.50))
    R_down = float(r_vector.get("R_down", 0.50))
    R_smooth = float(r_vector.get("R_smooth", 0.50))
    R_flow = float(r_vector.get("R_flow", 0.50))
    R_refl = float(r_vector.get("R_reflexivity", 0.50))

    for v in (R_up, R_down, R_smooth, R_flow, R_refl):
        if math.isnan(v) or math.isinf(v):
            pass  # use 0.50 fallback below

    R_up = max(0.01, R_up) if not math.isnan(R_up) else 0.50
    R_down = max(0.01, R_down) if not math.isnan(R_down) else 0.50
    R_smooth = max(0.01, R_smooth) if not math.isnan(R_smooth) else 0.50
    R_refl = max(0.01, R_refl) if not math.isnan(R_refl) else 0.50

    costs = {
        "long": R_up,  # §1.5.5 多开代价 = g_up
        "short": R_down,  # §1.5.5 空开代价 = g_down
        "wait": R_smooth * R_refl,  # §1.5.5 WAIT代价 = R_smooth × R_reflexivity
    }
    # F4 校准口径：等待成本随趋势强度上升（R_smooth 低 = 趋势纯 = 等待更贵）
    # F4.1（2026-11-26）：R_reflexivity 历史分位归一化 + 尺度放大，使其与方向代价可比
    refl_pct: float | None = None
    wait_scale = _wait_scale() if _refl_norm_enabled() else 1.0
    if _refl_norm_enabled():
        from .reflexivity_normalizer import get_normalizer

        norm = get_normalizer()
        refl_pct = norm.percentile(R_refl)
        norm.observe(R_refl)
        wait_cal_val = min(0.99, (1.0 - min(R_smooth, 0.99)) * refl_pct * wait_scale)
    else:
        wait_cal_val = (1.0 - min(R_smooth, 0.99)) * R_refl
    costs_cal = {
        "long": R_up,
        "short": R_down,
        "wait": wait_cal_val,
    }

    d_star = _pick(costs_cal if mode == "calibrated" else costs, mode, margin)
    d_star_cal = _pick(costs_cal, "calibrated", margin)
    costs_pick = costs_cal if mode == "calibrated" else costs
    best_key = "wait" if d_star == "WAIT" else d_star.lower()

    total = sum(costs_pick.values())
    confidence = 1.0 - (costs_pick[best_key] / total) if total > 0 else 0.0
    confidence = max(0.0, min(1.0, confidence))

    return {
        "d_star": d_star,
        "costs": costs if mode == "legacy" else costs_cal,
        "confidence": round(confidence, 4),
        "d_star_calibrated": d_star_cal,
        "costs_calibrated": costs_cal,
        "wait_mode": mode,
        "wait_margin": round(float(margin), 4),
        "R_reflexivity_pct": None if refl_pct is None else round(refl_pct, 4),
        "wait_scale": round(float(wait_scale), 4),
    }
