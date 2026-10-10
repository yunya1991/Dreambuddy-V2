"""RED 测试：apply_reward_with_derive — 精准因子奖惩。

基于 ReverseDeriver 的逆向推导结果，对错误维度因子降权、正确维度因子升权，
类比反向传播中的参数更新（SGD）。
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "dreambuddy_evolution"))
sys.path.insert(0, str(Path(__file__).parent.parent / "dreambuddy_evolution" / "engines"))

from dreambuddy_evolution.engines.reflection_engine import ReflectionEngine
from reverse_deriver import ReverseDeriver, ReverseDeriveResult


def _make_snapshot(dim_predictions=None, dim_factors=None):
    return {
        "symbol": "BTC-USDT-SWAP",
        "action": "long",
        "level0_dstar": "long",
        "ess_id": "e1",
        "ess_dir": "long",
        "cbr_sim": 0.8,
        "cbr_top1_outcome": "TP",
        "cluster_id": "C001",
        "dimension_predictions": dim_predictions or {"C1": "long", "C2": "short"},
        "dimension_factors": dim_factors or {
            "C1": {"资金流入": 0.5, "主力净买": 0.3},
            "C2": {"多空比": 0.4, "恐慌贪婪": 0.2},
        },
    }


def test_apply_reward_with_derive_returns_factor_adjustments():
    """RED: apply_reward_with_derive 应返回 factor_adjustments 字段。"""
    engine = ReflectionEngine()
    deriver = ReverseDeriver()
    snapshot = _make_snapshot()
    outcome = {"real_direction": "short", "real_outcome": "SL"}

    derive_result = deriver.derive(snapshot, outcome)
    reward = engine.apply_reward_with_derive(
        cs=-0.5, outcome="SL", cluster_id="C001", ess_id="e1",
        gmax=0.3, snapshot=snapshot, derive_result=derive_result,
    )

    assert "factor_adjustments" in reward
    # base_reward 字段仍存在
    assert "ess_delta" in reward
    assert "gmax_mult" in reward


def test_wrong_dimension_factors_are_downgraded():
    """RED: 错误维度的因子应降权 ×0.9。"""
    engine = ReflectionEngine()
    deriver = ReverseDeriver()
    # C1预测long，实际short → C1错
    snapshot = _make_snapshot(
        dim_predictions={"C1": "long", "C2": "short"},
        dim_factors={
            "C1": {"资金流入": 0.5},
            "C2": {"多空比": 0.4},
        },
    )
    outcome = {"real_direction": "short", "real_outcome": "SL"}

    derive_result = deriver.derive(snapshot, outcome)
    reward = engine.apply_reward_with_derive(
        cs=-0.5, outcome="SL", cluster_id="C001", ess_id="e1",
        gmax=0.3, snapshot=snapshot, derive_result=derive_result,
    )

    # C1 错 → 资金流入降权 ×0.9 = 0.45
    assert reward["factor_adjustments"]["资金流入"] == pytest.approx(0.5 * 0.9)


def test_correct_dimension_factors_are_upgraded():
    """RED: 正确维度的因子应升权 ×1.05。"""
    engine = ReflectionEngine()
    deriver = ReverseDeriver()
    # C2预测short，实际short → C2对
    snapshot = _make_snapshot(
        dim_predictions={"C1": "long", "C2": "short"},
        dim_factors={
            "C1": {"资金流入": 0.5},
            "C2": {"多空比": 0.4},
        },
    )
    outcome = {"real_direction": "short", "real_outcome": "SL"}

    derive_result = deriver.derive(snapshot, outcome)
    reward = engine.apply_reward_with_derive(
        cs=-0.5, outcome="SL", cluster_id="C001", ess_id="e1",
        gmax=0.3, snapshot=snapshot, derive_result=derive_result,
    )

    # C2 对 → 多空比升权 ×1.05 = 0.42
    assert reward["factor_adjustments"]["多空比"] == pytest.approx(0.4 * 1.05)


def test_no_wrong_dimensions_means_no_downgrade():
    """RED: 所有维度正确时，不降权只升权。"""
    engine = ReflectionEngine()
    deriver = ReverseDeriver()
    snapshot = _make_snapshot(
        dim_predictions={"C1": "short", "C2": "short"},
        dim_factors={
            "C1": {"资金流入": 0.5},
            "C2": {"多空比": 0.4},
        },
    )
    outcome = {"real_direction": "short", "real_outcome": "TP"}

    derive_result = deriver.derive(snapshot, outcome)
    reward = engine.apply_reward_with_derive(
        cs=0.9, outcome="TP", cluster_id="C001", ess_id="e1",
        gmax=0.3, snapshot=snapshot, derive_result=derive_result,
    )

    # 全部升权
    assert reward["factor_adjustments"]["资金流入"] == pytest.approx(0.5 * 1.05)
    assert reward["factor_adjustments"]["多空比"] == pytest.approx(0.4 * 1.05)


def test_fail_open_neutral_result_skips_factor_adjustment():
    """RED: derive_result 为 neutral（confidence=0）时，不做因子调整。"""
    engine = ReflectionEngine()
    snapshot = _make_snapshot()
    # neutral result（FAIL-OPEN）
    derive_result = ReverseDeriveResult(
        per_dimension_correctness={},
        per_dimension_cs={},
        wrong_dimensions=[],
        root_cause="reverse_derive_failed",
        root_cause_type="unknown",
        confidence=0.0,
        known_gaps=["缺少数据"],
        optimization_action="no_adjustment",
    )
    reward = engine.apply_reward_with_derive(
        cs=0.0, outcome="SL", cluster_id="C001", ess_id="e1",
        gmax=0.3, snapshot=snapshot, derive_result=derive_result,
    )

    # 空调整：不修改任何因子权重
    assert reward["factor_adjustments"] == {}
