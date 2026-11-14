"""资产类别配额（配比制）v1 —— 40/43 弹性约束的落地判定。

用户决策 2026-11-14：
    可投资本 = 总权益 × 杠杆 × band_upper × exposure_hint
    各类配额 = 可投资本 × asset_allocation[cls]
    已用名义（含挂单）≥ 配额 → 只禁该类加仓（block_over_quota），不禁其他类别。

红线：只做配额判定，不产方向信号；FAIL-OPEN：输入缺失 → allow。
"""

from __future__ import annotations

from typing import Any, Dict, Optional

ASSET_CLASSES = ("crypto_usdt", "us_stock", "precious_metal")
_EPS = 1e-9


def _f(value: Any, default: float = 0.0) -> float:
    try:
        if value is None:
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def build_quota_plan(
    *,
    total_equity: float,
    leverage: float = 5.0,
    band_upper_pct: Optional[float] = None,
    exposure_hint: Optional[float] = None,
    allocation: Optional[Dict[str, float]] = None,
    stale: bool = False,
) -> Dict[str, Any]:
    """构建各类资产配额计划。

    Args:
        total_equity: 账户总权益（USDT）
        leverage: 名义杠杆（总权益 → 名义可投资本）
        band_upper_pct: 40 `position_band_pct` 上限（百分数，如 55 表示 55%）
        exposure_hint: 43 `capital_posture.exposure_hint`（0-1）
        allocation: 43 `asset_allocation.allocation`（已归一到 1.0）
        stale: 约束数据陈旧 → exposure_hint 再降一档（×0.5），不转全禁
    """
    eq = max(0.0, _f(total_equity))
    lev = max(0.0, _f(leverage, 5.0))
    band_pct = 100.0 if band_upper_pct is None else _f(band_upper_pct, 100.0)
    band_ratio = max(0.0, min(1.0, band_pct / 100.0))
    hint = 1.0 if exposure_hint is None else max(0.0, min(1.0, _f(exposure_hint, 1.0)))
    if stale:
        hint *= 0.5

    raw = allocation if isinstance(allocation, dict) else {}
    weights = {cls: max(0.0, _f(raw.get(cls), 0.0)) for cls in ASSET_CLASSES}
    total_w = sum(weights.values())
    if total_w <= _EPS:
        weights = {cls: 1.0 / len(ASSET_CLASSES) for cls in ASSET_CLASSES}
    else:
        weights = {cls: weights[cls] / total_w for cls in ASSET_CLASSES}

    investable = eq * lev * band_ratio * hint
    quotas = {cls: investable * weights[cls] for cls in ASSET_CLASSES}
    return {
        "total_equity": round(eq, 2),
        "leverage": round(lev, 2),
        "band_upper_pct": round(band_pct, 4),
        "band_ratio": round(band_ratio, 4),
        "exposure_hint": round(hint, 4),
        "stale": bool(stale),
        "allocation": {cls: round(v, 4) for cls, v in weights.items()},
        "investable_notional": round(investable, 2),
        "quota": {cls: round(v, 2) for cls, v in quotas.items()},
    }


def evaluate_entry(
    *,
    asset_class: str,
    requested_notional: float,
    used_notional_by_class: Optional[Dict[str, float]],
    plan: Optional[Dict[str, Any]],
    min_notional: float = 0.0,
) -> Dict[str, Any]:
    """配额判定。

    Returns:
        decision ∈ {allow, allow_clamped, block_over_quota, constraint_suppressed}
        allowed_notional: 实际允许的下单名义（0 表示不下单）
    """
    req = max(0.0, _f(requested_notional))
    cls = asset_class if asset_class in ASSET_CLASSES else None
    quota_map = (plan or {}).get("quota") or {}
    if cls is None or cls not in quota_map:
        return {
            "decision": "allow",
            "allowed_notional": round(req, 2),
            "reason": "no_quota_plan",
            "asset_class": asset_class,
        }

    quota = max(0.0, _f(quota_map.get(cls)))
    used = max(0.0, _f((used_notional_by_class or {}).get(cls)))
    remaining = quota - used
    base = {
        "asset_class": cls,
        "quota": round(quota, 2),
        "used": round(used, 2),
        "remaining": round(max(0.0, remaining), 2),
    }

    if remaining <= _EPS:
        return {
            **base,
            "decision": "block_over_quota",
            "allowed_notional": 0.0,
            "reason": "class_quota_exhausted",
        }

    allowed = min(req, remaining)
    floor = max(0.0, _f(min_notional))
    if allowed < max(floor, _EPS):
        return {
            **base,
            "decision": "constraint_suppressed",
            "allowed_notional": 0.0,
            "reason": "below_min_notional_after_quota",
        }

    decision = "allow" if allowed >= req - _EPS else "allow_clamped"
    return {
        **base,
        "decision": decision,
        "allowed_notional": round(allowed, 2),
        "reason": "within_quota" if decision == "allow" else "clamped_to_remaining",
    }


def direction_policy(direction: str, bias_row: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """43 `direction_bias.per_class[cls]` → 仓位乘数（不 veto）。

    - 同向 dominant：×(1 + 0.3×同向权重)
    - 中性 dominant：×1.0；neutral ≥ 0.99 → 仅允许 probe
    - 反向 dominant：×0.6（只降仓，不禁开）
    """
    d = str(direction or "").lower()
    row = bias_row if isinstance(bias_row, dict) else {}
    if not row or d not in ("long", "short"):
        return {"multiplier": 1.0, "probe_only": False, "reason": "no_bias"}
    dominant = str(row.get("dominant") or "neutral").lower()
    neutral_w = max(0.0, min(1.0, _f(row.get("neutral"), 0.0)))
    if dominant == d:
        return {
            "multiplier": round(1.0 + 0.3 * max(0.0, min(1.0, _f(row.get(d)))), 4),
            "probe_only": False,
            "reason": "aligned",
        }
    if dominant == "neutral":
        return {
            "multiplier": 1.0,
            "probe_only": neutral_w >= 0.99,
            "reason": "neutral",
        }
    return {"multiplier": 0.6, "probe_only": False, "reason": "opposite"}
