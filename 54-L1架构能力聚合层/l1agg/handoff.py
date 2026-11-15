# -*- coding: utf-8 -*-
"""L1 → 22 执行信号交接（SPEC-54 §4.6 / §8，L1X-01）。

边界（硬约束）：
  - **L1 不执行**：本模块只把内部 `signal` 映射成 22 可接收的
    `FinalDecisionSignal v1.1`，下单/风控/撮合全部由 22 完成；
  - **不伪造执行标的**：只有 40 层 `asset_class=crypto` 的龙头才映射为
    `*-USDT-SWAP`，其余资产显式抛 `HandoffError`（禁止拿 MACRO 冒充）；
  - **确定性 decision_id**：`(symbol, as_of, direction, rule_version, params_hash)` 派生，
    供 22 进程内幂等与 outbox 去重（L1X-03）；
  - 输出再过一遍 49 契约的 jsonschema，字段口径与 23/50 两条链完全一致。
"""

from __future__ import annotations

import datetime as _dt
import json
import os
from typing import Any, Dict, Mapping, Optional

import jsonschema

from .leader_registry import BINDINGS, Binding

SOURCE = "l1-chart"
CONTRACT_PATH = os.path.normpath(
    os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
        "49-交易框架协议",
        "contracts",
        "final_decision_signal.v1.1.json",
    )
)

_DIRECTION_TEXT = {-1: "short", 0: "neutral", 1: "long"}
_ACTION_TEXT = {-1: "short", 0: "WAIT", 1: "long"}

_schema_cache: Optional[Dict[str, Any]] = None


class HandoffError(ValueError):
    """无法映射或映射结果不合 22 契约。"""


def _schema() -> Dict[str, Any]:
    global _schema_cache
    if _schema_cache is None:
        with open(CONTRACT_PATH, "r", encoding="utf-8") as fh:
            _schema_cache = json.load(fh)
    return _schema_cache


def _utc(now: Optional[_dt.datetime]) -> _dt.datetime:
    if now is None:
        return _dt.datetime.now(_dt.timezone.utc)
    return now if now.tzinfo else now.replace(tzinfo=_dt.timezone.utc)


def _iso(dt: _dt.datetime) -> str:
    return dt.astimezone(_dt.timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def execution_symbol(symbol: str) -> str:
    """L1 资产 → 22 可执行合约；非加密龙头直接拒绝（不猜标的）。"""
    raw = str(symbol or "").upper()
    base = raw.replace("-USDT-SWAP", "")
    binding: Optional[Binding] = BINDINGS.get(base)
    if binding is None or binding.asset_class != "crypto":
        raise HandoffError(f"no_execution_instrument:{symbol}")
    return f"{base}-USDT-SWAP"


def position_tier(direction: int, strength: float) -> str:
    if direction == 0:
        return "none"
    if strength < 0.55:
        return "probe"
    if strength < 0.75:
        return "standard"
    return "trend"


def build_final_decision(
    signal: Mapping[str, Any],
    *,
    mode: str = "paper",
    horizon: str = "days",
    ttl_minutes: float = 15.0,
    notional_usdt: float = 0.0,
    risk_exposure_hint: Optional[float] = None,
    now: Optional[_dt.datetime] = None,
) -> Dict[str, Any]:
    """`signal` 记录（含 `direction`/`strength`/`rule_version`/`params_hash`）→ 22 决策字典。"""
    for key in ("as_of", "symbol", "rule_version", "params_hash", "direction", "strength"):
        if signal.get(key) is None:
            raise HandoffError(f"signal 缺少字段: {key}")
    direction = int(signal["direction"])
    if direction not in (-1, 0, 1):
        raise HandoffError("direction 必须 ∈ {-1,0,1}")
    strength = float(signal["strength"])
    if not 0.0 <= strength <= 1.0:
        raise HandoffError("strength 必须 ∈ [0,1]")
    if mode not in ("live", "paper", "shadow"):
        raise HandoffError(f"未知 mode: {mode}")

    as_of = str(signal["as_of"])
    base = str(signal["symbol"]).upper().replace("-USDT-SWAP", "")
    symbol = execution_symbol(base)
    tier = position_tier(direction, strength)
    stamp = _utc(now)
    decision_id = (
        f"dec-l1-{base}-{as_of}-{direction}-{signal['rule_version']}-"
        f"{str(signal['params_hash'])[:8]}"
    )
    decision = {
        "signal_id": f"{SOURCE}|{decision_id}",
        "source": SOURCE,
        "ts": _iso(stamp),
        "symbol": symbol,
        "direction": _DIRECTION_TEXT[direction],
        "confidence": strength,
        "horizon": horizon,
        "risk_exposure_hint": (
            strength
            if risk_exposure_hint is None and direction != 0
            else (0.0 if risk_exposure_hint is None else float(risk_exposure_hint))
        ),
        "expires_at": _iso(stamp + _dt.timedelta(minutes=float(ttl_minutes))),
        "mode": mode,
        "payload": {
            "decision_id": decision_id,
            "action": _ACTION_TEXT[direction],
            "position_tier": tier,
            "position_mult": strength if direction != 0 else 0.0,
            "notional_usdt": float(notional_usdt),
            "adapter": "54-l1",
            "as_of": as_of,
            "l1_direction": direction,
            "l1_strength": strength,
            "l1_band": signal.get("band"),
            "l1_flags": list(signal.get("flags") or []),
            "rule_version": str(signal["rule_version"]),
            "params_hash": str(signal["params_hash"]),
        },
    }
    validate_final_decision(decision)
    return decision


def validate_final_decision(payload: Mapping[str, Any]) -> None:
    """按 49 冻结契约校验；失败抛 `HandoffError`（不静默修补字段）。"""
    try:
        jsonschema.validate(dict(payload), _schema())
    except jsonschema.ValidationError as exc:
        raise HandoffError(f"契约校验失败: {exc.message} at {list(exc.path)}") from exc


__all__ = [
    "CONTRACT_PATH",
    "HandoffError",
    "SOURCE",
    "build_final_decision",
    "execution_symbol",
    "position_tier",
    "validate_final_decision",
]
