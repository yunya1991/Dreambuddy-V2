# -*- coding: utf-8 -*-
"""
test_split.py — P2-2 防泄漏切分组件测试
========================================
验收（PLAN P2-2）：
- purged：训练样本标签窗口与测试窗重叠即剔除（label_horizon）
- embargo：测试窗之后一段训练样本禁运剔除
- walk-forward：扩展窗口，训练只在测试之前（含 purge 尾部）
- 给定样例可验证无泄漏：verify_no_leakage 对生成切分返回空，对人工泄漏样例返回违规
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from evaluators.common.split import (  # noqa: E402
    SplitError,
    TimeSplit,
    embargo_length,
    purged_kfold,
    verify_no_leakage,
    walk_forward,
)

# ---------- 块切分与 purged k-fold ----------


def test_purged_kfold_blocks_cover_all_samples():
    splits = purged_kfold(10, n_splits=5)
    assert len(splits) == 5
    assert [s.fold for s in splits] == [0, 1, 2, 3, 4]
    covered = [i for split in splits for i in split.test]
    assert covered == list(range(10))
    # 每折训练集不含测试索引
    for split in splits:
        assert set(split.train).isdisjoint(split.test)


def test_purge_removes_train_labels_overlapping_test_window():
    splits = purged_kfold(10, n_splits=5, label_horizon=2)
    fold1 = splits[1]  # 测试 [2, 4)
    assert fold1.test == (2, 3)
    # i < s - horizon = 0 无；i >= e = 4 → 4..9；0/1 因标签窗口覆盖测试被 purge
    assert fold1.train == (4, 5, 6, 7, 8, 9)


def test_purge_without_horizon_keeps_past_train():
    fold1 = purged_kfold(10, n_splits=5)[1]
    assert fold1.train == (0, 1, 4, 5, 6, 7, 8, 9)


def test_embargo_removes_train_right_after_test():
    splits = purged_kfold(20, n_splits=5, embargo_pct=0.1)
    fold1 = splits[1]  # 测试 [4, 8)，embargo_len = 2
    assert fold1.test == (4, 5, 6, 7)
    assert fold1.train == (0, 1, 2, 3, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19)


def test_purge_and_embargo_combined():
    split = purged_kfold(20, n_splits=5, label_horizon=2, embargo_pct=0.1)[1]
    assert split.train == (0, 1, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19)


def test_embargo_length_rules():
    assert embargo_length(100, 0.0) == 0
    assert embargo_length(100, 0.005) == 1  # 至少 1 条
    assert embargo_length(100, 0.1) == 10
    assert embargo_length(20, 0.1) == 2


# ---------- walk-forward ----------


def test_walk_forward_train_only_before_test():
    splits = walk_forward(8, n_splits=3)
    assert [s.test for s in splits] == [(2, 3), (4, 5), (6, 7)]
    assert splits[0].train == (0, 1)
    assert splits[1].train == (0, 1, 2, 3)
    assert splits[2].train == (0, 1, 2, 3, 4, 5)
    for split in splits:
        assert max(split.train) < min(split.test)


def test_walk_forward_purges_label_horizon_tail():
    splits = walk_forward(8, n_splits=3, label_horizon=1)
    assert [s.train for s in splits] == [(0,), (0, 1, 2), (0, 1, 2, 3, 4)]
    assert [s.test for s in splits] == [(2, 3), (4, 5), (6, 7)]


# ---------- 无泄漏验证 ----------


def test_verify_no_leakage_passes_for_generated_purged_kfold():
    splits = purged_kfold(40, n_splits=4, label_horizon=3, embargo_pct=0.05)
    assert verify_no_leakage(splits, label_horizon=3, embargo_len=2) == []


def test_verify_no_leakage_passes_for_walk_forward():
    splits = walk_forward(40, n_splits=4, label_horizon=2)
    assert verify_no_leakage(splits, label_horizon=2) == []


def test_verify_no_leakage_detects_label_overlap():
    leaky = TimeSplit(fold=0, train=(0, 1, 2), test=(2, 3, 4))
    violations = verify_no_leakage([leaky], label_horizon=0)
    assert violations == ["fold0: train 2 标签窗口与测试 [2,5) 重叠"]


def test_verify_no_leakage_detects_embargo_zone():
    leaky = TimeSplit(fold=0, train=(2, 3), test=(0, 1))
    violations = verify_no_leakage([leaky], embargo_len=2)
    assert len(violations) == 2
    assert all("禁运期" in item for item in violations)


# ---------- 参数校验 ----------


@pytest.mark.parametrize(
    "kwargs",
    [
        {"n_samples": 0},
        {"n_samples": 10, "n_splits": 1},
        {"n_samples": 3, "n_splits": 5},
        {"n_samples": 10, "label_horizon": -1},
        {"n_samples": 10, "embargo_pct": -0.01},
        {"n_samples": 10, "embargo_pct": 1.0},
    ],
)
def test_purged_kfold_invalid_params(kwargs):
    with pytest.raises(SplitError):
        purged_kfold(**kwargs)


@pytest.mark.parametrize(
    "kwargs",
    [
        {"n_samples": 3, "n_splits": 3},  # 4 个块中测试块为空
        {"n_samples": 2, "n_splits": 2},
        {"n_samples": 0},
        {"n_samples": 10, "n_splits": 1},
    ],
)
def test_walk_forward_invalid_params(kwargs):
    with pytest.raises(SplitError):
        walk_forward(**kwargs)
