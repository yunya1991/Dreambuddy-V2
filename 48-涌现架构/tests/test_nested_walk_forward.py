"""P0-4 嵌套 walk-forward 反思选择 — SPEC §2.10 A2。"""

from __future__ import annotations

import pytest
from nested_walk_forward import (
    nested_walk_forward,
    walk_forward_blocks,
)

DATES = [f"2026-01-{d:02d}" for d in range(1, 31)]


def _score_fn(table):
    def _eval(cand, train, test):
        return sum(table[cand][d] for d in test) / len(test)

    return _eval


def _overfit_table():
    # A 在前期强、后期弱；B 全程平稳
    a = {d: (0.9 if i < 15 else 0.1) for i, d in enumerate(DATES)}
    b = dict.fromkeys(DATES, 0.6)
    return {"A": a, "B": b}


def test_split_has_no_overlap_and_respects_embargo():
    blocks = walk_forward_blocks(DATES, 4, embargo=3, min_train=10)
    assert len(blocks) == 4
    ds = sorted(DATES)
    for train, test in blocks:
        assert max(train) < min(test)
        gap = ds.index(test[0]) - ds.index(train[-1])
        assert gap >= 4  # embargo + 1


def test_selection_is_inner_only_and_fitness_is_outer():
    table = _overfit_table()
    res = nested_walk_forward(
        DATES, ["A", "B"], _score_fn(table), outer_folds=4, inner_folds=3, min_train=10
    )
    assert res.degraded is False
    assert res.leakage_free is True
    # 至少一个外层折在内层选中 A（前期高分），外层暴露其真实水平
    assert any(f.inner_best_index == 0 for f in res.folds)
    assert any(f.inner_best_index == 0 and f.outer_score < f.inner_score for f in res.folds)
    assert res.selection_gap > 0.1
    # 上报的适应度必须是外层均值，不是内层最优
    assert res.mean_outer_score == pytest.approx(
        sum(f.outer_score for f in res.folds) / len(res.folds), abs=1e-6
    )
    assert res.mean_outer_score < res.mean_inner_score


def test_stable_candidate_has_near_zero_gap():
    table = {c: dict.fromkeys(DATES, 0.6) for c in ("A", "B")}
    res = nested_walk_forward(
        DATES, ["A", "B"], _score_fn(table), outer_folds=4, inner_folds=3, min_train=10
    )
    assert res.degraded is False
    assert abs(res.selection_gap) < 1e-6
    assert res.mean_outer_score == pytest.approx(0.6)


def test_insufficient_dates_degrade_without_raise():
    res = nested_walk_forward(DATES[:5], ["A"], lambda c, tr, te: 1.0, outer_folds=4, min_train=20)
    assert res.degraded is True
    assert res.mean_outer_score is None
    assert res.reason == "insufficient_dates"


def test_eval_exception_degrades_without_raise():
    def boom(cand, train, test):
        raise RuntimeError("fit failed")

    res = nested_walk_forward(DATES, ["A"], boom, outer_folds=2, min_train=10)
    assert res.degraded is True
    assert res.reason.startswith("error:")


def test_no_candidates_degrades():
    res = nested_walk_forward(DATES, [], lambda c, tr, te: 0.0)
    assert res.degraded is True
    assert res.reason == "no_candidates"
