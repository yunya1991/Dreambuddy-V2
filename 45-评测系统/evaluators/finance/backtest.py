# -*- coding: utf-8 -*-
"""
backtest.py — 金融回测统计内核（P2-4）
========================================
SPEC §5.1 F-H6/F-H7、D-04（DSR 主判、Sharpe 辅判）：

- PSR：Bailey & López de Prado (2012)，非年化 Sharpe、按每期收益计算
- DSR：PSR 的基准换成「N 次试验下的期望最大 Sharpe」SR0
  SR0 = σ_SR[(1-γ)Z⁻¹(1-1/N) + γZ⁻¹(1-1/(Ne))]，γ=Euler–Mascheroni
- PBO：CSCV（S=16，组合 C(16,8)=12870），选 IS 最优策略后看其 OOS 分位，λ≤0 记为过拟合
- N_trials 未登记 → F-H6 BLOCK；PBO>0.50 → BLOCK
- DSR≥0.95 且 OOS 交易≥100、walk-forward≥5 折，否则 F-H7 INCONCLUSIVE

说明：公式中的 Sharpe / skew / kurtosis 均为「每期」口径，kurtosis 用原始峰度（正态=3）。
"""

from __future__ import annotations

import itertools
from dataclasses import dataclass
from math import e, inf, sqrt
from statistics import NormalDist

from storage.repo import EvalItemRecord

EULER_GAMMA = 0.577_215_664_9
DSR_MIN = 0.95
PBO_MAX = 0.50
MIN_OOS_TRADES = 100
MIN_WF_FOLDS = 5
CSCV_BLOCKS = 16


class BacktestError(ValueError):
    """回测统计参数非法（样本不足/退化分布等）。"""


def probabilistic_sharpe_ratio(
    sharpe: float,
    n_observations: int,
    skew: float = 0.0,
    kurtosis: float = 3.0,
    benchmark_sr: float = 0.0,
) -> float:
    """PSR = Φ((SR-SR*)·√(n-1) / √(1-γ₃SR+((γ₄-1)/4)SR²))。"""
    if n_observations < 2:
        raise BacktestError(f"n_observations 必须 ≥ 2，收到 {n_observations}")
    variance = 1 - skew * sharpe + (kurtosis - 1) / 4 * sharpe**2
    if variance <= 0:
        raise BacktestError("PSR 方差项非正，skew/kurtosis 输入不合理")
    z = (sharpe - benchmark_sr) * sqrt(n_observations - 1) / sqrt(variance)
    return NormalDist().cdf(z)


def expected_max_sharpe(n_trials: int, sr_std: float = 1.0) -> float:
    """N 次独立试验的期望最大 Sharpe（Bailey 近似）。"""
    if n_trials < 1:
        raise BacktestError(f"n_trials 必须 ≥ 1，收到 {n_trials}")
    if sr_std <= 0:
        raise BacktestError(f"sr_std 必须 > 0，收到 {sr_std}")
    z_first = NormalDist().inv_cdf(1 - 1 / n_trials)
    z_last = NormalDist().inv_cdf(1 - 1 / (n_trials * e))
    return sr_std * ((1 - EULER_GAMMA) * z_first + EULER_GAMMA * z_last)


def deflated_sharpe_ratio(
    sharpe: float,
    n_observations: int,
    n_trials: int,
    skew: float = 0.0,
    kurtosis: float = 3.0,
    sr_std: float = 1.0,
) -> float:
    """DSR：以 SR0 为基准的 PSR；n_trials=1 时退化为 SR*=0。"""
    benchmark = 0.0 if n_trials <= 1 else expected_max_sharpe(n_trials, sr_std)
    return probabilistic_sharpe_ratio(
        sharpe, n_observations, skew=skew, kurtosis=kurtosis, benchmark_sr=benchmark
    )


def pbo_cscv(returns_by_strategy: list[list[float]], S: int = CSCV_BLOCKS) -> float:
    """CSCV 计算 PBO：IS 选优 → 看 OOS 分位，λ≤0 的比例即过拟合概率。"""
    if len(returns_by_strategy) < 2:
        raise BacktestError("PBO 至少需要 2 个策略")
    lengths = {len(series) for series in returns_by_strategy}
    if len(lengths) != 1:
        raise BacktestError("各策略样本长度必须一致")
    n_samples = lengths.pop()
    if S < 2 or S % 2 != 0:
        raise BacktestError(f"S 必须为 ≥2 的偶数，收到 {S}")
    if n_samples % S != 0 or n_samples // S < 1:
        raise BacktestError(f"样本数 {n_samples} 必须能被 S={S} 整除")

    block = n_samples // S
    blocks = [list(range(i * block, (i + 1) * block)) for i in range(S)]
    overfit = 0
    total = 0
    for is_blocks in itertools.combinations(range(S), S // 2):
        is_indices = [i for index in is_blocks for i in blocks[index]]
        oos_indices = [i for index in range(S) if index not in is_blocks for i in blocks[index]]
        is_scores = [_sharpe([series[i] for i in is_indices]) for series in returns_by_strategy]
        best = max(range(len(is_scores)), key=lambda idx: is_scores[idx])
        oos_scores = [_sharpe([series[i] for i in oos_indices]) for series in returns_by_strategy]
        rank = (
            sum(1 for score in oos_scores if score < oos_scores[best])
            + 0.5 * sum(1 for score in oos_scores if score == oos_scores[best])
        ) / len(oos_scores)
        if rank <= 0.5:
            overfit += 1
        total += 1
    return overfit / total


def _sharpe(values: list[float]) -> float:
    mean = sum(values) / len(values)
    if len(values) < 2:
        return 0.0
    variance = sum((value - mean) ** 2 for value in values) / (len(values) - 1)
    if variance <= 0:
        if mean > 0:
            return inf
        return -inf if mean < 0 else 0.0
    return mean / sqrt(variance)


@dataclass(frozen=True)
class BacktestStats:
    """一份回测统计摘要（报告证据字段子集）。"""

    sharpe: float
    n_observations: int
    n_trials: int
    oos_trades: int
    walk_forward_folds: int
    pbo: float
    skew: float = 0.0
    kurtosis: float = 3.0
    sr_std: float = 1.0


class BacktestStatisticsEvaluator:
    """F-H6 过拟合红线 + F-H7 统计显著性主判。"""

    def evaluate(self, stats: BacktestStats, run_id: str) -> list[EvalItemRecord]:
        overfit_codes = self._overfit_codes(stats)
        significance_codes = self._significance_codes(stats)
        return [
            self._item(run_id, "F-H6-overfit", overfit_codes, "BLOCK"),
            self._item(run_id, "F-H7-significance", significance_codes, "INCONCLUSIVE"),
        ]

    @staticmethod
    def _overfit_codes(stats: BacktestStats) -> list[str]:
        if stats.n_trials <= 0:
            return ["F-H6_n_trials_missing"]
        if stats.pbo > PBO_MAX:
            return [f"F-H6_pbo_exceeded:{stats.pbo:g}"]
        return []

    @staticmethod
    def _significance_codes(stats: BacktestStats) -> list[str]:
        codes: list[str] = []
        if stats.oos_trades < MIN_OOS_TRADES:
            codes.append(f"F-H7_oos_trades_low:{stats.oos_trades}")
        if stats.walk_forward_folds < MIN_WF_FOLDS:
            codes.append(f"F-H7_folds_low:{stats.walk_forward_folds}")
        dsr = deflated_sharpe_ratio(
            stats.sharpe,
            stats.n_observations,
            stats.n_trials,
            skew=stats.skew,
            kurtosis=stats.kurtosis,
            sr_std=stats.sr_std,
        )
        if dsr < DSR_MIN:
            codes.append(f"F-H7_dsr_below:{dsr:.4f}")
        return codes

    @staticmethod
    def _item(run_id: str, name: str, codes: list[str], failed_status: str) -> EvalItemRecord:
        return EvalItemRecord(
            item_id=f"{run_id}-{name}",
            run_id=run_id,
            name=name,
            kind="hard",
            score=None,
            n=None,
            ci_lower=None,
            ci_upper=None,
            weight=None,
            status=failed_status if codes else "PASS",
            evidence_id=None,
            detail="; ".join(codes) or None,
        )
