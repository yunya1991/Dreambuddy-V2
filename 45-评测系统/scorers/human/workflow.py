# -*- coding: utf-8 -*-
"""
workflow.py — 人工评测工作流（P4-4，SPEC §10.1–§10.3 / D-03）
=============================================================
全流程：分层抽样 → 双标重叠（10–20%，默认 15%）→ 盲测 → 聚合/第三方仲裁 →
一致性校验（Krippendorff's α ordinal ≥0.67、Cohen's κ≥0.60）→ 最终分与成本记录。

判定语义（SPEC §4）：
- α/κ 低于下限、重叠样本 <2 → 该评测项 INCONCLUSIVE，禁止用点估计放行
- 分歧样本必须有第三方仲裁理由，仲裁结果计入最终分
"""

from __future__ import annotations

import hashlib
import random
from dataclasses import dataclass

from scorers.human.sampling import SamplingPlan, stratified_sample
from scorers.model.calibration import CalibrationError, cohen_kappa, krippendorff_alpha_ordinal

ALPHA_MIN = 0.67
ALPHA_TARGET = 0.80
KAPPA_MIN = 0.60
OVERLAP_MIN = 0.10
OVERLAP_MAX = 0.20
OVERLAP_DEFAULT = 0.15

# 盲测：标注者不得看到版本、预期与基线信息
BLIND_FORBIDDEN_KEYS = frozenset(
    {"expected", "answer", "label", "rubric_version", "version", "baseline"}
)


class WorkflowError(ValueError):
    """人工评测工作流参数非法（重叠比例/盲测泄漏/仲裁不合规/rubric 不符）。"""


@dataclass(frozen=True)
class Rubric:
    """评分细则：版本化并与 EvalSpec 绑定（SPEC §10.3）。"""

    rubric_id: str
    version: str
    labels: tuple[str, ...]

    def __post_init__(self) -> None:
        if not self.rubric_id or not self.version:
            raise WorkflowError("rubric_id 与 version 必须为非空字符串")
        if not self.labels or len(set(self.labels)) != len(self.labels):
            raise WorkflowError("rubric 等级标签必须非空且不重复")

    def rank(self, label: str) -> int:
        try:
            return self.labels.index(label)
        except ValueError as exc:
            raise WorkflowError(
                f"标签 {label!r} 不在 rubric {self.rubric_id}@{self.version}"
            ) from exc

    def normalized(self, label: str) -> float:
        if len(self.labels) == 1:
            return 1.0
        return self.rank(label) / (len(self.labels) - 1)


@dataclass(frozen=True)
class HumanItem:
    """待标注项：payload 只含标注者可见信息（盲测）。"""

    item_id: str
    stratum: str
    payload: dict[str, object]

    def __post_init__(self) -> None:
        if not self.item_id or not self.stratum:
            raise WorkflowError("item_id 与 stratum 必须为非空字符串")


@dataclass(frozen=True)
class AnnotationPlan:
    """双标计划：primary 全员标注，secondary 为重叠子集（每项两人）。"""

    sampling: SamplingPlan
    primary: dict[str, str]
    secondary: dict[str, str]
    strata: dict[str, str]
    overlap_ratio: float


@dataclass(frozen=True)
class Annotation:
    item_id: str
    annotator_id: str
    label: str
    minutes: float = 0.0


@dataclass(frozen=True)
class Arbitration:
    item_id: str
    arbitrator_id: str
    label: str
    reason: str


@dataclass(frozen=True)
class ItemOutcome:
    item_id: str
    status: str  # resolved / arbitration_required
    label: str | None
    labels: tuple[str, ...]
    arbitrated: bool = False


@dataclass(frozen=True)
class ConsistencyReport:
    alpha: float | None
    kappa: float | None
    overlap_n: int
    verdict: str  # PASS / INCONCLUSIVE
    reasons: tuple[str, ...]


@dataclass(frozen=True)
class HumanReport:
    rubric_id: str
    rubric_version: str
    item_count: int
    resolved_count: int
    unresolved: tuple[str, ...]
    arbitrated_count: int
    final_score: float | None
    consistency: ConsistencyReport
    total_minutes: float
    minutes_by_stratum: dict[str, float]
    cost_per_sample: float
    annotator_ids: tuple[str, ...]


def build_plan(
    items: list[HumanItem],
    n: int,
    *,
    seed: int = 0,
    primary_annotator: str = "annotator-1",
    secondary_annotator: str = "annotator-2",
    overlap_ratio: float = OVERLAP_DEFAULT,
) -> AnnotationPlan:
    """分层抽样 + 双标重叠（10–20%），重叠子集按固定 seed 确定性选取。"""
    if not OVERLAP_MIN <= overlap_ratio <= OVERLAP_MAX:
        raise WorkflowError(
            f"双标重叠比例必须在 {OVERLAP_MIN:.0%}–{OVERLAP_MAX:.0%}，收到 {overlap_ratio:.0%}"
        )
    if not primary_annotator or not secondary_annotator:
        raise WorkflowError("标注者 ID 不得为空")
    if primary_annotator == secondary_annotator:
        raise WorkflowError("双标必须由两名不同标注者执行")
    _validate_blind(items)

    sampling = stratified_sample([(item.item_id, item.stratum) for item in items], n, seed=seed)
    ids = list(sampling.items)
    overlap_count = min(len(ids), max(1, round(len(ids) * overlap_ratio)))

    pool = list(ids)
    random.Random(seed).shuffle(pool)
    secondary_ids = sorted(pool[:overlap_count])

    return AnnotationPlan(
        sampling=sampling,
        primary=dict.fromkeys(ids, primary_annotator),
        secondary=dict.fromkeys(secondary_ids, secondary_annotator),
        strata={item.item_id: item.stratum for item in items},
        overlap_ratio=len(secondary_ids) / len(ids),
    )


def resolve(
    annotations: list[Annotation],
    *,
    rubric: Rubric,
    arbitrations: list[Arbitration] | tuple[Arbitration, ...] = (),
) -> tuple[ItemOutcome, ...]:
    """聚合标注：一致即定稿；分歧必须由第三方仲裁（附理由）才定稿。"""
    grouped = _group(annotations)
    pending = {arbitration.item_id: arbitration for arbitration in arbitrations}

    for item_id, arbitration in pending.items():
        if item_id not in grouped:
            raise WorkflowError(f"仲裁指向未知评测项：{item_id}")
        if not arbitration.reason.strip():
            raise WorkflowError("第三方仲裁必须记录理由")
        annotators = {annotation.annotator_id for annotation in grouped[item_id]}
        if arbitration.arbitrator_id in annotators:
            raise WorkflowError("仲裁必须由第三方裁定，不得由原标注者自裁")
        rubric.rank(arbitration.label)

    outcomes: list[ItemOutcome] = []
    for item_id in sorted(grouped):
        labels: list[str] = []
        for annotation in grouped[item_id]:
            if not annotation.annotator_id.strip():
                raise WorkflowError("标注者 ID 不得为空")
            rubric.rank(annotation.label)
            labels.append(annotation.label)

        if item_id in pending:
            outcomes.append(
                ItemOutcome(item_id, "resolved", pending[item_id].label, tuple(labels), True)
            )
        elif len(set(labels)) == 1:
            outcomes.append(ItemOutcome(item_id, "resolved", labels[0], tuple(labels), False))
        else:
            outcomes.append(
                ItemOutcome(item_id, "arbitration_required", None, tuple(labels), False)
            )
    return tuple(outcomes)


def consistency_report(
    plan: AnnotationPlan, annotations: list[Annotation], rubric: Rubric
) -> ConsistencyReport:
    """只用计划内的双标重叠样本计算一致性（SPEC §10.2）。"""
    grouped = _group(annotations)
    primary_labels: list[str] = []
    secondary_labels: list[str] = []
    for item_id in sorted(plan.secondary):
        primary_label = _label_of(grouped.get(item_id, ()), plan.primary[item_id])
        secondary_label = _label_of(grouped.get(item_id, ()), plan.secondary[item_id])
        if primary_label is None or secondary_label is None:
            continue
        rubric.rank(primary_label)
        rubric.rank(secondary_label)
        primary_labels.append(primary_label)
        secondary_labels.append(secondary_label)

    overlap_n = len(primary_labels)
    if overlap_n < 2:
        return ConsistencyReport(None, None, overlap_n, "INCONCLUSIVE", ("overlap_too_small",))

    try:
        alpha = krippendorff_alpha_ordinal([primary_labels, secondary_labels], rubric.labels)
    except CalibrationError as exc:
        return ConsistencyReport(None, None, overlap_n, "INCONCLUSIVE", (f"alpha_error:{exc}",))
    kappa = cohen_kappa(primary_labels, secondary_labels)

    reasons: list[str] = []
    if alpha < ALPHA_MIN:
        reasons.append(f"alpha_below_min:{alpha:.4f}")
    if kappa < KAPPA_MIN:
        reasons.append(f"kappa_below_min:{kappa:.4f}")
    return ConsistencyReport(
        alpha=alpha,
        kappa=kappa,
        overlap_n=overlap_n,
        verdict="INCONCLUSIVE" if reasons else "PASS",
        reasons=tuple(reasons),
    )


def build_report(
    plan: AnnotationPlan,
    annotations: list[Annotation],
    rubric: Rubric,
    *,
    arbitrations: list[Arbitration] | tuple[Arbitration, ...] = (),
    hourly_rate: float = 0.0,
) -> HumanReport:
    """汇总最终分、一致性与成本（仲裁样本计入最终分，未决样本不计分）。"""
    outcomes = resolve(annotations, rubric=rubric, arbitrations=arbitrations)
    resolved = [outcome for outcome in outcomes if outcome.status == "resolved"]

    final_score: float | None = None
    if resolved:
        total = sum(rubric.normalized(outcome.label) for outcome in resolved if outcome.label)
        final_score = total / len(resolved)

    total_minutes = 0.0
    minutes_by_stratum: dict[str, float] = {}
    annotated_items: set[str] = set()
    for annotation in annotations:
        minutes = float(annotation.minutes)
        if minutes < 0:
            raise WorkflowError("标注工时不得为负")
        total_minutes += minutes
        stratum = plan.strata.get(annotation.item_id)
        if stratum is not None:
            minutes_by_stratum[stratum] = minutes_by_stratum.get(stratum, 0.0) + minutes
        annotated_items.add(annotation.item_id)

    total_cost = total_minutes / 60 * hourly_rate
    cost_per_sample = total_cost / len(annotated_items) if annotated_items else 0.0

    return HumanReport(
        rubric_id=rubric.rubric_id,
        rubric_version=rubric.version,
        item_count=len(plan.sampling.items),
        resolved_count=len(resolved),
        unresolved=tuple(outcome.item_id for outcome in outcomes if outcome.status != "resolved"),
        arbitrated_count=sum(1 for outcome in outcomes if outcome.arbitrated),
        final_score=final_score,
        consistency=consistency_report(plan, annotations, rubric),
        total_minutes=total_minutes,
        minutes_by_stratum=minutes_by_stratum,
        cost_per_sample=cost_per_sample,
        annotator_ids=tuple(
            sorted({mask_annotator(annotation.annotator_id) for annotation in annotations})
        ),
    )


def mask_annotator(annotator_id: str) -> str:
    """标注者 ID 脱敏（SPEC §10.3）：稳定哈希前缀，便于审计对账。"""
    digest = hashlib.sha256(annotator_id.encode("utf-8")).hexdigest()
    return f"ann-{digest[:10]}"


def _validate_blind(items: list[HumanItem]) -> None:
    seen: set[str] = set()
    for item in items:
        if item.item_id in seen:
            raise WorkflowError(f"评测项 ID 重复：{item.item_id}")
        seen.add(item.item_id)
        leaked = BLIND_FORBIDDEN_KEYS & set(item.payload)
        if leaked:
            raise WorkflowError(f"人工标注项必须盲测，payload 不得含：{sorted(leaked)}")


def _group(annotations: list[Annotation]) -> dict[str, list[Annotation]]:
    grouped: dict[str, list[Annotation]] = {}
    for annotation in annotations:
        grouped.setdefault(annotation.item_id, []).append(annotation)
    return grouped


def _label_of(
    annotations: tuple[Annotation, ...] | list[Annotation], annotator_id: str
) -> str | None:
    for annotation in annotations:
        if annotation.annotator_id == annotator_id:
            return annotation.label
    return None
