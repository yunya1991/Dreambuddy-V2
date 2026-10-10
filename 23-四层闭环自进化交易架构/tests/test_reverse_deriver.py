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
