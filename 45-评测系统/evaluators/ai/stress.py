# -*- coding: utf-8 -*-
"""
stress.py — AI 性能压测达标率（P2-6，SPEC A-W2 / thresholds A-W2）
====================================================================
判定口径：固定并发下每个样本需同时满足 p95 延迟 / 吞吐 / 错误率三项阈值；
达标率 ≥0.80 且样本数 ≥30 才 PASS，否则 INCONCLUSIVE（加权项不拦截）。
"""

from __future__ import annotations

from dataclasses import dataclass

from storage.repo import EvalItemRecord

A_W2_DEFAULT_TARGET = 0.80
A_W2_DEFAULT_MIN_N = 30


class StressError(ValueError):
    """压测样本或阈值配置非法。"""


@dataclass(frozen=True)
class StressPlan:
    """压测阈值（来自 thresholds.yaml A-W2 及其环境参数）。"""

    p95_max_ms: float
    throughput_min_rps: float
    max_error_rate: float
    target: float = A_W2_DEFAULT_TARGET
    min_n: int = A_W2_DEFAULT_MIN_N


@dataclass(frozen=True)
class StressSample:
    """单次压测样本（固定并发）。"""

    concurrency: int
    p95_latency_ms: float
    throughput_rps: float
    error_rate: float

    def __post_init__(self) -> None:
        if self.concurrency < 1:
            raise StressError(f"concurrency 必须 ≥ 1，收到 {self.concurrency}")
        if self.p95_latency_ms < 0 or self.throughput_rps < 0:
            raise StressError("压测指标不能为负")
        if not 0.0 <= self.error_rate <= 1.0:
            raise StressError(f"error_rate 必须落在 [0,1]，收到 {self.error_rate}")

    def meets(self, plan: StressPlan) -> bool:
        return (
            self.p95_latency_ms <= plan.p95_max_ms
            and self.throughput_rps >= plan.throughput_min_rps
            and self.error_rate <= plan.max_error_rate
        )


class StressEvaluator:
    """A-W2：达标率 = 同时满足三条阈值的样本占比。"""

    def evaluate(
        self, samples: list[StressSample], plan: StressPlan, run_id: str
    ) -> list[EvalItemRecord]:
        total = len(samples)
        pass_rate = sum(1 for item in samples if item.meets(plan)) / total if total else 0.0
        codes: list[str] = []
        if total < plan.min_n:
            codes.append(f"A-W2_samples_low:{total}")
        if pass_rate < plan.target:
            codes.append(f"A-W2_pass_rate_low:{pass_rate:.4f}")

        return [
            EvalItemRecord(
                item_id=f"{run_id}-A-W2",
                run_id=run_id,
                name="A-W2-stress",
                kind="weighted",
                score=pass_rate,
                n=total,
                ci_lower=None,
                ci_upper=None,
                weight=None,
                status="INCONCLUSIVE" if codes else "PASS",
                evidence_id=None,
                detail="; ".join(codes) or None,
            )
        ]
