"""
Level 0 路径代价计算器 (§1.5.5 · MVP 即部署)
蓝图: 四层闭环进化架构-最小阻力路径总览.md §1.5.5

d* = argmin_{d ∈ {long, short, WAIT}} [ d^T · g_MVP · d ]
  多开代价 = g_up = R_up
  空开代价 = g_down = R_down
  WAIT代价 = R_smooth × R_reflexivity

g_MVP = diag(R_up, R_down, R_smooth, R_flow, R_reflexivity)
"""
import math
import numpy as np
from typing import Any


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


def compute_d_star(r_vector: dict[str, Any]) -> dict[str, Any]:
    """
    Level 0 最优方向: argmin 代价方向.
    返回: {d_star, costs{long,short,wait}, confidence}
    confidence = 1 - (min_cost / sum_costs) 越大越自信.
    """
    import math as _math
    R_up = float(r_vector.get("R_up", 0.50))
    R_down = float(r_vector.get("R_down", 0.50))
    R_smooth = float(r_vector.get("R_smooth", 0.50))
    R_flow = float(r_vector.get("R_flow", 0.50))
    R_refl = float(r_vector.get("R_reflexivity", 0.50))

    for v in (R_up, R_down, R_smooth, R_flow, R_refl):
        if _math.isnan(v) or _math.isinf(v):
            pass  # use 0.50 fallback below

    R_up = max(0.01, R_up) if not _math.isnan(R_up) else 0.50
    R_down = max(0.01, R_down) if not _math.isnan(R_down) else 0.50
    R_smooth = max(0.01, R_smooth) if not _math.isnan(R_smooth) else 0.50
    R_refl = max(0.01, R_refl) if not _math.isnan(R_refl) else 0.50

    costs = {
        "long": R_up,                                    # §1.5.5 多开代价 = g_up
        "short": R_down,                                 # §1.5.5 空开代价 = g_down
        "wait": R_smooth * R_refl,                       # §1.5.5 WAIT代价 = R_smooth × R_reflexivity
    }

    d_star_raw = min(costs, key=costs.get)
    d_star = "WAIT" if d_star_raw == "wait" else d_star_raw

    total = sum(costs.values())
    confidence = 1.0 - (costs[d_star_raw] / total) if total > 0 else 0.0
    confidence = max(0.0, min(1.0, confidence))

    return {
        "d_star": d_star,
        "costs": costs,
        "confidence": round(confidence, 4),
    }
