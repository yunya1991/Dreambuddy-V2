"""N-P1a 权重学习测试（RED 阶段）。

文档要求：权重由数据驱动（Bradley-Terry），不能手工设定。
验收标准：
- Bradley-Terry 冷启动：从合成偏好数据初始化权重
- 在线迭代：verify 结果持续更新各验证器准确率
- 同源降权：高度相关的验证器自动降权
- 权重版本记录：每次权重变更有版本号
"""
import pytest


def test_module_importable():
    from weight_learner import (
        BradleyTerryLearner, WeightVersion,
    )


# ---------------------------------------------------------------------------
# Bradley-Terry 冷启动
# ---------------------------------------------------------------------------

def test_bt_cold_start_equal_weights():
    """无数据时冷启动为等权。"""
    from weight_learner import BradleyTerryLearner
    stages = ["cycle_consistency", "factuality", "applicability"]
    bt = BradleyTerryLearner(stages=stages)
    weights = bt.get_weights()
    for s in stages:
        assert abs(weights[s] - 1.0) < 1e-9  # 等权


def test_bt_update_increases_winner_weight():
    """验证通过（pass）的验证器权重应上升。"""
    from weight_learner import BradleyTerryLearner
    stages = ["cycle_consistency", "factuality"]
    bt = BradleyTerryLearner(stages=stages)
    w_before = bt.get_weights()
    # cycle_consistency pass, factuality fail
    bt.update({"cycle_consistency": "pass", "factuality": "fail"})
    w_after = bt.get_weights()
    assert w_after["cycle_consistency"] > w_before["cycle_consistency"]
    assert w_after["factuality"] < w_before["factuality"]


def test_bt_update_abstain_no_penalty():
    """abstain 不直接惩罚（强度不变，但归一化可能偏移）。"""
    from weight_learner import BradleyTerryLearner
    stages = ["a", "b"]
    bt = BradleyTerryLearner(stages=stages)
    s_before = bt._strength["a"]
    bt.update({"a": "abstain", "b": "pass"})
    s_after = bt._strength["a"]
    assert abs(s_after - s_before) < 1e-9  # 强度不变（不被惩罚）


def test_bt_weights_nonnegative():
    """权重不能为负。"""
    from weight_learner import BradleyTerryLearner
    stages = ["a", "b"]
    bt = BradleyTerryLearner(stages=stages)
    for _ in range(100):
        bt.update({"a": "fail", "b": "pass"})
    w = bt.get_weights()
    for v in w.values():
        assert v >= 0.0


# ---------------------------------------------------------------------------
# 权重版本
# ---------------------------------------------------------------------------

def test_weight_version_increments():
    from weight_learner import BradleyTerryLearner, WeightVersion
    stages = ["a", "b"]
    bt = BradleyTerryLearner(stages=stages)
    v0 = bt.version
    bt.update({"a": "pass", "b": "fail"})
    v1 = bt.version
    assert v1.version_id > v0.version_id
    assert v1.weights != v0.weights


def test_weight_version_records_history():
    from weight_learner import BradleyTerryLearner
    stages = ["a", "b"]
    bt = BradleyTerryLearner(stages=stages)
    bt.update({"a": "pass", "b": "fail"})
    bt.update({"a": "fail", "b": "pass"})
    history = bt.version_history()
    assert len(history) >= 3  # 初始 + 2次更新


# ---------------------------------------------------------------------------
# 同源降权
# ---------------------------------------------------------------------------

def test_correlation_downweighting():
    """高度相关的验证器应被降权。"""
    from weight_learner import BradleyTerryLearner
    stages = ["a", "b", "c"]
    bt = BradleyTerryLearner(stages=stages)
    # a 和 b 高度相关（总是相同 verdict），c 独立
    for _ in range(50):
        bt.update({"a": "pass", "b": "pass", "c": "pass"})
        bt.update({"a": "fail", "b": "fail", "c": "pass"})
    bt.apply_correlation_downweighting()
    w = bt.get_weights()
    # a 和 b 高度相关，总权重应低于独立的 c
    assert w["a"] + w["b"] < 2 * w["c"]  # 相关对被降权


def test_no_correlation_no_downweight():
    """不相关的验证器不应被降权。"""
    from weight_learner import BradleyTerryLearner
    stages = ["a", "b"]
    bt = BradleyTerryLearner(stages=stages)
    for _ in range(20):
        bt.update({"a": "pass", "b": "fail"})
        bt.update({"a": "fail", "b": "pass"})
    w_before = bt.get_weights()
    bt.apply_correlation_downweighting()
    w_after = bt.get_weights()
    # 完全负相关，不应触发降权（降权针对正相关）
    assert w_after["a"] >= w_before["a"] * 0.9


# ---------------------------------------------------------------------------
# 导出/导入
# ---------------------------------------------------------------------------

def test_export_import_weights():
    from weight_learner import BradleyTerryLearner
    stages = ["a", "b"]
    bt = BradleyTerryLearner(stages=stages)
    bt.update({"a": "pass", "b": "fail"})
    params = bt.export_params()
    w1 = bt.get_weights()

    bt2 = BradleyTerryLearner(stages=stages)
    bt2.import_params(params)
    w2 = bt2.get_weights()
    for s in stages:
        assert abs(w1[s] - w2[s]) < 1e-9
