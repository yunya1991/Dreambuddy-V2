"""RED 测试：ReverseDeriver — 金融逆向推导。

从交易结果反推哪个矛盾维度判断错，类比反向传播。
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "dreambuddy_evolution" / "engines"))
sys.path.insert(0, str(Path(__file__).parent.parent / "dreambuddy_evolution"))

from reverse_deriver import ReverseDeriver


def _make_snapshot(dim_predictions=None):
    return {
        "symbol": "BTC-USDT-SWAP",
        "action": "long",
        "level0_dstar": "long",
        "ess_dir": "long",
        "cbr_top1_outcome": "TP",
        "cluster_id": "C001",
        "dimension_predictions": dim_predictions or {"C1": "long", "C2": "short", "C3": "long"},
    }


def test_derive_returns_per_dimension_correctness():
    """RED: 应返回每个维度的判断正确性。"""
    deriver = ReverseDeriver()
    snapshot = _make_snapshot({"C1": "long", "C2": "short", "C3": "long"})
    outcome = {"real_direction": "short", "real_outcome": "SL"}

    result = deriver.derive(snapshot, outcome)

    assert result.per_dimension_correctness == {"C1": False, "C2": True, "C3": False}
    assert "C1" in result.wrong_dimensions
    assert "C3" in result.wrong_dimensions


def test_derive_fail_open_when_missing_dimension_predictions():
    """RED: snapshot 缺 dimension_predictions 时 FAIL-OPEN 返回 neutral。"""
    deriver = ReverseDeriver()
    snapshot = {"symbol": "BTC", "action": "long"}  # 无 dimension_predictions
    outcome = {"real_direction": "short"}

    result = deriver.derive(snapshot, outcome)

    assert result.root_cause_type == "unknown"
    assert result.optimization_action == "no_adjustment"
    assert result.per_dimension_correctness == {}


def test_derive_returns_root_cause_and_optimization_action():
    """RED: 应返回根因类型和建议优化动作。"""
    deriver = ReverseDeriver()
    snapshot = _make_snapshot({"C1": "long", "C2": "short"})
    outcome = {"real_direction": "short", "real_outcome": "SL"}

    result = deriver.derive(snapshot, outcome)

    assert result.root_cause_type in ("factor_error", "weight_error", "data_error", "unknown")
    assert result.optimization_action != ""
    assert 0.0 <= result.confidence <= 1.0


def test_derive_all_correct_no_wrong_dimensions():
    """RED: 所有维度判断正确时 wrong_dimensions 为空。"""
    deriver = ReverseDeriver()
    snapshot = _make_snapshot({"C1": "short", "C2": "short"})
    outcome = {"real_direction": "short", "real_outcome": "TP"}

    result = deriver.derive(snapshot, outcome)

    assert result.wrong_dimensions == []
    assert all(v is True for v in result.per_dimension_correctness.values())


def test_derive_all_wrong_dimensions():
    """RED: 所有维度判断错误时，全部进入 wrong_dimensions。"""
    deriver = ReverseDeriver()
    snapshot = _make_snapshot({"C1": "long", "C2": "long", "C3": "long"})
    outcome = {"real_direction": "short", "real_outcome": "SL"}

    result = deriver.derive(snapshot, outcome)

    assert set(result.wrong_dimensions) == {"C1", "C2", "C3"}
    assert all(v is False for v in result.per_dimension_correctness.values())
    # 多数维度错 → weight_error
    assert result.root_cause_type == "weight_error"
    assert result.confidence == 0.0


def test_derive_false_failure_correct_dimensions_but_sl():
    """RED: 假失败 — 维度判断全对但被扫损(SL)。

    方向对却被扫损，不应归因为维度错误，optimization_action 应偏向参数/止损调整。
    """
    deriver = ReverseDeriver()
    snapshot = _make_snapshot({"C1": "long", "C2": "long"})
    outcome = {"real_direction": "long", "real_outcome": "SL"}  # 方向对但SL=假失败

    result = deriver.derive(snapshot, outcome)

    assert result.wrong_dimensions == []
    assert all(v is True for v in result.per_dimension_correctness.values())
    # 全对 → root_cause_type 为 unknown，不做因子调整
    assert result.root_cause_type == "unknown"
    assert result.optimization_action == "no_adjustment"


def test_derive_true_failure_wrong_dimensions_and_sl():
    """RED: 真失败 — 维度判断错且亏损(SL)。

    应定位错误维度并给出降权/审计因子的优化动作。
    """
    deriver = ReverseDeriver()
    snapshot = _make_snapshot({"C1": "short", "C2": "short", "C3": "long"})
    outcome = {"real_direction": "long", "real_outcome": "SL"}  # 真实long，C1/C2错

    result = deriver.derive(snapshot, outcome)

    assert set(result.wrong_dimensions) == {"C1", "C2"}
    assert result.per_dimension_correctness["C3"] is True
    # 2/3 错 → wrong_ratio >= 0.5 → weight_error
    assert result.root_cause_type == "weight_error"
    assert "降低" in result.optimization_action or "检查" in result.optimization_action
