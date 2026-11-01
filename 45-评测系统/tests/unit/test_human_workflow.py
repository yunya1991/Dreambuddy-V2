# -*- coding: utf-8 -*-
"""
test_human_workflow.py — P4-4 人工评测工作流
=============================================
验收（PLAN P4-4 / SPEC §10.1–§10.3 / D-03）：
- 分层抽样 + 双标重叠 10–20%（默认 15%），标注者盲测（不暴露版本与预期）
- 多标注聚合：一致即定稿，分歧必须第三方仲裁（记录理由），仲裁样本计入最终分
- 一致性：Krippendorff's α（ordinal）下限 0.67、Cohen's κ≥0.60；
  不足 → 该评测项 INCONCLUSIVE（不用点估计下结论）
- 记录每层工时、单样本成本、脱敏标注者 ID；rubric 版本与 EvalSpec 绑定
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from scorers.human.workflow import (  # noqa: E402
    ALPHA_MIN,
    KAPPA_MIN,
    OVERLAP_DEFAULT,
    OVERLAP_MAX,
    OVERLAP_MIN,
    Annotation,
    Arbitration,
    HumanItem,
    Rubric,
    WorkflowError,
    build_plan,
    build_report,
    consistency_report,
    mask_annotator,
    resolve,
)
from scorers.model.calibration import (  # noqa: E402
    CalibrationError,
    cohen_kappa,
    krippendorff_alpha,
    krippendorff_alpha_ordinal,
)

PRIMARY = "annotator-A"
SECONDARY = "annotator-B"
ARBITRATOR = "arbiter-X"


def make_items(count: int = 20) -> list[HumanItem]:
    return [
        HumanItem(
            item_id=f"item-{index:02d}",
            stratum=("easy", "hard")[index % 2],
            payload={"prompt": f"question-{index}"},
        )
        for index in range(count)
    ]


def make_rubric() -> Rubric:
    return Rubric(rubric_id="RUB-human", version="1.2.0", labels=("fail", "pass"))


def make_plan(items: list[HumanItem] | None = None, *, seed: int = 0):
    items = items if items is not None else make_items(20)
    return build_plan(
        items,
        len(items),
        seed=seed,
        primary_annotator=PRIMARY,
        secondary_annotator=SECONDARY,
        overlap_ratio=OVERLAP_DEFAULT,
    )


def label_all(plan, label: str) -> list[Annotation]:
    annotations = [
        Annotation(item_id=item_id, annotator_id=annotator, label=label)
        for item_id, annotator in plan.primary.items()
    ]
    annotations += [
        Annotation(item_id=item_id, annotator_id=annotator, label=label)
        for item_id, annotator in plan.secondary.items()
    ]
    return annotations


# ---------- 抽样与双标重叠 ----------


def test_overlap_default_is_15_percent() -> None:
    assert OVERLAP_MIN == 0.10
    assert OVERLAP_MAX == 0.20
    assert OVERLAP_DEFAULT == 0.15

    plan = make_plan()
    overlap = len(plan.secondary)
    assert overlap == 3
    assert plan.overlap_ratio == pytest.approx(overlap / len(plan.sampling.items))
    assert OVERLAP_MIN <= plan.overlap_ratio <= OVERLAP_MAX


def test_overlap_ratio_below_min_rejected() -> None:
    with pytest.raises(WorkflowError):
        build_plan(make_items(20), 20, overlap_ratio=0.05)


def test_overlap_ratio_above_max_rejected() -> None:
    with pytest.raises(WorkflowError):
        build_plan(make_items(20), 20, overlap_ratio=0.30)


def test_secondary_subset_of_primary() -> None:
    plan = make_plan()
    assert set(plan.secondary) <= set(plan.primary)
    assert set(plan.primary) == set(plan.sampling.items)


def test_plan_is_deterministic_per_seed() -> None:
    first = make_plan(seed=7)
    second = make_plan(seed=7)
    assert first.sampling.items == second.sampling.items
    assert first.secondary == second.secondary


def test_blind_payload_rejects_expectations() -> None:
    for forbidden in ("expected", "answer", "label", "rubric_version", "version", "baseline"):
        item = HumanItem(
            item_id="item-01",
            stratum="easy",
            payload={"prompt": "q", forbidden: "leaked"},
        )
        with pytest.raises(WorkflowError, match="盲测"):
            build_plan([item], 1)


def test_blind_payload_clean_is_accepted() -> None:
    plan = build_plan([HumanItem(item_id="item-01", stratum="easy", payload={"prompt": "q"})], 1)
    assert plan.sampling.items == ("item-01",)


# ---------- 聚合与仲裁 ----------


def test_agreement_resolves_without_arbitration() -> None:
    rubric = make_rubric()
    annotations = [
        Annotation("item-01", PRIMARY, "pass"),
        Annotation("item-01", SECONDARY, "pass"),
        Annotation("item-02", PRIMARY, "fail"),
    ]
    outcomes = resolve(annotations, rubric=rubric)
    by_id = {outcome.item_id: outcome for outcome in outcomes}
    assert by_id["item-01"].status == "resolved"
    assert by_id["item-01"].label == "pass"
    assert by_id["item-01"].arbitrated is False
    assert by_id["item-02"].status == "resolved"


def test_divergence_requires_arbitration() -> None:
    rubric = make_rubric()
    annotations = [
        Annotation("item-01", PRIMARY, "fail"),
        Annotation("item-01", SECONDARY, "pass"),
    ]
    outcomes = resolve(annotations, rubric=rubric)
    assert outcomes[0].status == "arbitration_required"
    assert outcomes[0].label is None
    assert set(outcomes[0].labels) == {"fail", "pass"}


def test_label_outside_rubric_rejected() -> None:
    with pytest.raises(WorkflowError, match="rubric"):
        resolve([Annotation("item-01", PRIMARY, "maybe")], rubric=make_rubric())


def test_empty_annotator_rejected() -> None:
    with pytest.raises(WorkflowError, match="标注者"):
        resolve([Annotation("item-01", "", "pass")], rubric=make_rubric())


def test_arbitration_requires_reason() -> None:
    annotations = [
        Annotation("item-01", PRIMARY, "fail"),
        Annotation("item-01", SECONDARY, "pass"),
    ]
    with pytest.raises(WorkflowError, match="理由"):
        resolve(
            annotations,
            rubric=make_rubric(),
            arbitrations=[Arbitration("item-01", ARBITRATOR, "pass", "  ")],
        )


def test_arbitration_must_be_third_party() -> None:
    annotations = [
        Annotation("item-01", PRIMARY, "fail"),
        Annotation("item-01", SECONDARY, "pass"),
    ]
    with pytest.raises(WorkflowError, match="第三方"):
        resolve(
            annotations,
            rubric=make_rubric(),
            arbitrations=[Arbitration("item-01", PRIMARY, "pass", "ok")],
        )


def test_arbitration_unknown_item_rejected() -> None:
    annotations = [Annotation("item-01", PRIMARY, "fail")]
    with pytest.raises(WorkflowError, match="未知"):
        resolve(
            annotations,
            rubric=make_rubric(),
            arbitrations=[Arbitration("item-99", ARBITRATOR, "pass", "ok")],
        )


# ---------- 一致性（α 下限 0.67 / κ 下限 0.60） ----------


def test_consistency_pass_on_full_agreement() -> None:
    plan = make_plan()
    rubric = make_rubric()
    annotations = label_all(plan, "pass")
    report = consistency_report(plan, annotations, rubric)
    assert report.overlap_n == 3
    assert report.verdict == "PASS"
    assert report.alpha == pytest.approx(1.0)
    assert report.kappa == pytest.approx(1.0)
    assert report.reasons == ()


def test_consistency_inconclusive_when_alpha_below_min() -> None:
    plan = make_plan()
    rubric = make_rubric()
    secondary_ids = sorted(plan.secondary)
    primary_labels = dict.fromkeys(plan.primary, "pass")
    secondary_labels = dict.fromkeys(plan.primary, "pass")
    # 重叠样本中制造两处分歧（α 与 κ 同时跌破下限）
    for item_id in secondary_ids[:2]:
        secondary_labels[item_id] = "fail"
    annotations = [
        Annotation(item_id, annotator, primary_labels[item_id])
        for item_id, annotator in plan.primary.items()
    ] + [
        Annotation(item_id, annotator, secondary_labels[item_id])
        for item_id, annotator in plan.secondary.items()
    ]
    report = consistency_report(plan, annotations, rubric)
    assert report.overlap_n == len(secondary_ids)
    assert report.verdict == "INCONCLUSIVE"
    assert report.alpha is not None and report.alpha < ALPHA_MIN
    assert any(reason.startswith("alpha_below_min") for reason in report.reasons)


def test_consistency_inconclusive_when_overlap_too_small() -> None:
    plan = build_plan(make_items(3), 3, overlap_ratio=OVERLAP_DEFAULT)
    assert len(plan.secondary) == 1
    report = consistency_report(plan, label_all(plan, "pass"), make_rubric())
    assert report.verdict == "INCONCLUSIVE"
    assert "overlap_too_small" in report.reasons
    assert report.alpha is None and report.kappa is None


def test_kappa_min_constant_matches_spec() -> None:
    assert ALPHA_MIN == 0.67
    assert KAPPA_MIN == 0.60


# ---------- ordinal α（SPEC §10.2 要求 ordinal） ----------


def test_ordinal_alpha_full_agreement_is_one() -> None:
    labels = ("low", "mid", "high")
    assert krippendorff_alpha_ordinal([["low", "high"], ["low", "high"]], labels) == 1.0


def test_ordinal_alpha_adjacent_disagreement_beats_nominal() -> None:
    labels = ("low", "mid", "high")
    coders = [["low", "mid", "high"], ["mid", "mid", "high"]]
    ordinal = krippendorff_alpha_ordinal(coders, labels)
    nominal = krippendorff_alpha(coders)
    assert ordinal > nominal


def test_ordinal_alpha_rejects_unknown_label() -> None:
    with pytest.raises(CalibrationError):
        krippendorff_alpha_ordinal([["low", "missing"]], ("low", "mid", "high"))


def test_ordinal_alpha_requires_two_coders() -> None:
    with pytest.raises(CalibrationError):
        krippendorff_alpha_ordinal([["low", "high"]], ("low", "mid", "high"))


def test_kappa_and_nominal_alpha_still_work() -> None:
    assert cohen_kappa(["a", "b", "b"], ["a", "b", "b"]) == pytest.approx(1.0)
    assert krippendorff_alpha([["a", "b"], ["a", "b"]]) == pytest.approx(1.0)


# ---------- 最终分 / 报告 ----------


def test_arbitrated_samples_count_into_final_score() -> None:
    plan = build_plan(make_items(2), 2, overlap_ratio=OVERLAP_DEFAULT)
    rubric = make_rubric()
    annotations = [
        Annotation("item-00", PRIMARY, "fail"),
        Annotation("item-00", SECONDARY, "fail"),
        Annotation("item-01", PRIMARY, "fail"),
        Annotation("item-01", SECONDARY, "pass"),
    ]
    report = build_report(
        plan,
        annotations,
        rubric,
        arbitrations=[Arbitration("item-01", ARBITRATOR, "pass", "证据不足但方向正确")],
    )
    assert report.final_score == pytest.approx(0.5)
    assert report.resolved_count == 2
    assert report.arbitrated_count == 1
    assert report.unresolved == ()


def test_unresolved_items_are_flagged_not_scored() -> None:
    plan = build_plan(make_items(2), 2, overlap_ratio=OVERLAP_DEFAULT)
    rubric = make_rubric()
    annotations = [
        Annotation("item-00", PRIMARY, "fail"),
        Annotation("item-00", SECONDARY, "fail"),
        Annotation("item-01", PRIMARY, "fail"),
        Annotation("item-01", SECONDARY, "pass"),
    ]
    report = build_report(plan, annotations, rubric)
    assert report.final_score == pytest.approx(0.0)
    assert report.unresolved == ("item-01",)
    assert report.resolved_count == 1


def test_final_score_normalized_by_ordinal_rank() -> None:
    plan = build_plan(make_items(2), 2, overlap_ratio=OVERLAP_DEFAULT)
    rubric = Rubric("RUB-3", "2.0", ("bad", "ok", "good"))
    annotations = [
        Annotation("item-00", PRIMARY, "ok"),
        Annotation("item-01", PRIMARY, "good"),
    ]
    report = build_report(plan, annotations, rubric)
    assert report.final_score == pytest.approx(0.75)


def test_report_binds_rubric_and_records_cost() -> None:
    plan = make_plan()
    rubric = make_rubric()
    annotations = label_all(plan, "pass")
    annotations[0] = Annotation(annotations[0].item_id, PRIMARY, "pass", minutes=10.0)
    annotations.append(Annotation("item-01", SECONDARY, "pass", minutes=20.0))
    report = build_report(plan, annotations, rubric, hourly_rate=60.0)
    assert report.rubric_id == "RUB-human"
    assert report.rubric_version == "1.2.0"
    assert report.total_minutes == pytest.approx(30.0)
    assert report.minutes_by_stratum["easy"] == pytest.approx(10.0)
    assert report.minutes_by_stratum["hard"] == pytest.approx(20.0)
    assert report.cost_per_sample == pytest.approx(1.5)
    assert report.consistency.verdict == "PASS"


def test_report_masks_annotator_ids() -> None:
    plan = make_plan()
    report = build_report(plan, label_all(plan, "pass"), make_rubric())
    assert set(report.annotator_ids) == {mask_annotator(PRIMARY), mask_annotator(SECONDARY)}
    for masked in report.annotator_ids:
        assert masked.startswith("ann-")
        assert masked not in (PRIMARY, SECONDARY)
    assert mask_annotator(PRIMARY) == mask_annotator(PRIMARY)


def test_report_without_annotations_is_inconclusive() -> None:
    plan = make_plan()
    report = build_report(plan, [], make_rubric())
    assert report.final_score is None
    assert report.consistency.verdict == "INCONCLUSIVE"
    assert "overlap_too_small" in report.consistency.reasons
