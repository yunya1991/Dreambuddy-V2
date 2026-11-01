# -*- coding: utf-8 -*-
"""
tests.py — 工程测试与基准（P2-8，SPEC §5.3）
==============================================
- E-H4 新增行覆盖率：按 base_sha 自算（不信任提交方数字），≥0.80；缺 base_sha / job 签名即 BLOCK
- E-W5 pycg 基准集对照：F1 ≥0.70（加权项，不达标 INCONCLUSIVE）
- E-W6 OpenSSF Scorecard：≥7.0/10（加权项）

覆盖率输入只接受「行号集合」，避免提交方预置覆盖率文件（防绕过）。
"""

from __future__ import annotations

from dataclasses import dataclass, field

from storage.repo import EvalItemRecord

DIFF_COVERAGE_MIN = 0.80
PYCG_F1_MIN = 0.70
SCORECARD_MIN = 7.0


@dataclass(frozen=True)
class CoverageReport:
    """覆盖率报告：必须带 base_sha 与 job 签名，45 自算 diff coverage。"""

    base_sha: str
    job_signature: str
    added_lines: dict[str, tuple[int, ...]] = field(default_factory=dict)
    covered_lines: dict[str, tuple[int, ...]] = field(default_factory=dict)


@dataclass(frozen=True)
class BenchmarkReport:
    """pycg 基准集对照：调用边集合（expected=基准，predicted=被测）。"""

    expected_edges: tuple[tuple[str, str], ...]
    predicted_edges: tuple[tuple[str, str], ...]


@dataclass(frozen=True)
class ScorecardReport:
    score: float

    def __post_init__(self) -> None:
        if not 0.0 <= self.score <= 10.0:
            raise ValueError(f"Scorecard 分值必须落在 [0,10]，收到 {self.score}")


@dataclass(frozen=True)
class EngineeringTestsInput:
    coverage: CoverageReport
    benchmark: BenchmarkReport
    scorecard: ScorecardReport


def compute_diff_coverage(
    added_lines: dict[str, tuple[int, ...]],
    covered_lines: dict[str, tuple[int, ...]],
) -> float | None:
    """新增行覆盖率 = 新增且被覆盖的行数 / 新增行数；无新增行返回 None。"""
    added = {(path, line) for path, lines in added_lines.items() for line in lines}
    if not added:
        return None
    covered = {(path, line) for path, lines in covered_lines.items() for line in lines}
    return len(added & covered) / len(added)


def pycg_f1(
    expected_edges: tuple[tuple[str, str], ...],
    predicted_edges: tuple[tuple[str, str], ...],
) -> float | None:
    """基准集 F1；基准为空返回 None（无法对照）。"""
    expected = set(expected_edges)
    if not expected:
        return None
    predicted = set(predicted_edges)
    true_positive = len(expected & predicted)
    if true_positive == 0:
        return 0.0
    precision = true_positive / len(predicted)
    recall = true_positive / len(expected)
    return 2 * precision * recall / (precision + recall)


class EngineeringTestsEvaluator:
    """E-H4（硬）+ E-W5 / E-W6（加权）。"""

    def evaluate(self, data: EngineeringTestsInput, run_id: str) -> list[EvalItemRecord]:
        return [
            self._diff_coverage_item(data.coverage, run_id),
            self._pycg_item(data.benchmark, run_id),
            self._scorecard_item(data.scorecard, run_id),
        ]

    def _diff_coverage_item(self, report: CoverageReport, run_id: str) -> EvalItemRecord:
        codes: list[str] = []
        coverage: float | None = None
        if not report.base_sha:
            codes.append("E-H4_missing_metadata:base_sha")
        if not report.job_signature:
            codes.append("E-H4_missing_metadata:job_signature")

        if not codes:
            coverage = compute_diff_coverage(report.added_lines, report.covered_lines)
            if coverage is None:
                codes.append("E-H4_no_new_lines")
            elif coverage < DIFF_COVERAGE_MIN:
                codes.append(f"E-H4_diff_coverage_low:{coverage:.4f}")

        added_total = sum(len(lines) for lines in report.added_lines.values())
        if codes:
            status = "INCONCLUSIVE" if codes == ["E-H4_no_new_lines"] else "BLOCK"
        else:
            status = "PASS"
        return _item(
            run_id,
            "E-H4-diff-coverage",
            "hard",
            status,
            score=coverage,
            n=added_total,
            detail="; ".join(codes) or None,
        )

    @staticmethod
    def _pycg_item(benchmark: BenchmarkReport, run_id: str) -> EvalItemRecord:
        f1 = pycg_f1(benchmark.expected_edges, benchmark.predicted_edges)
        codes: list[str] = []
        if f1 is None:
            codes.append("E-W5_no_benchmark")
        elif f1 < PYCG_F1_MIN:
            codes.append(f"E-W5_f1_low:{f1:.4f}")
        return _item(
            run_id,
            "E-W5-pycg",
            "weighted",
            "INCONCLUSIVE" if codes else "PASS",
            score=f1,
            n=len(benchmark.expected_edges),
            detail="; ".join(codes) or None,
        )

    @staticmethod
    def _scorecard_item(report: ScorecardReport, run_id: str) -> EvalItemRecord:
        codes: list[str] = []
        if report.score < SCORECARD_MIN:
            codes.append(f"E-W6_score_low:{report.score:g}")
        return _item(
            run_id,
            "E-W6-scorecard",
            "weighted",
            "INCONCLUSIVE" if codes else "PASS",
            score=report.score,
            n=None,
            detail="; ".join(codes) or None,
        )


def _item(
    run_id: str,
    name: str,
    kind: str,
    status: str,
    *,
    score: float | None,
    n: int | None,
    detail: str | None,
) -> EvalItemRecord:
    return EvalItemRecord(
        item_id=f"{run_id}-{name}",
        run_id=run_id,
        name=name,
        kind=kind,
        score=score,
        n=n,
        ci_lower=None,
        ci_upper=None,
        weight=None,
        status=status,
        evidence_id=None,
        detail=detail,
    )
