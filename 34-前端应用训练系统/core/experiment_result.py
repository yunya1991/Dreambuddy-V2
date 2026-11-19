# -*- coding: utf-8 -*-
"""P0-D3D: 对照实验计划与结果（F6/F7 关闭项）。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple


def _as_tuple(value: Any) -> Tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        return (value,)
    try:
        return tuple(str(v) for v in value)
    except TypeError:
        return ()


@dataclass(frozen=True)
class ExperimentPlan:
    experiment_id: str
    decision_id: str
    hypothesis: str
    control: str
    treatment: str
    sample_size: int = 0
    metrics: Tuple[str, ...] = ()
    thresholds: Dict[str, Any] = None  # type: ignore[assignment]
    run_id: str = ""
    judgment: bool = False
    human_signoff: Optional[str] = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "metrics", _as_tuple(self.metrics))
        object.__setattr__(self, "thresholds", dict(self.thresholds or {}))

    def to_dict(self) -> Dict[str, Any]:
        return {
            "experiment_id": self.experiment_id,
            "decision_id": self.decision_id,
            "hypothesis": self.hypothesis,
            "control": self.control,
            "treatment": self.treatment,
            "sample_size": self.sample_size,
            "metrics": list(self.metrics),
            "thresholds": dict(self.thresholds),
            "run_id": self.run_id,
            "judgment": self.judgment,
            "human_signoff": self.human_signoff,
        }


@dataclass(frozen=True)
class ExperimentResult:
    experiment_id: str
    status: str = "not_run"
    metrics: Dict[str, Any] = None  # type: ignore[assignment]
    effect_size: Optional[float] = None
    ci: Optional[Tuple[float, float]] = None
    run_id: str = ""
    verdict: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "metrics", dict(self.metrics or {}))
        if self.ci is not None:
            object.__setattr__(self, "ci", tuple(self.ci))

    def to_dict(self) -> Dict[str, Any]:
        return {
            "experiment_id": self.experiment_id,
            "status": self.status,
            "metrics": dict(self.metrics),
            "effect_size": self.effect_size,
            "ci": list(self.ci) if self.ci else None,
            "run_id": self.run_id,
            "verdict": self.verdict,
        }


def validate_plan(plan: Any, tier: str = "T0") -> List[str]:
    """返回错误列表；T2/T3 必须有可复跑实验，judgment 必须有人签署。"""
    errors: List[str] = []
    if not isinstance(plan, ExperimentPlan):
        return ["invalid_plan"]
    if not plan.hypothesis:
        errors.append("hypothesis_required")
    if not plan.control:
        errors.append("control_required")
    if not plan.treatment:
        errors.append("treatment_required")
    if str(tier).upper() in {"T2", "T3"}:
        if plan.sample_size <= 0:
            errors.append("sample_size_required")
        if not plan.metrics:
            errors.append("metrics_required")
        if not plan.thresholds:
            errors.append("thresholds_required")
        if not plan.run_id:
            errors.append("run_id_required")
    if plan.judgment and not plan.human_signoff:
        errors.append("human_signoff_required")
    return errors
