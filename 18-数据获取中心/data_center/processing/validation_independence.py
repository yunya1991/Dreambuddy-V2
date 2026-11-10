"""验证独立性判定 — SPEC §2.10 A3。

问题：50 的 `DimensionForce` 由 `path.metadata["weight"]` 构造，输入含 40/42，
与 48 同源。若直接把它称为"独立验证"，等于自证。

本模块只做一件事：给出可复核的 `validation_type` 标签。

独立源三选一（满足其一即可）：
  ① 频率不同且比值 ≥2（如 1h × 日线）
  ② 供应商不同（如 yfinance × binance）
  ③ 验证快照滞后 ≥24h

不满足 → `same_source_review`（同源复核），不得对外称独立验证。

FAIL-OPEN：异常一律判为 same_source_review（保守），不抛。
"""

from __future__ import annotations

import logging
import re
from dataclasses import asdict, dataclass
from typing import Any

logger = logging.getLogger("data_center.processing.validation_independence")

VALIDATION_TYPES = ("independent", "same_source_review")

_FREQ_HOURS = {
    "15m": 0.25,
    "30m": 0.5,
    "1h": 1.0,
    "hourly": 1.0,
    "2h": 2.0,
    "4h": 4.0,
    "1d": 24.0,
    "daily": 24.0,
}
_FREQ_RE = re.compile(r"^(\d+)\s*([mhd])$")
FREQ_RATIO_MIN = 3.0
LAG_HOURS_MIN = 24.0


@dataclass(frozen=True)
class SourceProfile:
    source_id: str
    frequency: str
    supplier: str
    lag_hours: float = 0.0

    def as_dict(self) -> dict:
        return asdict(self)


def _freq_hours(freq: Any) -> float | None:
    s = str(freq or "").strip().lower()
    if not s:
        return None
    if s in _FREQ_HOURS:
        return _FREQ_HOURS[s]
    m = _FREQ_RE.match(s)
    if not m:
        return None
    n, unit = float(m.group(1)), m.group(2)
    return n * {"m": 1 / 60, "h": 1.0, "d": 24.0}[unit]


def _coerce(x: Any) -> SourceProfile:
    if isinstance(x, SourceProfile):
        return x
    if isinstance(x, dict):
        return SourceProfile(
            source_id=str(x.get("source_id") or ""),
            frequency=str(x.get("frequency") or ""),
            supplier=str(x.get("supplier") or ""),
            lag_hours=float(x.get("lag_hours") or 0.0),
        )
    raise TypeError(f"unsupported profile: {type(x).__name__}")


def classify_independence(primary: Any, validator: Any) -> dict:
    """→ {validation_type, rules, reason, primary, validator}。"""
    result: dict[str, Any] = {
        "validation_type": "same_source_review",
        "rules": [],
        "reason": "",
        "primary": None,
        "validator": None,
    }
    try:
        p = _coerce(primary)
        v = _coerce(validator)
        result["primary"] = p.as_dict()
        result["validator"] = v.as_dict()

        rules: list[str] = []
        reasons: list[str] = []

        fp, fv = _freq_hours(p.frequency), _freq_hours(v.frequency)
        if fp and fv:
            ratio = max(fp, fv) / min(fp, fv)
            if ratio >= FREQ_RATIO_MIN:
                rules.append("frequency")
            else:
                reasons.append(f"频率接近({p.frequency} vs {v.frequency})")
        else:
            reasons.append("频率不可解析")

        if p.supplier and v.supplier and p.supplier.lower() != v.supplier.lower():
            rules.append("supplier")
        else:
            reasons.append("供应商相同或缺失")

        if float(v.lag_hours) >= LAG_HOURS_MIN:
            rules.append("lag_24h")
        else:
            reasons.append(f"滞后不足({v.lag_hours}h)")

        result["rules"] = rules
        if rules:
            result["validation_type"] = "independent"
            result["reason"] = "满足独立条件：" + "、".join(rules)
        else:
            result["reason"] = "同源复核：" + "；".join(reasons)
        return result
    except Exception as e:  # noqa: BLE003  FAIL-OPEN
        logger.warning("[FAIL-OPEN] classify_independence %s: %s", type(e).__name__, str(e)[:120])
        result["reason"] = f"error:{type(e).__name__}"
        return result


def stamp_validation(row: dict, primary: Any, validator: Any) -> dict:
    """给产物行盖章，不修改入参。"""
    try:
        verdict = classify_independence(primary, validator)
        out = dict(row) if isinstance(row, dict) else {}
        out["validation_type"] = verdict["validation_type"]
        out["independence_rules"] = list(verdict["rules"])
        src = verdict.get("validator") or {}
        out["validator_source"] = src.get("source_id") if isinstance(src, dict) else None
        return out
    except Exception as e:  # noqa: BLE003  FAIL-OPEN
        logger.warning("[FAIL-OPEN] stamp_validation %s: %s", type(e).__name__, str(e)[:120])
        out = dict(row) if isinstance(row, dict) else {}
        out["validation_type"] = "same_source_review"
        out["independence_rules"] = []
        out["validator_source"] = None
        return out
