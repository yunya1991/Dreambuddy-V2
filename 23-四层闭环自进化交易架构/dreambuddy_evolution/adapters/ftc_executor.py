"""
ftc_executor — FTC 可执行交易逻辑映射

将 FTC 的 condition 步骤映射为对 kline_data 的检查，
inference 步骤跳过（不执行），action 步骤决定方向。

执行规则:
  - 所有 condition 步骤必须满足 (AND 逻辑)
  - inference 步骤不参与执行（仅用于知识对齐和可解释）
  - action 步骤的 gene_ref 决定方向: AC-LONG→long, AC-SHORT→short, etc.
  - 如果有多个 action，取第一个（简化）
  - 如果条件不满足 → "WAIT"

FAIL-OPEN: 缺少数据时返回 WAIT，不抛异常。
"""
from __future__ import annotations

import logging
from typing import Any

from .ftc_schema import FTC, FTCStep

logger = logging.getLogger(__name__)


def evaluate_ftc(ftc: FTC, kline_data: dict[str, Any]) -> dict[str, Any]:
    """
    在单根 K 线数据上评估 FTC，返回交易信号。

    Returns:
        {
            "signal": "long" | "short" | "WAIT",
            "confidence": float,  # 所有 condition 满足度的平均值
            "conditions_met": int,
            "conditions_total": int,
            "reason": str,
        }
    """
    conditions = ftc.condition_steps
    if not conditions:
        return {"signal": "WAIT", "confidence": 0.0,
                "conditions_met": 0, "conditions_total": 0,
                "reason": "no conditions"}

    met_count = 0
    confidences: list[float] = []

    for cond in conditions:
        ok, conf = _check_condition(cond, kline_data)
        if ok:
            met_count += 1
        confidences.append(conf)

    # 所有 condition 必须满足 (AND)
    if met_count < len(conditions):
        avg_conf = sum(confidences) / len(confidences) if confidences else 0.0
        return {
            "signal": "WAIT",
            "confidence": round(avg_conf, 4),
            "conditions_met": met_count,
            "conditions_total": len(conditions),
            "reason": f"{met_count}/{len(conditions)} conditions met",
        }

    # 所有条件满足 → 执行 action
    action = ftc.action_steps[0] if ftc.action_steps else None
    if not action:
        return {"signal": "WAIT", "confidence": 1.0,
                "conditions_met": met_count, "conditions_total": len(conditions),
                "reason": "conditions met but no action"}

    direction = _action_to_direction(action.gene_ref)
    avg_conf = sum(confidences) / len(confidences) if confidences else 1.0

    return {
        "signal": direction,
        "confidence": round(avg_conf, 4),
        "conditions_met": met_count,
        "conditions_total": len(conditions),
        "reason": f"all conditions met → {action.gene_ref}",
    }


def _check_condition(cond: FTCStep, kline_data: dict[str, Any]) -> tuple[bool, float]:
    """
    检查单个 condition 步骤是否满足。
    返回 (是否满足, 置信度 0-1)
    FAIL-OPEN: 数据缺失返回 (False, 0.0)
    """
    gene_ref = (cond.gene_ref or "").upper()
    threshold = cond.threshold

    # 根据 gene_ref 类型检查
    try:
        if gene_ref == "CD-VOL-SURGE":
            vol_ratio = float(kline_data.get("vol_ratio", 1.0) or 1.0)
            t = float(threshold or 1.3)
            conf = min(1.0, max(0.0, (vol_ratio - 1.0) / max(t - 1.0, 0.1)))
            return vol_ratio >= t, conf

        elif gene_ref == "CD-PRICE-BREAKOUT":
            close = kline_data.get("close", [])
            if isinstance(close, list) and len(close) >= 20:
                ma20 = sum(close[-20:]) / 20
                last = close[-1]
                conf = min(1.0, max(0.0, (last - ma20) / max(ma20, 1e-9) * 100))
                return last > ma20, conf
            return False, 0.0

        elif gene_ref == "CD-ADX-STRONG":
            adx = float(kline_data.get("adx", 0) or 0)
            t = float(threshold or 20)
            conf = min(1.0, adx / 50.0)
            return adx >= t, conf

        elif gene_ref in ("CD-CAPITAL-ROTATION", "CD-CAPITAL-INFLOW"):
            rot = float(kline_data.get("capital_rotation", 0) or 0)
            if gene_ref == "CD-CAPITAL-ROTATION":
                t = float(threshold or 0.1)
                conf = min(1.0, abs(rot) / max(t, 0.1))
                return abs(rot) >= t, conf
            else:
                t = float(threshold or 0.0)
                cap_flow = float(kline_data.get("capital_flow", 0) or 0)
                conf = min(1.0, max(0.0, cap_flow / 0.5))
                return cap_flow >= t, conf

        elif gene_ref == "CD-OI-DIVERGENCE":
            oi_change = float(kline_data.get("oi_change_pct", 0) or 0)
            t = float(threshold or 0.05)
            conf = min(1.0, abs(oi_change) / 0.1)
            return abs(oi_change) >= t, conf

        elif gene_ref == "CD-FUNDING-EXTREME":
            funding = float(kline_data.get("funding_rate", 0) or 0)
            t = float(threshold or 0.001)
            conf = min(1.0, abs(funding) / 0.005)
            return abs(funding) >= t, conf

        elif gene_ref == "CD-ZSCORE-EXTREME":
            z = float(kline_data.get("z_score", 0) or 0)
            t = float(threshold or 2.0)
            conf = min(1.0, abs(z) / t)
            return abs(z) >= t, conf

        elif gene_ref in ("CD-REGIME-RANGING", "CD-REGIME-TREND", "CD-REGIME-DETECT"):
            regime = kline_data.get("regime", "")
            if gene_ref == "CD-REGIME-RANGING":
                return regime == "ranging", 1.0 if regime == "ranging" else 0.0
            elif gene_ref == "CD-REGIME-TREND":
                return regime in ("trend_up", "trend_down"), 1.0 if regime.startswith("trend") else 0.0
            else:  # CD-REGIME-DETECT
                return regime in ("trend_up", "trend_down", "ranging"), 0.5

        elif gene_ref == "CD-SYMBOL-MATCH":
            symbol = kline_data.get("symbol", "")
            symbols = threshold if isinstance(threshold, (list, tuple)) else ()
            return symbol in symbols, 1.0 if symbol in symbols else 0.0

        # 未知基因: FAIL-OPEN 返回不满足
        return False, 0.0

    except (TypeError, ValueError, KeyError, ZeroDivisionError):
        return False, 0.0


def _action_to_direction(gene_ref: str | None) -> str:
    """将 action 基因映射为交易方向"""
    if not gene_ref:
        return "WAIT"
    g = gene_ref.upper()
    if "LONG" in g:
        return "long"
    if "SHORT" in g:
        return "short"
    if "FOLLOW" in g:
        return "follow"
    if "CONTRARIAN" in g:
        return "contrarian"
    if "ROTATION" in g:
        return "rotation"
    return "long"  # 默认做多
