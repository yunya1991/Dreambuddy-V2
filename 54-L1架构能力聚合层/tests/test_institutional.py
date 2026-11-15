# -*- coding: utf-8 -*-
"""G 组机构方法能力出口测试（D-G01…D-G24）。

覆盖：横截面（X 组）、序列算子（O 组）、组合风险（P 组）、Fama-MacBeth（Q05）。
断言口径：信封契约（ok/capability/intent）+ `data.capabilities.<ID>.methods`
必须 ⊆ manifest 声明；非 good 时 answer 必须披露样本；输出可 JSON 序列化且确定性。
"""

import json
import os
import random
import sys

import pytest

_MODULE_ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
if _MODULE_ROOT not in sys.path:
    sys.path.insert(0, _MODULE_ROOT)

from l1agg.capabilities import manifest, run_capability  # noqa: E402
from l1agg.capabilities.institutional import (  # noqa: E402
    INTENT_ATTRIBUTION,
    INTENT_CROSS_SECTION,
    INTENT_CROWDING,
    INTENT_FACTOR,
    INTENT_REGRESSION,
    INTENT_RISK,
    INTENT_SEQUENCE,
)

# ---------------- 测试数据 ----------------


def _panel(n_symbols=32, n=90, seed=11):
    """横截面面板：{symbol: 取值序列}（X 组只取最近一期）。"""
    rng = random.Random(seed)
    return {f"S{i:02d}": [rng.gauss(0.0003, 0.02) for _ in range(n)] for i in range(n_symbols)}


def _returns(n_symbols=8, n=90, seed=23):
    """P 组面板：{symbol: 日收益序列}（等长对齐）。"""
    rng = random.Random(seed)
    return {f"A{i:02d}": [rng.gauss(0.0002, 0.015) for _ in range(n)] for i in range(n_symbols)}


def _price_series(n=120, seed=31):
    rng = random.Random(seed)
    out, level = [], 100.0
    for _ in range(n):
        level *= 1.0 + rng.gauss(0.0004, 0.01)
        out.append(level)
    return out


def _weight_map(names):
    return {nm: float(i + 1) for i, nm in enumerate(names)}


def _sector_map(names):
    return {nm: ("tech" if i % 2 == 0 else "fin") for i, nm in enumerate(names)}


def _assert_contract(out, capability_id, intent):
    assert out["ok"] is True, (capability_id, out["answer"])
    assert out["capability"] == capability_id
    assert out["intent"] == intent
    block = out["data"]["capabilities"][capability_id]
    declared = set(manifest().get(capability_id).methods)
    used = set(block["methods"])
    assert used, capability_id
    assert used <= declared, (capability_id, used, declared)
    if out["quality"]["status"] != "good":
        assert "样本" in out["answer"], (capability_id, out["answer"])
    return block


# ---------------- 横截面族 D-G01…D-G06 ----------------


def test_cross_section_profile_returns_z_and_percentile():
    out = run_capability("D-G01", panel=_panel())
    block = _assert_contract(out, "D-G01", INTENT_CROSS_SECTION)
    assert set(block["z"]) == set(block["pct"])
    assert block["n"] == 32
    assert "不代表未来" in out["answer"]


def test_group_neutralize_removes_group_mean():
    panel = _panel(n_symbols=32)
    groups = _sector_map(sorted(panel))
    out = run_capability("D-G02", panel=panel, groups=groups)
    block = _assert_contract(out, "D-G02", INTENT_CROSS_SECTION)
    resid = block["resid"]
    assert set(resid) == set(panel)
    for label in set(groups.values()):
        members = [resid[sym] for sym in resid if groups[sym] == label]
        assert abs(sum(members) / len(members)) < 1e-6


def test_quantile_portfolio_returns_buckets_and_spread():
    out = run_capability("D-G03", panel=_panel(), k=5)
    block = _assert_contract(out, "D-G03", INTENT_CROSS_SECTION)
    assert len(block["counts"]) == 5
    assert sum(block["counts"].values()) == 32
    assert isinstance(block["spread"], float)
    assert "不构成多空建议" in out["answer"]


def test_dispersion_breadth_matches_cross_section_counts():
    out = run_capability("D-G04", panel=_panel())
    block = _assert_contract(out, "D-G04", INTENT_CROSS_SECTION)
    assert block["advance"] + block["decline"] <= 32
    assert 0.0 <= block["breadth"] <= 1.0


def test_co_movement_returns_ratio_over_pairs():
    out = run_capability("D-G05", panel=_panel())
    block = _assert_contract(out, "D-G05", INTENT_CROSS_SECTION)
    assert block["pairs"] == 32 * 31 // 2
    assert 0.0 <= block["ratio"] <= 1.0


def test_factor_exposure_uses_declared_factor_matrix():
    panel = _panel(n_symbols=32)
    names = sorted(panel)
    factor = {"beta": {nm: float(i % 5) for i, nm in enumerate(names)}}
    out = run_capability("D-G06", panel=panel, factor=factor)
    block = _assert_contract(out, "D-G06", INTENT_FACTOR)
    assert "beta" in block["betas"]
    assert set(block["specific"]) == set(panel)


def test_factor_exposure_defaults_to_equal_weight_proxy():
    out = run_capability("D-G06", panel=_panel(n_symbols=32))
    block = _assert_contract(out, "D-G06", INTENT_FACTOR)
    assert set(block["betas"]) == {"market"}
    assert block["alpha"] == 0.0


def test_cross_section_insufficient_symbols_fails_open():
    out = run_capability("D-G01", panel={"A": [1.0, 2.0], "B": [2.0, 3.0]})
    assert out["ok"] is False
    assert out["quality"]["status"] == "empty"


# ---------------- 序列算子族 D-G07 ----------------


def test_sequence_operators_covers_declared_ops():
    out = run_capability("D-G07", series=_price_series(120), d=20)
    block = _assert_contract(out, "D-G07", INTENT_SEQUENCE)
    declared = set(manifest().get("D-G07").methods)
    assert set(block["ops"]) == declared - {"O09", "O10"}
    assert block["n"] == 120


def test_sequence_operators_appends_pair_ops_when_other_given():
    out = run_capability(
        "D-G07", series=_price_series(120), other=_price_series(120, seed=32), d=20
    )
    block = _assert_contract(out, "D-G07", INTENT_SEQUENCE)
    assert {"O09", "O10"} <= set(block["ops"])


def test_sequence_operators_short_series_fails_open():
    out = run_capability("D-G07", series=_price_series(10), d=5)
    assert out["ok"] is False
    assert out["quality"]["status"] == "empty"


# ---------------- 组合风险族 D-G10…D-G15 ----------------


def test_inverse_volatility_weights_sum_to_one():
    out = run_capability("D-G10", panel=_returns())
    block = _assert_contract(out, "D-G10", INTENT_RISK)
    assert abs(sum(block["weights"].values()) - 1.0) < 1e-5


def test_equal_risk_contribution_is_balanced():
    out = run_capability("D-G11", panel=_returns())
    block = _assert_contract(out, "D-G11", INTENT_RISK)
    assert block["iterations"] >= 1
    assert abs(sum(block["weights"].values()) - 1.0) < 1e-5


def test_risk_contribution_share_sums_to_one():
    panel = _returns()
    weights = _weight_map(sorted(panel))
    out = run_capability("D-G12", panel=panel, weights=weights)
    block = _assert_contract(out, "D-G12", INTENT_RISK)
    assert abs(sum(block["share"].values()) - 1.0) < 1e-6
    assert block["total_risk"] > 0.0


def test_covariance_shrinkage_reports_delta_and_backend():
    out = run_capability("D-G13", panel=_returns())
    block = _assert_contract(out, "D-G13", INTENT_RISK)
    assert 0.0 <= block["delta"] <= 1.0
    assert block["backend"] in ("sklearn", "analytic")
    assert len(block["cov"]) == len(block["symbols"])


def test_pca_risk_decomposition_ratio_is_list_and_sums_below_one():
    out = run_capability("D-G15", panel=_returns(), k=3)
    block = _assert_contract(out, "D-G15", INTENT_RISK)
    assert isinstance(block["ratio"], list)
    assert len(block["ratio"]) == block["k"]
    assert 0.0 < sum(block["ratio"]) <= 1.0 + 1e-9


def test_portfolio_risk_short_sample_fails_open():
    out = run_capability("D-G10", panel=_returns(n=20))
    assert out["ok"] is False
    assert out["quality"]["status"] == "empty"


# ---------------- 归因 D-G18 ----------------


def test_brinson_attribution_aligns_weights_and_sectors():
    panel = _returns()
    names = sorted(panel)
    out = run_capability(
        "D-G18",
        panel=panel,
        weights=_weight_map(names),
        benchmark_weights=dict.fromkeys(names, 1.0),
        sector=_sector_map(names),
    )
    block = _assert_contract(out, "D-G18", INTENT_ATTRIBUTION)
    for key in ("allocation", "selection", "interaction", "active_return"):
        assert isinstance(block[key], float)


# ---------------- Fama-MacBeth D-G21 ----------------


def _macbeth_inputs(n_periods=260, n_assets=8, seed=41):
    rng = random.Random(seed)
    factor = {f"B{i:02d}": [rng.gauss(0.0, 1.0) for _ in range(n_periods)] for i in range(n_assets)}
    target = {
        f"B{i:02d}": [rng.gauss(0.001, 0.02) for _ in range(n_periods)] for i in range(n_assets)
    }
    return factor, target


def test_fama_macbeth_returns_lambda_se_and_periods():
    factor, target = _macbeth_inputs()
    out = run_capability("D-G21", factor=factor, target=target)
    block = _assert_contract(out, "D-G21", INTENT_REGRESSION)
    assert block["n_periods"] == 260
    assert block["n_assets"] == 8
    assert block["se"] > 0.0


def test_fama_macbeth_short_sample_fails_open():
    factor, target = _macbeth_inputs(n_periods=100)
    out = run_capability("D-G21", factor=factor, target=target)
    assert out["ok"] is False
    assert out["quality"]["status"] == "empty"


def test_fama_macbeth_requires_target():
    factor, _ = _macbeth_inputs()
    with pytest.raises(ValueError, match="target"):
        run_capability("D-G21", factor=factor)


# ---------------- 拥挤度 D-G24 ----------------


def test_factor_crowding_returns_scalar_stability():
    out = run_capability("D-G24", panel=_returns(), q=0.2)
    block = _assert_contract(out, "D-G24", INTENT_CROWDING)
    assert block["rho_down_avg"] is not None
    assert block["rho_full_avg"] is not None
    assert block["stability"] is None or isinstance(block["stability"], float)
    assert block["valuation_spread"] is None
    assert "估值价差未提供" in out["answer"]


def test_factor_crowding_accepts_valuation_spread():
    out = run_capability("D-G24", panel=_returns(), q=0.2, valuation_spread=0.03)
    block = _assert_contract(out, "D-G24", INTENT_CROWDING)
    assert block["valuation_spread"] == 0.03


# ---------------- 跨能力一致性 ----------------


def test_institutional_outputs_are_json_serializable_and_deterministic():
    panel = _panel(n_symbols=8, n=90)
    for capability_id, kwargs in (
        ("D-G01", {"panel": panel}),
        ("D-G03", {"panel": panel, "k": 4}),
        ("D-G07", {"series": _price_series(120), "d": 10}),
        ("D-G10", {"panel": _returns()}),
    ):
        first = json.dumps(run_capability(capability_id, **kwargs), sort_keys=True, default=str)
        second = json.dumps(run_capability(capability_id, **kwargs), sort_keys=True, default=str)
        assert first == second, capability_id


def test_all_g_capabilities_are_declared_in_manifest():
    ids = {cap.id for cap in manifest().capabilities}
    expected = {
        "D-G01",
        "D-G02",
        "D-G03",
        "D-G04",
        "D-G05",
        "D-G06",
        "D-G07",
        "D-G10",
        "D-G11",
        "D-G12",
        "D-G13",
        "D-G15",
        "D-G18",
        "D-G21",
        "D-G24",
    }
    assert expected <= ids
    for capability_id in expected:
        assert manifest().get(capability_id).method_binding == "compute"
