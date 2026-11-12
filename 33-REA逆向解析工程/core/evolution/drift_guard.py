"""Drift Guard — T-G5 度量漂移守卫

SPEC-33-G G-G5 / §2.3 metric_drift：
  - cycles / god_components / fan_out 相对基线涨幅超阈值 → 降级 review
  - adoption 相对基线跌幅超阈值 → 降级 review
  - 降级必须同时产出 Evidence（append-only JSONL）
  - 阈值来自配置；严格大于才触发；基线为 0 且当前 > 0 保守判 drift

工程约束：纯标准库；配置键 `*_pct` 表示涨幅阈值、`*_drop_pct` 表示跌幅阈值。
"""

from __future__ import annotations

import json
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

DEFAULT_THRESHOLDS: Dict[str, float] = {
    "cycles_pct": 30.0,
    "god_components_pct": 30.0,
    "fan_out_pct": 30.0,
    "adoption_drop_pct": 20.0,
}

_INCREASE_KEY = re.compile(r"^(?P<metric>.+)_pct$")
_DROP_KEY = re.compile(r"^(?P<metric>.+)_drop_pct$")


class DriftGuard:
    def __init__(
        self,
        evidence_dir: str | Path,
        *,
        thresholds: Optional[Dict[str, float]] = None,
        clock: Optional[Callable[[], datetime]] = None,
    ):
        self.evidence_dir = Path(evidence_dir)
        self.thresholds = dict(DEFAULT_THRESHOLDS)
        if thresholds is not None:
            self.thresholds.update({str(key): float(value) for key, value in thresholds.items()})
        self.clock = clock or (lambda: datetime.now(timezone.utc))

    # ---------------------------------------------------------------- 检查

    def check(self, current: Dict[str, Any], baseline: Dict[str, Any]) -> Dict[str, Any]:
        current = dict(current or {})
        baseline = dict(baseline or {})
        drifts: List[Dict[str, Any]] = []

        for key, threshold in sorted(self.thresholds.items()):
            drop_match = _DROP_KEY.match(key)
            increase_match = _INCREASE_KEY.match(key)
            if drop_match:
                metric = drop_match.group("metric")
                direction = "decrease"
            elif increase_match:
                metric = increase_match.group("metric")
                direction = "increase"
            else:
                continue
            if metric not in current or metric not in baseline:
                continue

            base_value = _num(baseline.get(metric))
            current_value = _num(current.get(metric))
            if base_value is None or current_value is None:
                continue

            if base_value == 0:
                if current_value > 0:
                    drifts.append(
                        {
                            "metric": metric,
                            "direction": direction,
                            "baseline": base_value,
                            "current": current_value,
                            "pct": None,
                            "threshold": float(threshold),
                            "reason": "基线为 0，无法计算百分比，保守判 drift",
                        }
                    )
                continue

            pct = (current_value - base_value) / abs(base_value) * 100.0
            triggered = pct > threshold if direction == "increase" else pct < -threshold
            if triggered:
                drifts.append(
                    {
                        "metric": metric,
                        "direction": direction,
                        "baseline": base_value,
                        "current": current_value,
                        "pct": round(pct, 4),
                        "threshold": float(threshold),
                    }
                )

        return {"status": "review" if drifts else "ok", "drifts": drifts}

    # ---------------------------------------------------------------- 留证

    def guard(
        self,
        current: Dict[str, Any],
        baseline: Dict[str, Any],
        *,
        policy_id: str = "drift-guard",
    ) -> Dict[str, Any]:
        result = self.check(current, baseline)
        result["policy_id"] = policy_id
        if result["status"] != "review":
            return result

        recorded_at = self._now()
        evidence_id = f"EV-DRIFT-{recorded_at.strftime('%Y%m%d%H%M%S')}-{uuid.uuid4().hex[:8]}"
        record = {
            "evidence_id": evidence_id,
            "kind": "metric_drift",
            "verdict": "review",
            "policy_id": policy_id,
            "baseline": dict(baseline or {}),
            "current": dict(current or {}),
            "drifts": result["drifts"],
            "thresholds": dict(self.thresholds),
            "provenance": "drift_guard",
            "created_at": recorded_at.isoformat(),
        }
        path = self.evidence_dir / "drift_guard.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")

        result["evidence_id"] = evidence_id
        result["evidence_path"] = str(path)
        return result

    def _now(self) -> datetime:
        return self.clock()


def _num(value: Any) -> Optional[float]:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
