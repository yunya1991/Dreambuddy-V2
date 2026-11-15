# -*- coding: utf-8 -*-
"""J 组科研方法能力出口测试（D-J01…D-J29）。

断言口径：信封契约（ok/capability/intent）+ `data.capabilities.<ID>.methods`
必须 ⊆ manifest 声明；非 good 时 answer 必须披露样本；输出可 JSON 序列化且确定性；
样本不足一律 `empty`，不抛异常（唯一例外是编程性参数缺失需显式报错）。
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
from l1agg.capabilities import research_stats as rs  # noqa: E402

# ---------------- 测试数据 ----------------


def _walk(n=200, seed=7, start=100.0, drift=0.0005, vol=0.01):
    rng = random.Random(seed)
    out, level = [], start
    for _ in range(n):
        level *= 1.0 + rng.gauss(drift, vol)
        out.append(level)
    return out


def _partner(series, seed=8, noise=0.01):
    rng = random.Random(seed)
    return [v * (1.0 + rng.gauss(0.0, noise)) for v in series]


def _rows(n_rows=90, n_cols=4, seed=9):
    rng = random.Random(seed)
    return [[rng.gauss(0.0, 1.0) for _ in range(n_cols)] for _ in range(n_rows)]


def _target(rows, seed=10):
    rng = random.Random(seed)
    return [0.3 * sum(r) + rng.gauss(0.0, 0.1) for r in rows]


def _groups(n_groups=3, n_each=40, seed=11):
    rng = random.Random(seed)
    return [[rng.gauss(0.1 * (i + 1), 1.0) for _ in range(n_each)] for i in range(n_groups)]


def _survival(n=60, seed=12):
    rng = random.Random(seed)
    return {
        "time": [abs(rng.gauss(10.0, 3.0)) + 0.1 for _ in range(n)],
        "event": [rng.random() < 0.6 for _ in range(n)],
        "group": [i % 2 for i in range(n)],
        "covariate": [rng.gauss(0.0, 1.0) for _ in range(n)],
    }


def _coords(n=40, seed=13):
    rng = random.Random(seed)
    return [[rng.random(), rng.random()] for _ in range(n)]


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


# ---------------- 单序列族 ----------------


def test_trend_test_reports_mann_kendall_and_sen():
    out = run_capability("D-J01", series=_walk())
    block = _assert_contract(out, "D-J01", rs.INTENT_TREND_TEST)
    assert block["trend"] in ("increasing", "decreasing", "no trend")
    assert block["slope"] is not None
    assert "不代表未来" in out["answer"]


def test_outlier_scan_marks_statistical_outliers():
    out = run_capability("D-J03", series=_walk(), k=3.0)
    block = _assert_contract(out, "D-J03", rs.INTENT_OUTLIER)
    assert block["n_outliers"] == len(block["outliers"])
    assert block["threshold"] > 0.0


def test_smoothing_filter_combines_savgol_wavelet_butterworth():
    out = run_capability("D-J06", series=_walk())
    block = _assert_contract(out, "D-J06", rs.INTENT_SIGNAL)
    assert block["methods"] == ["SC42", "SC44", "SC45"]
    assert len(block["smoothed"]) == block["n"]


def test_spectral_envelope_reports_hilbert():
    out = run_capability("D-J07", series=_walk())
    block = _assert_contract(out, "D-J07", rs.INTENT_SIGNAL)
    assert len(block["envelope"]) == block["n"]
    assert len(block["phase"]) == block["n"]


def test_state_space_filter_is_deterministic():
    first = run_capability("D-J08", series=_walk())
    second = run_capability("D-J08", series=_walk())
    block = _assert_contract(first, "D-J08", rs.INTENT_SIGNAL)
    assert block["last_state"] == second["data"]["capabilities"]["D-J08"]["last_state"]


def test_complexity_measures_include_three_metrics():
    out = run_capability("D-J12", series=_walk())
    block = _assert_contract(out, "D-J12", rs.INTENT_COMPLEXITY)
    assert block["methods"] == ["SC59", "SC60", "SC61"]
    assert block["lempel_ziv"] is not None
    assert 0.0 <= block["permutation_entropy"] <= 1.0


def test_long_memory_reports_hurst():
    out = run_capability("D-J13", series=_walk())
    block = _assert_contract(out, "D-J13", rs.INTENT_COMPLEXITY)
    assert block["hurst"] is not None
    assert len(block["scales"]) == 10


def test_tail_risk_extreme_reports_gev_gpd_level():
    out = run_capability("D-J14", series=_walk())
    block = _assert_contract(out, "D-J14", rs.INTENT_EXTREME)
    assert block["gev"]["mu"] is not None
    assert block["return_level"]["return_period"] == 10.0


def test_measurement_uncertainty_degrades_without_components():
    out = run_capability("D-J15", series=_walk())
    block = _assert_contract(out, "D-J15", rs.INTENT_UNCERTAINTY)
    assert block["methods"] == ["SC11"]
    assert block["u_c"] is None
    assert "未提供分量不确定度" in out["answer"]


def test_measurement_uncertainty_with_components_runs_gum():
    out = run_capability("D-J15", series=_walk(), components=[0.2] * 40)
    block = _assert_contract(out, "D-J15", rs.INTENT_UNCERTAINTY)
    assert block["methods"] == ["SC09", "SC11"]
    assert block["u_c"] is not None and block["U"] == pytest.approx(2.0 * block["u_c"], rel=1e-6)


def test_power_sample_size_reports_power():
    out = run_capability("D-J17", series=_walk())
    block = _assert_contract(out, "D-J17", rs.INTENT_DESIGN)
    assert block["power"] is not None


# ---------------- 双序列族 ----------------


def test_coherence_analysis_returns_peak_frequency():
    s = _walk()
    out = run_capability("D-J09", x=s, y=_partner(s))
    block = _assert_contract(out, "D-J09", rs.INTENT_SIGNAL)
    assert len(block["coherence"]) == len(block["freqs"])
    assert 0.0 <= block["peak_coherence"] <= 1.0


def test_information_measures_single_series_skips_pairs():
    out = run_capability("D-J10", series=_walk())
    block = _assert_contract(out, "D-J10", rs.INTENT_INFORMATION)
    assert block["methods"] == ["SC55"]
    assert block["mutual_info"] is None


def test_information_measures_with_other_adds_mi_and_kl():
    s = _walk()
    out = run_capability("D-J10", series=s, other=_partner(s))
    block = _assert_contract(out, "D-J10", rs.INTENT_INFORMATION)
    assert block["methods"] == ["SC55", "SC56", "SC58"]
    assert block["mutual_info"] is not None
    assert block["js"] is not None


def test_transfer_entropy_reports_net_flow():
    s = _walk()
    out = run_capability("D-J11", x=s, y=_partner(s), lag=1)
    block = _assert_contract(out, "D-J11", rs.INTENT_INFORMATION)
    assert block["te"] is not None
    assert block["net"] == pytest.approx(block["te"] - block["te_reverse"], abs=1e-5)


def test_interval_estimate_single_series_returns_tolerance():
    out = run_capability("D-J16", x=_walk())
    block = _assert_contract(out, "D-J16", rs.INTENT_UNCERTAINTY)
    assert block["methods"] == ["SC11"]
    assert block["tolerance"]["ti_low"] < block["tolerance"]["ti_high"]


def test_interval_estimate_pair_returns_prediction_and_conformal():
    s = _walk()
    out = run_capability("D-J16", x=s, y=_partner(s))
    block = _assert_contract(out, "D-J16", rs.INTENT_UNCERTAINTY)
    assert block["methods"] == ["SC10", "SC12"]
    assert block["prediction"]["pi_low"] < block["prediction"]["pi_high"]


def test_equivalence_test_reports_tost_verdict():
    s = _walk()
    out = run_capability("D-J18", x=s, y=_partner(s))
    block = _assert_contract(out, "D-J18", rs.INTENT_DESIGN)
    assert isinstance(block["equivalent"], bool)
    assert block["bound"] > 0.0


# ---------------- 面板 / 分组族 ----------------


def test_group_comparison_runs_anova_and_tukey():
    out = run_capability("D-J19", groups=_groups())
    block = _assert_contract(out, "D-J19", rs.INTENT_GROUP)
    assert block["methods"] == ["SC25", "SC30"]
    assert block["f"] is not None


def test_regression_diagnostics_covers_five_checks():
    rows = _rows()
    out = run_capability("D-J20", X={"X": rows}, y=_target(rows))
    block = _assert_contract(out, "D-J20", rs.INTENT_DIAGNOSTIC)
    assert block["methods"] == ["SC20", "SC21", "SC22", "SC23", "SC24"]
    assert block["max_vif"] >= 1.0


def test_robust_regression_returns_quantile_and_huber():
    rows = _rows()
    out = run_capability("D-J21", X={"X": rows}, y=_target(rows))
    block = _assert_contract(out, "D-J21", rs.INTENT_DIAGNOSTIC)
    assert block["methods"] == ["SC17", "SC18"]
    assert block["huber"]["intercept"] is not None


def test_cluster_structure_returns_labels():
    out = run_capability("D-J23", X={"X": _rows()}, k=3)
    block = _assert_contract(out, "D-J23", rs.INTENT_CLUSTER)
    assert len(block["labels"]) == block["n"]
    assert block["silhouette"] is not None


def test_spatial_autocorrelation_runs_moran():
    rng = random.Random(14)
    out = run_capability(
        "D-J25",
        coords=_coords(),
        values=[rng.gauss(0.0, 1.0) for _ in range(40)],
    )
    block = _assert_contract(out, "D-J25", rs.INTENT_SPATIAL)
    assert block["methods"] == ["SC67", "SC68", "SC69"]
    assert -1.0 <= block["moran_i"] <= 1.0


def test_survival_analysis_with_group_and_covariate():
    payload = _survival()
    out = run_capability(
        "D-J26",
        time=payload["time"],
        event=payload["event"],
        group=payload["group"],
        covariate=payload["covariate"],
    )
    block = _assert_contract(out, "D-J26", rs.INTENT_SURVIVAL)
    assert block["methods"] == ["SC73", "SC74", "SC75", "SC76"]
    assert block["logrank"]["p"] is not None


def test_survival_analysis_without_group_skips_logrank():
    payload = _survival()
    out = run_capability("D-J26", time=payload["time"], event=payload["event"])
    block = _assert_contract(out, "D-J26", rs.INTENT_SURVIVAL)
    assert "SC74" not in block["methods"]
    assert block["logrank"] is None


def test_reliability_metrics_reports_mtbf_and_alarms():
    payload = _survival()
    out = run_capability("D-J27", time=payload["time"], event=payload["event"])
    block = _assert_contract(out, "D-J27", rs.INTENT_RELIABILITY)
    assert block["mtbf"] > 0.0
    assert isinstance(block["alarms"], list)


def test_meta_analysis_returns_fixed_and_random_effects():
    rng = random.Random(15)
    out = run_capability(
        "D-J28",
        effects=[rng.gauss(0.2, 0.3) for _ in range(32)],
        se=[abs(rng.gauss(0.1, 0.02)) for _ in range(32)],
    )
    block = _assert_contract(out, "D-J28", rs.INTENT_META)
    assert block["methods"] == ["SC79", "SC80", "SC81", "SC82", "SC83"]
    assert block["random"]["pooled"] is not None


def test_missing_data_profile_counts_gaps():
    rng = random.Random(16)
    rows = [
        [None if rng.random() < 0.1 else rng.gauss(0.0, 1.0) for _ in range(4)] for _ in range(80)
    ]
    out = run_capability("D-J29", X={"X": rows})
    block = _assert_contract(out, "D-J29", rs.INTENT_MISSING)
    assert block["mechanism"]["n_missing"] > 0
    assert block["patterns"]["n_patterns"] >= 1


# ---------------- 门禁与一致性 ----------------


@pytest.mark.parametrize(
    "capability_id,kwargs",
    [
        ("D-J01", {"series": [1.0, 2.0, 3.0]}),
        ("D-J03", {"series": [1.0, 2.0, 3.0]}),
        ("D-J12", {"series": [1.0, 2.0, 3.0]}),
        ("D-J17", {"series": [1.0, 2.0, 3.0]}),
        ("D-J09", {"x": [1.0] * 5, "y": [2.0] * 5}),
        ("D-J19", {"groups": [[1.0, 2.0], [3.0, 4.0]]}),
        ("D-J20", {"X": {"X": [[1.0, 2.0]] * 5}, "y": [1.0] * 5}),
        ("D-J25", {"coords": [[0.0, 0.0]] * 5, "values": [1.0] * 5}),
        ("D-J26", {"time": [1.0, 2.0, 3.0]}),
        ("D-J28", {"effects": [0.1, 0.2], "se": [0.1, 0.1]}),
        ("D-J29", {"X": {"X": [[1.0, None]] * 5}}),
    ],
)
def test_short_samples_fail_open(capability_id, kwargs):
    out = run_capability(capability_id, **kwargs)
    assert out["ok"] is False, capability_id
    assert out["quality"]["status"] == "empty"
    assert "样本" in out["answer"]


def test_missing_required_input_for_spatial_fails_open():
    out = run_capability("D-J25", coords=_coords())
    assert out["ok"] is False
    assert out["quality"]["status"] == "empty"


def test_j_outputs_are_json_serializable_and_deterministic():
    s = _walk()
    cases = (
        ("D-J01", {"series": s}),
        ("D-J12", {"series": s}),
        ("D-J16", {"x": s, "y": _partner(s)}),
        ("D-J19", {"groups": _groups()}),
        ("D-J23", {"X": {"X": _rows()}, "k": 3}),
    )
    for capability_id, kwargs in cases:
        first = json.dumps(run_capability(capability_id, **kwargs), sort_keys=True, default=str)
        second = json.dumps(run_capability(capability_id, **kwargs), sort_keys=True, default=str)
        assert first == second, capability_id


def test_all_j_capabilities_are_declared_compute_binding():
    m = manifest()
    ids = {cap.id for cap in m.capabilities}
    expected = {
        "D-J01",
        "D-J03",
        "D-J06",
        "D-J07",
        "D-J08",
        "D-J09",
        "D-J10",
        "D-J11",
        "D-J12",
        "D-J13",
        "D-J14",
        "D-J15",
        "D-J16",
        "D-J17",
        "D-J18",
        "D-J19",
        "D-J20",
        "D-J21",
        "D-J23",
        "D-J25",
        "D-J26",
        "D-J27",
        "D-J28",
        "D-J29",
    }
    assert expected <= ids
    for capability_id in expected:
        cap = m.get(capability_id)
        assert cap.method_binding == "compute"
        assert cap.mode == "deterministic"


def test_methods_are_sorted_unique():
    s = _walk()
    out = run_capability("D-J10", series=s, other=_partner(s))
    methods = out["data"]["capabilities"]["D-J10"]["methods"]
    assert methods == sorted(set(methods))
