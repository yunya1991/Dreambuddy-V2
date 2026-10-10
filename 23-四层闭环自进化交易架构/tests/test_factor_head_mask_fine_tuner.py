"""RED 测试：FactorHeadMaskFineTuner — 矛盾Transformer factor_head_mask 微调。

SPEC §5.4: 用逆向推导的标注数据（哪个维度该赢）微调 factor_head_mask，
降低错误维度的 head 权重。
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "dreambuddy_evolution" / "engines"))
sys.path.insert(0, str(Path(__file__).parent.parent / "dreambuddy_evolution"))

from factor_head_mask_fine_tuner import FactorHeadMaskFineTuner


def test_downgrade_wrong_dimension_head_weight():
    """RED: 错误维度的 head 权重应降低。"""
    tuner = FactorHeadMaskFineTuner()
    current_mask = {"C1": 1.0, "C2": 1.0, "C3": 1.0}
    wrong_dims = ["C1"]

    adjusted = tuner.adjust(current_mask, wrong_dims)

    # C1 错误 → 降权
    assert adjusted["C1"] < current_mask["C1"]
    # C2/C3 正确 → 不变或微升
    assert adjusted["C2"] >= current_mask["C2"]
    assert adjusted["C3"] >= current_mask["C3"]


def test_correct_dimension_head_weight_not_downgraded():
    """RED: 正确维度的 head 权重不降权。"""
    tuner = FactorHeadMaskFineTuner()
    current_mask = {"C1": 0.8, "C2": 0.6}
    wrong_dims = ["C1"]

    adjusted = tuner.adjust(current_mask, wrong_dims)

    assert adjusted["C2"] == current_mask["C2"]


def test_mask_weight_clamped_to_bounds():
    """RED: 调整后权重不超出 [0.1, 1.0] 边界。"""
    tuner = FactorHeadMaskFineTuner()
    current_mask = {"C1": 0.15}  # 已经接近下界
    wrong_dims = ["C1"]

    adjusted = tuner.adjust(current_mask, wrong_dims)

    assert adjusted["C1"] >= 0.1
    assert adjusted["C1"] <= 1.0


def test_no_wrong_dimensions_means_no_change():
    """RED: 无错误维度时，mask 不变。"""
    tuner = FactorHeadMaskFineTuner()
    current_mask = {"C1": 0.8, "C2": 0.6}
    wrong_dims = []

    adjusted = tuner.adjust(current_mask, wrong_dims)

    assert adjusted == current_mask


def test_fail_open_on_invalid_mask():
    """RED: 无效 mask 时 FAIL-OPEN 返回原 mask。"""
    tuner = FactorHeadMaskFineTuner()
    adjusted = tuner.adjust(None, ["C1"])
    assert adjusted is None or adjusted == {}
