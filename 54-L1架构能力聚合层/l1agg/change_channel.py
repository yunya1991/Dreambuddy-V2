# -*- coding: utf-8 -*-
"""T7-2c 受控参数变更通道（SPEC-20261116 §5.8.4）。

链路：预注册 → 48 nested_walk_forward → 期级同号 → verdict → 升版本。
只读核对（48-涌现架构/reflection/nested_walk_forward.py）：
  `nested_walk_forward(dates, candidates, eval_fn(cand, train, test) -> float,
   *, outer_folds=4, inner_folds=3, embargo=1, min_train=20) -> NestedResult`
  `NestedResult{mean_inner_score, mean_outer_score, selection_gap, leakage_free, degraded, reason}`

边界：
  - 本模块**不判定 verdict 以外的语义**：verdict 只由 `decide_verdict` 按冻结规则给出；
  - `verified` 才允许升版本，且必须落回滚快照；
  - 48 模块不可用时 FAIL-OPEN 为 `insufficient_data`，绝不晋级。
"""

from __future__ import annotations

import importlib
import json
import os
import sys
from datetime import datetime, timezone
from typing import Any, Callable, Dict, Mapping, Optional, Sequence

from .experiment_prereg import VERDICT_SCHEME, apply_outcome

MODULE_ROOT = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
ROLLBACK_DIR = os.path.join(MODULE_ROOT, "reports", "reflection", "rollback")
EMERGENCE_ROOT = os.path.normpath(os.path.join(MODULE_ROOT, "..", "48-涌现架构"))

MIN_CANDIDATE_PERIODS = 3
MIN_VERIFIED_PERIODS = 8
MAX_GAP_RATIO = 0.2


def _load_nested_walk_forward() -> Optional[Callable[..., Any]]:
    """懒加载 48 的嵌套 walk-forward；不可用返回 None（FAIL-OPEN）。"""
    if EMERGENCE_ROOT not in sys.path:
        sys.path.insert(0, EMERGENCE_ROOT)
    try:
        module = importlib.import_module("reflection.nested_walk_forward")
    except Exception:  # noqa: BLE001  FAIL-OPEN
        return None
    return getattr(module, "nested_walk_forward", None)


def nested_check(
    dates: Sequence[Any],
    candidates: Sequence[Any],
    eval_fn: Callable[[Any, Sequence[str], Sequence[str]], float],
    *,
    outer_folds: int = 4,
    inner_folds: int = 3,
    embargo: int = 1,
    min_train: int = 20,
) -> Dict[str, Any]:
    """跑一次嵌套 walk-forward，返回扁平统计；异常一律 degraded。"""
    runner = _load_nested_walk_forward()
    if runner is None:
        return {
            "degraded": True,
            "reason": "nested_walk_forward_unavailable",
            "leakage_free": False,
        }
    try:
        result = runner(
            dates,
            candidates,
            eval_fn,
            outer_folds=outer_folds,
            inner_folds=inner_folds,
            embargo=embargo,
            min_train=min_train,
        )
        payload = result.to_dict() if hasattr(result, "to_dict") else dict(result)
    except Exception as exc:  # noqa: BLE001  FAIL-OPEN
        return {"degraded": True, "reason": f"error:{type(exc).__name__}", "leakage_free": False}
    payload.pop("folds", None)
    return payload


def decide_verdict(
    stats: Mapping[str, Any],
    *,
    same_sign_periods: int,
    wilson_lb: float,
    base_rate: float,
    effect_bps: float,
    cost_bps: float,
    opposite_significant: bool = False,
) -> Dict[str, Any]:
    """冻结规则，顺序不可调换（先排除不可信，再判强度）。"""
    if stats.get("degraded") or not stats.get("leakage_free"):
        return {
            "verdict": "insufficient_data",
            "reason_code": str(stats.get("reason") or "leakage_or_degraded"),
        }

    mean_inner = stats.get("mean_inner_score")
    if mean_inner is None or float(mean_inner) <= 0:
        return {"verdict": "rejected", "reason_code": "non_positive_inner_score"}

    gap = stats.get("selection_gap")
    if gap is not None and float(gap) / float(mean_inner) > MAX_GAP_RATIO:
        return {"verdict": "rejected", "reason_code": "selection_overfit"}

    if opposite_significant and int(same_sign_periods) >= MIN_CANDIDATE_PERIODS:
        return {"verdict": "falsified", "reason_code": "opposite_direction_significant"}

    if int(same_sign_periods) < MIN_CANDIDATE_PERIODS:
        return {"verdict": "insufficient_data", "reason_code": "fewer_than_three_periods"}

    if (
        int(same_sign_periods) >= MIN_VERIFIED_PERIODS
        and float(wilson_lb) > float(base_rate)
        and float(effect_bps) > float(cost_bps)
    ):
        return {"verdict": "verified", "reason_code": "eight_periods_and_wilson_above_base"}

    return {"verdict": "candidate", "reason_code": "three_to_seven_periods"}


def _bump(version: str) -> str:
    parts = str(version or "1.0.0").split(".")
    try:
        parts[-1] = str(int(parts[-1]) + 1)
    except ValueError:
        parts[-1] = "1"
    return ".".join(parts)


def propose_change(
    *,
    experiment_id: str,
    verdict: str,
    current_version: str,
    params: Mapping[str, Any],
    frozen_params_hash: str,
    rollback_dir: Optional[str] = None,
    now: Optional[datetime] = None,
) -> Dict[str, Any]:
    """只有 verified 才允许升版本，并写回滚快照。"""
    if verdict != "verified":
        return {"ok": False, "reason": "not_verified", "verdict": verdict}
    stamp = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    target_dir = rollback_dir or ROLLBACK_DIR
    os.makedirs(target_dir, exist_ok=True)
    previous, current = str(current_version), _bump(current_version)
    snapshot = {
        "experiment_id": experiment_id,
        "previous_version": previous,
        "new_version": current,
        "params": dict(params),
        "frozen_params_hash": frozen_params_hash,
        "applied_at": stamp.isoformat(timespec="seconds"),
    }
    path = os.path.join(target_dir, f"{experiment_id}-{stamp.strftime('%Y%m%dT%H%M%S')}.json")
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(snapshot, fh, ensure_ascii=False, indent=2, sort_keys=True)
    return {
        "ok": True,
        "experiment_id": experiment_id,
        "previous_version": previous,
        "new_version": current,
        "snapshot_path": path,
    }


def record_verdict(
    *,
    experiment_id: str,
    decision: Mapping[str, Any],
    effect: Optional[float],
    db_path: Optional[str] = None,
) -> Dict[str, Any]:
    """把裁决写回 54 预注册表；54 不产生 verdict，只落库。"""
    return apply_outcome(
        {
            "experiment_id": experiment_id,
            "verdict": decision.get("verdict"),
            "verdict_scheme": VERDICT_SCHEME,
            "effect": effect,
            "reason_code": decision.get("reason_code"),
        },
        db_path=db_path,
    )
