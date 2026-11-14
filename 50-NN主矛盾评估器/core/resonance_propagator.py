"""M4 共振传感器 → 50 live 决策置信度传导。

复用 core/resonance_sensor.py（R(s)=corr0/beta/down_corr、t_arrive、regime_overlay），
只做一件增量事：按"龙头方向 × 相关标的方向 × corr0/down_corr"放大或衰减 confidence。

约束：
- 只调 confidence，不改 direction（方向仍由 50 裁决）
- 有界：乘数 ∈ [1-alpha, 1+alpha]（alpha 默认 0.15）
- 时滞保护：t_arrive > MAX_LAG_DAYS 不传导（滞后太长等于噪声）
- fail-open：传感器降级 / 非矩阵标的 / 无龙头证据 → 原样返回，multiplier=1.0
- 可解释：payload.resonance 记录 leader、corr0、down_corr、t_arrive、multiplier、raw_confidence
"""

from __future__ import annotations

import os
from typing import Any

from core.resonance_sensor import ResonanceSensor

ALPHA = float(os.environ.get("50_RESONANCE_ALPHA", "0.15"))
MIN_CORR = float(os.environ.get("50_RESONANCE_MIN_CORR", "0.5"))
MAX_LAG_DAYS = float(os.environ.get("50_RESONANCE_MAX_LAG_DAYS", "3"))

_LEADER = {
    "crypto_usdt": "BTC",
    "crypto": "BTC",
    "precious_metal": "XAU",
    "us_stock": "NVDA",
    "us_etf": "SPY",
    "us_index": "US500",
    "energy": "CL",
    "apac_index": "JP225",
    "industrial_metal": "XCU",
    "rates_credit": "TLT",
}

_SENSOR: ResonanceSensor | None = None


def _sensor(sensor: ResonanceSensor | None = None) -> ResonanceSensor:
    global _SENSOR
    if sensor is not None:
        return sensor
    if _SENSOR is None:
        _SENSOR = ResonanceSensor()
    return _SENSOR


def _base_symbol(symbol: str) -> str:
    return (symbol or "").strip().upper().replace("/", "-").split("-")[0]


def _leader_direction(evidences: list[dict[str, Any]], leader: str) -> str | None:
    best: tuple[float, str] | None = None
    for ev in evidences:
        if _base_symbol(str(ev.get("symbol") or "")) != leader:
            continue
        direction = str(ev.get("direction") or "").lower()
        if direction not in ("long", "short"):
            continue
        try:
            conf = float(ev.get("confidence") or 0)
        except (TypeError, ValueError):
            continue
        if best is None or conf > best[0]:
            best = (conf, direction)
    return best[1] if best else None


def propagate(
    decision: dict[str, Any],
    evidences: list[dict[str, Any]],
    asset_class: str = "crypto_usdt",
    sensor: ResonanceSensor | None = None,
) -> dict[str, Any]:
    """按龙头共振调整单条决策 confidence（原地修改并返回）。"""
    base = _base_symbol(str(decision.get("symbol") or ""))
    leader = _LEADER.get(asset_class)
    leader_dir = _leader_direction(evidences, leader) if leader else None
    payload = decision.setdefault("payload", {})

    meta: dict[str, Any] = {
        "leader": leader,
        "leader_direction": leader_dir,
        "multiplier": 1.0,
        "raw_confidence": decision.get("confidence"),
        "applied": False,
    }

    direction = str(decision.get("direction") or "").lower()
    if not leader or leader_dir is None or base == leader or direction not in ("long", "short"):
        payload["resonance"] = meta
        return decision

    snap = _sensor(sensor).get_snapshot(f"{base}/USDT")
    r = snap.r or {}
    corr0 = float(r.get("corr0") or 0)
    down_corr = float(r.get("down_corr") or 0)
    meta.update(
        {
            "corr0": corr0,
            "down_corr": down_corr,
            "t_arrive": snap.t_arrive,
            "regime_overlay": snap.regime_overlay,
            "degraded": snap.degraded,
        }
    )

    if abs(corr0) < MIN_CORR or (
        {"symbol_not_in_layers", "resonance_fallback", "fetch_failed", "leader_missing"}
        & set(snap.degraded or [])
    ):
        meta["skip_reason"] = "degraded_or_low_corr"
        payload["resonance"] = meta
        return decision
    if snap.t_arrive is not None and snap.t_arrive > MAX_LAG_DAYS:
        meta["skip_reason"] = "lag_too_long"
        payload["resonance"] = meta
        return decision

    if direction == leader_dir:
        multiplier = 1.0 + ALPHA * min(abs(corr0), 1.0)
    else:
        multiplier = 1.0 - ALPHA * min(abs(down_corr), 1.0)

    try:
        raw = float(decision.get("confidence") or 0)
    except (TypeError, ValueError):
        raw = 0.0
    decision["confidence"] = round(max(0.0, min(1.0, raw * multiplier)), 4)
    meta.update({"multiplier": round(multiplier, 4), "applied": True})
    payload["resonance"] = meta
    return decision
