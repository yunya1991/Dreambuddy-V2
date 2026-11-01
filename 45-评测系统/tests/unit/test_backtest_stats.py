# -*- coding: utf-8 -*-
"""test_backtest_stats.py — P2-4 金融回测内核：PSR / DSR / PBO / N_trials。"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from evaluators.finance.backtest import (  # noqa: E402
    BacktestError,
    BacktestStatisticsEvaluator,
    BacktestStats,
    deflated_sharpe_ratio,
    expected_max_sharpe,
    pbo_cscv,
    probabilistic_sharpe_ratio,
)

# ---------- PSR（对照论文公式手算） ----------


def test_psr_normal_reference():
    # SR=0.2, n=100, 正态（skew=0, kurt=3）→ 0.975602
    assert probabilistic_sharpe_ratio(0.2, 100) == pytest.approx(0.975602, abs=1e-6)


def test_psr_benchmark_equal_returns_half():
    assert probabilistic_sharpe_ratio(0.2, 100, benchmark_sr=0.2) == pytest.approx(0.5, abs=1e-9)


def test_psr_negative_skew_and_fat_tail_lower_it():
    assert probabilistic_sharpe_ratio(0.2, 100, skew=-1.0) == pytest.approx(0.964199, abs=1e-6)
    assert probabilistic_sharpe_ratio(0.2, 100, kurtosis=6.0) == pytest.approx(0.973932, abs=1e-6)


def test_psr_more_samples_raise_confidence():
    assert probabilistic_sharpe_ratio(0.2, 200) > probabilistic_sharpe_ratio(0.2, 100)


@pytest.mark.parametrize("n", [1, 0, -3])
def test_psr_requires_enough_samples(n):
    with pytest.raises(BacktestError):
        probabilistic_sharpe_ratio(0.2, n)


# ---------- 期望最大 Sharpe / DSR ----------


def test_expected_max_sharpe_reference():
    assert expected_max_sharpe(2) == pytest.approx(0.519755, abs=1e-6)
    assert expected_max_sharpe(100) == pytest.approx(2.530603, abs=1e-5)


def test_expected_max_sharpe_invalid():
    with pytest.raises(BacktestError):
        expected_max_sharpe(0)
    with pytest.raises(BacktestError):
        expected_max_sharpe(10, sr_std=0)


def test_dsr_single_trial_equals_psr():
    assert deflated_sharpe_ratio(0.2, 250, n_trials=1) == pytest.approx(
        probabilistic_sharpe_ratio(0.2, 250), abs=1e-9
    )


def test_dsr_decreases_with_more_trials():
    single = deflated_sharpe_ratio(0.2, 250, n_trials=1)
    many = deflated_sharpe_ratio(0.2, 250, n_trials=10)
    assert many < single
    assert many < 0.5  # 多重检验把 0.2 的 Sharpe 判为不显著


def test_dsr_reference_value():
    assert deflated_sharpe_ratio(0.2, 250, n_trials=10) == pytest.approx(0.0, abs=1e-6)


# ---------- PBO（CSCV） ----------


def test_pbo_dominant_strategy_is_zero():
    winner = [0.02 + i * 0.001 for i in range(8)]
    loser = [-0.01] * 8
    assert pbo_cscv([winner, loser], S=4) == 0.0


def test_pbo_perfect_overfit_approaches_one():
    first_half = [0.02] * 4 + [-0.01] * 4
    second_half = [-0.01] * 4 + [0.02] * 4
    assert pbo_cscv([first_half, second_half], S=4) == pytest.approx(1.0)


@pytest.mark.parametrize(
    "returns,kwargs",
    [
        ([[0.1, 0.2, 0.3], [0.1, 0.2, 0.3]], {"S": 2}),  # T=3 不能被 S 整除
        ([[0.1] * 8, [0.1] * 8], {"S": 3}),  # S 必须为偶数
        ([[0.1] * 8], {"S": 4}),  # 至少 2 个策略
        ([[0.1] * 8, [0.2] * 5], {"S": 4}),  # 策略样本长度不一致
    ],
)
def test_pbo_invalid_inputs(returns, kwargs):
    with pytest.raises(BacktestError):
        pbo_cscv(returns, **kwargs)


# ---------- F-H6 / F-H7 判定 ----------


def stats(**overrides) -> BacktestStats:
    base = {
        "sharpe": 0.5,
        "n_observations": 1000,
        "n_trials": 1,
        "oos_trades": 150,
        "walk_forward_folds": 5,
        "pbo": 0.2,
    }
    base.update(overrides)
    return BacktestStats(**base)


def test_overfit_and_significance_pass():
    items = BacktestStatisticsEvaluator().evaluate(stats(), run_id="RUN-1")
    assert [i.name for i in items] == ["F-H6-overfit", "F-H7-significance"]
    assert [i.status for i in items] == ["PASS", "PASS"]


def test_unregistered_trials_block():
    items = BacktestStatisticsEvaluator().evaluate(stats(n_trials=0), run_id="RUN-1")
    assert items[0].status == "BLOCK"
    assert items[0].detail == "F-H6_n_trials_missing"


def test_pbo_over_50_percent_block():
    items = BacktestStatisticsEvaluator().evaluate(stats(pbo=0.51), run_id="RUN-1")
    assert items[0].status == "BLOCK"
    assert items[0].detail == "F-H6_pbo_exceeded:0.51"


def test_pbo_boundary_50_percent_passes():
    items = BacktestStatisticsEvaluator().evaluate(stats(pbo=0.50), run_id="RUN-1")
    assert items[0].status == "PASS"


@pytest.mark.parametrize(
    "overrides,code",
    [
        ({"oos_trades": 99}, "F-H7_oos_trades_low:99"),
        ({"walk_forward_folds": 4}, "F-H7_folds_low:4"),
        (
            {"sharpe": 0.2, "n_trials": 10},
            None,
        ),  # DSR < 0.95 → INCONCLUSIVE，detail 含 F-H7_dsr_below
    ],
)
def test_insufficient_significance_is_inconclusive(overrides, code):
    items = BacktestStatisticsEvaluator().evaluate(stats(**overrides), run_id="RUN-1")
    assert items[1].status == "INCONCLUSIVE"
    if code:
        assert items[1].detail == code
    else:
        assert "F-H7_dsr_below" in (items[1].detail or "")
