"""主导因素一致率门控 — SPEC-D1-MULTIDIM-STATE §2.7.3 / §7 P3-a。

claim（文章主张）vs DimensionContext（9 域实测）→ 三档门控 + 样本权重。

预注册阈值（禁止按结果回调）：
  consistent            主导维 = 实测最强维且方向一致        → 权重 1.0
  divergent_but_valid   主导维 |z| ≥ 1 且方向一致（非最强）  → 权重 1.5
  no_signal             主导维 |z| < 0.5 或方向相反          → 权重 0.3
  unmeasurable          主导维无可用数据                    → 不参与一致率统计

FAIL-OPEN：异常按 unmeasurable 处理，不抛。
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger("data_center.processing.dominance_agreement")

GATE_WEIGHTS = {
    "consistent": 1.0,
    "divergent_but_valid": 1.5,
    "no_signal": 0.3,
}
MIN_Z_VALID = 1.0
MIN_Z_SIGNAL = 0.5
MEASURABLE_AVAILABILITY = {"long", "short"}


def _claim_direction(claim: dict) -> str:
    d = claim.get("direction")
    return {"bullish": "up", "bearish": "down"}.get(d, "neutral")


def evaluate_claim(claim: Any, matrix: Any) -> dict:
    """单篇 claim 的实测一致性判定。FAIL-OPEN。"""
    base = {
        "claimed_dimension": None,
        "measured_top": None,
        "claim_direction": "neutral",
        "measured_direction": None,
        "measured_z": None,
        "measured_strength": None,
        "gate": "unmeasurable",
        "weight": None,
        "agreement": None,
    }
    try:
        if not isinstance(claim, dict) or not isinstance(matrix, dict):
            return base

        dim = claim.get("dominant_dimension")
        cdir = _claim_direction(claim)
        measured = {
            d: c
            for d, c in matrix.items()
            if getattr(c, "availability", "none") in MEASURABLE_AVAILABILITY
            and getattr(c, "data_points", 0) > 0
        }
        top = max(measured, key=lambda d: measured[d].strength) if measured else None

        res = {
            **base,
            "claimed_dimension": dim,
            "measured_top": top,
            "claim_direction": cdir,
        }
        if not dim or dim not in matrix or cdir == "neutral":
            return res

        ctx = matrix[dim]
        if dim not in measured:
            return res

        res["measured_direction"] = ctx.direction
        res["measured_z"] = ctx.z
        res["measured_strength"] = ctx.strength
        same = ctx.direction == cdir

        if same and dim == top:
            gate = "consistent"
        elif same and abs(ctx.z) >= MIN_Z_VALID:
            gate = "divergent_but_valid"
        else:
            gate = "no_signal"

        return {
            **res,
            "gate": gate,
            "weight": GATE_WEIGHTS[gate],
            "agreement": gate in ("consistent", "divergent_but_valid"),
        }
    except Exception as e:  # noqa: BLE003  FAIL-OPEN
        logger.warning("[FAIL-OPEN] evaluate_claim 异常 %s: %s", type(e).__name__, str(e)[:160])
        return base


def summarize(rows: list[dict]) -> dict:
    """汇总一致率（unmeasurable 不计入分母）。FAIL-OPEN。"""
    try:
        rows = [r for r in rows if isinstance(r, dict)]
        gate_counts: dict[str, int] = {}
        for r in rows:
            g = r.get("gate", "unmeasurable")
            gate_counts[g] = gate_counts.get(g, 0) + 1
        measurable = [r for r in rows if r.get("gate") != "unmeasurable"]
        agree = sum(1 for r in measurable if r.get("agreement") is True)
        return {
            "n_total": len(rows),
            "n_measurable": len(measurable),
            "n_agree": agree,
            "agreement_rate": (agree / len(measurable)) if measurable else None,
            "gate_counts": gate_counts,
        }
    except Exception as e:  # noqa: BLE003  FAIL-OPEN
        logger.warning("[FAIL-OPEN] summarize 异常 %s: %s", type(e).__name__, str(e)[:160])
        return {
            "n_total": 0,
            "n_measurable": 0,
            "n_agree": 0,
            "agreement_rate": None,
            "gate_counts": {},
        }
