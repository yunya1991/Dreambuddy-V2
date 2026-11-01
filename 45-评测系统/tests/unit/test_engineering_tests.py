# -*- coding: utf-8 -*-
"""test_engineering_tests.py — P2-8 工程测试与基准（E-H4 / E-W5 / E-W6）。"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from evaluators.engineering.tests import (  # noqa: E402
    BenchmarkReport,
    CoverageReport,
    EngineeringTestsEvaluator,
    EngineeringTestsInput,
    ScorecardReport,
    compute_diff_coverage,
    pycg_f1,
)


def coverage(
    added: int = 10, covered: int = 8, base: str = "base123", signature: str = "sig-abc"
) -> CoverageReport:
    return CoverageReport(
        base_sha=base,
        job_signature=signature,
        added_lines={"src/app.py": tuple(range(1, added + 1))},
        covered_lines={"src/app.py": tuple(range(1, covered + 1))},
    )


def benchmark(f1_ok: bool = True) -> BenchmarkReport:
    expected = (("a", "b"), ("b", "c"), ("c", "d"))
    predicted = expected if f1_ok else (("x", "y"),)
    return BenchmarkReport(expected_edges=expected, predicted_edges=predicted)


def scorecard(score: float = 8.0) -> ScorecardReport:
    return ScorecardReport(score=score)


def make_input(**overrides) -> EngineeringTestsInput:
    values = {"coverage": coverage(), "benchmark": benchmark(), "scorecard": scorecard()}
    values.update(overrides)
    return EngineeringTestsInput(**values)


# ---------- diff coverage 自算 ----------


def test_compute_diff_coverage_exact():
    assert compute_diff_coverage({"a.py": (1, 2, 3, 4)}, {"a.py": (1, 2)}) == pytest.approx(0.5)


def test_compute_diff_coverage_counts_only_added_lines():
    added = {"a.py": (10, 11), "b.py": (5,)}
    covered = {"a.py": (10, 99), "b.py": (5, 6)}
    assert compute_diff_coverage(added, covered) == pytest.approx(2 / 3)


def test_compute_diff_coverage_no_new_lines():
    assert compute_diff_coverage({}, {}) is None


# ---------- E-H4 ----------


def test_diff_coverage_passes_at_boundary():
    evaluator = EngineeringTestsEvaluator()
    item = evaluator.evaluate(make_input(), run_id="RUN-1")[0]
    assert item.name == "E-H4-diff-coverage"
    assert item.kind == "hard"
    assert item.status == "PASS"
    assert item.score == pytest.approx(0.80)
    assert item.n == 10


def test_diff_coverage_below_threshold_blocks():
    item = EngineeringTestsEvaluator().evaluate(
        make_input(coverage=coverage(10, 7)), run_id="RUN-1"
    )[0]
    assert item.status == "BLOCK"
    assert item.detail == "E-H4_diff_coverage_low:0.7000"


@pytest.mark.parametrize("field", ["base_sha", "job_signature"])
def test_missing_metadata_blocks(field):
    values = {"base_sha": "base123", "job_signature": "sig-abc", "coverage": coverage()}
    if field == "base_sha":
        values["coverage"] = coverage(base="")
    else:
        values["coverage"] = coverage(signature="")
    item = EngineeringTestsEvaluator().evaluate(
        make_input(coverage=values["coverage"]), run_id="RUN-1"
    )[0]
    assert item.status == "BLOCK"
    assert item.detail == f"E-H4_missing_metadata:{field}"


def test_no_new_lines_is_inconclusive():
    item = EngineeringTestsEvaluator().evaluate(
        make_input(
            coverage=CoverageReport(
                base_sha="b", job_signature="s", added_lines={}, covered_lines={}
            )
        ),
        run_id="RUN-1",
    )[0]
    assert item.status == "INCONCLUSIVE"
    assert item.detail == "E-H4_no_new_lines"


# ---------- E-W5 pycg ----------


def test_pycg_f1_perfect():
    assert pycg_f1((("a", "b"),), (("a", "b"),)) == pytest.approx(1.0)


def test_pycg_f1_reference():
    expected = (("a", "b"), ("b", "c"))
    predicted = (("a", "b"),)
    assert pycg_f1(expected, predicted) == pytest.approx(2 / 3)


def test_pycg_no_benchmark_is_inconclusive():
    item = EngineeringTestsEvaluator().evaluate(
        make_input(benchmark=BenchmarkReport(expected_edges=(), predicted_edges=())), run_id="RUN-1"
    )[1]
    assert item.name == "E-W5-pycg"
    assert item.kind == "weighted"
    assert item.status == "INCONCLUSIVE"
    assert item.detail == "E-W5_no_benchmark"


def test_pycg_below_threshold_is_inconclusive():
    item = EngineeringTestsEvaluator().evaluate(
        make_input(benchmark=benchmark(f1_ok=False)), run_id="RUN-1"
    )[1]
    assert item.status == "INCONCLUSIVE"
    assert item.detail == "E-W5_f1_low:0.0000"


# ---------- E-W6 Scorecard ----------


def test_scorecard_boundary_passes():
    item = EngineeringTestsEvaluator().evaluate(
        make_input(scorecard=scorecard(7.0)), run_id="RUN-1"
    )[2]
    assert item.name == "E-W6-scorecard"
    assert item.status == "PASS"
    assert item.score == pytest.approx(7.0)


def test_scorecard_below_threshold_is_inconclusive():
    item = EngineeringTestsEvaluator().evaluate(
        make_input(scorecard=scorecard(6.9)), run_id="RUN-1"
    )[2]
    assert item.status == "INCONCLUSIVE"
    assert item.detail == "E-W6_score_low:6.9"


# ---------- 输入校验 ----------


@pytest.mark.parametrize("score", [-1.0, 10.5])
def test_scorecard_range_validated(score):
    with pytest.raises(ValueError):
        ScorecardReport(score=score)
