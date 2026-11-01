# -*- coding: utf-8 -*-
"""test_stress_sampling.py — P2-6 AI 压测达标率 + 分层抽样。"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from evaluators.ai.stress import (  # noqa: E402
    StressEvaluator,
    StressPlan,
    StressSample,
)
from scorers.human.sampling import (  # noqa: E402
    SamplingError,
    stratified_sample,
)


def sample(p95: float = 200, rps: float = 100, error: float = 0.0) -> StressSample:
    return StressSample(concurrency=50, p95_latency_ms=p95, throughput_rps=rps, error_rate=error)


def plan(target: float = 0.80, min_n: int = 30) -> StressPlan:
    return StressPlan(
        p95_max_ms=500, throughput_min_rps=50, max_error_rate=0.01, target=target, min_n=min_n
    )


# ---------- A-W2 压测 ----------


def test_stress_pass_rate_meets_target():
    samples = [sample() for _ in range(30)]
    items = StressEvaluator().evaluate(samples, plan=plan(), run_id="RUN-1")
    assert [i.name for i in items] == ["A-W2-stress"]
    assert items[0].kind == "weighted"
    assert items[0].status == "PASS"
    assert items[0].score == pytest.approx(1.0)
    assert items[0].n == 30


def test_stress_below_target_is_inconclusive():
    samples = [sample(p95=900) for _ in range(30)]
    item = StressEvaluator().evaluate(samples, plan=plan(), run_id="RUN-1")[0]
    assert item.status == "INCONCLUSIVE"
    assert item.score == pytest.approx(0.0)
    assert item.detail == "A-W2_pass_rate_low:0.0000"


def test_stress_samples_below_min_n():
    samples = [sample() for _ in range(29)]
    item = StressEvaluator().evaluate(samples, plan=plan(), run_id="RUN-1")[0]
    assert item.status == "INCONCLUSIVE"
    assert item.detail == "A-W2_samples_low:29"


def test_stress_each_criterion_can_fail():
    cases = [
        sample(p95=501),
        sample(rps=49),
        sample(error=0.02),
    ]
    for bad in cases:
        samples = [bad for _ in range(30)]
        item = StressEvaluator().evaluate(samples, plan=plan(), run_id="RUN-1")[0]
        assert item.status == "INCONCLUSIVE"


def test_stress_target_boundary_passes():
    samples = [sample(p95=900) for _ in range(6)] + [sample() for _ in range(24)]
    item = StressEvaluator().evaluate(samples, plan=plan(target=0.80), run_id="RUN-1")[0]
    assert item.status == "PASS"
    assert item.score == pytest.approx(0.80)


def test_stress_invalid_sample_rejected():
    with pytest.raises(ValueError):
        StressSample(concurrency=-1, p95_latency_ms=100, throughput_rps=100, error_rate=0.0)


# ---------- 分层抽样 ----------


def test_stratified_sample_proportional():
    population = (
        [(f"a{i}", "A") for i in range(100)]
        + [(f"b{i}", "B") for i in range(50)]
        + [(f"c{i}", "C") for i in range(50)]
    )
    result = stratified_sample(population, n=20, seed=7)
    assert len(result.items) == 20
    assert result.per_stratum == {"A": 10, "B": 5, "C": 5}
    assert len(set(result.items)) == 20


def test_stratified_sample_is_deterministic():
    population = [(f"i{i}", "A" if i % 3 else "B") for i in range(60)]
    first = stratified_sample(population, n=12, seed=42)
    second = stratified_sample(population, n=12, seed=42)
    assert first.items == second.items


def test_stratified_sample_guarantees_each_stratum():
    population = [(f"a{i}", "A") for i in range(98)] + [("b0", "B"), ("c0", "C")]
    result = stratified_sample(population, n=10, seed=1)
    assert set(result.per_stratum) == {"A", "B", "C"}
    assert all(value >= 1 for value in result.per_stratum.values())
    assert sum(result.per_stratum.values()) == 10


@pytest.mark.parametrize(
    "population,n",
    [
        ([], 5),
        ([("a", "A"), ("b", "B")], 0),
        ([("a", "A"), ("b", "B")], 5),
        ([("a", "A"), ("b", "B"), ("c", "C")], 2),  # 样本数少于层数
    ],
)
def test_stratified_sample_invalid(population, n):
    with pytest.raises(SamplingError):
        stratified_sample(population, n=n)
