# -*- coding: utf-8 -*-
"""SC01–SC46（科研方法族 A 段）实现测试。

覆盖：46 条注册完整性、逐条真实数值/性质断言、输出 schema 一致性、
确定性（seed 固定）、空输入门禁。

运行：cd 54-L1架构能力聚合层 && python3 -m pytest tests/test_methods_research_sc_a.py -q
"""

import json
import math
import os
import sys

import numpy as np
import pytest

_MODULE_ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
if _MODULE_ROOT not in sys.path:
    sys.path.insert(0, _MODULE_ROOT)

import l1agg.methods.research_sc_a  # noqa: F401,E402  # 触发 SC01–SC46 登记
from l1agg.methods import get, run  # noqa: E402

SC_IDS = [f"SC{i:02d}" for i in range(1, 47)]


# ---------------------------------------------------------------- 数据构造


def _rng(seed=7):
    return np.random.default_rng(seed)


def _line(n=60, slope=2.0, intercept=1.0):
    x = np.arange(n, dtype=float)
    return x, slope * x + intercept


def _noisy_line(n=60, slope=2.0, intercept=1.0, noise=0.5, seed=3):
    x, y = _line(n, slope, intercept)
    return x, y + _rng(seed).normal(0.0, noise, n)


def _sine(n=64, period=8.0, amp=2.0):
    t = np.arange(n, dtype=float)
    return amp * np.sin(2.0 * np.pi * t / period)


def _corr_matrix(n=60, p=4, seed=5):
    rng = _rng(seed)
    base = rng.normal(0.0, 1.0, (n, 2))
    M = np.column_stack(
        [
            base[:, 0] + 0.2 * rng.normal(0, 1, n),
            base[:, 1] + 0.2 * rng.normal(0, 1, n),
            base.sum(axis=1) + 0.2 * rng.normal(0, 1, n),
            base[:, 0] - base[:, 1] + 0.2 * rng.normal(0, 1, n),
        ]
    )
    return M[:, :p]


def _clustered(n=60, seed=9):
    rng = _rng(seed)
    centers = np.asarray([[0.0, 0.0], [8.0, 8.0], [-8.0, 8.0]])
    return np.vstack([c + rng.normal(0, 0.4, (n // 3, 2)) for c in centers])


def _data_for(mid):
    """每个 ID 的 (data, params)。"""
    if mid in ("SC01", "SC02"):
        return list(_rng(11).normal(1.0, 1.0, 60)), {"effect_size": 0.5}
    if mid == "SC03":
        base = np.arange(60, dtype=float)
        return {"x": base.tolist(), "y": (base + _rng(2).normal(0, 0.01, 60)).tolist()}, {
            "bound": 0.5
        }
    if mid == "SC04":
        return {"x": list(range(30)), "y": [float(v + 5) for v in range(30)]}, {}
    if mid in ("SC05", "SC06", "SC07", "SC11"):
        return list(100.0 + _rng(4).normal(0, 1.0, 60)), {}
    if mid == "SC08":
        x = np.linspace(1.0, 5.0, 60)
        return {"x": x.tolist(), "y": (2.0 * x).tolist()}, {}
    if mid == "SC09":
        return {"u": [0.1] * 30, "c": [2.0] * 30}, {}
    if mid == "SC10":
        x, y = _noisy_line()
        return {"x": x.tolist(), "y": y.tolist()}, {"x0": 10.0}
    if mid == "SC12":
        x, y = _noisy_line(n=40, noise=0.3)
        return {"x": x.tolist(), "y": y.tolist()}, {}
    if mid == "SC13":
        x, y = _line()
        return {"x": x.tolist(), "y": y.tolist()}, {}
    if mid == "SC14":
        x, y = _line()
        return {"x": x.tolist(), "y": y.tolist(), "w": [1.0] * len(x)}, {}
    if mid == "SC15":
        rng = _rng(13)
        x = rng.normal(0.0, 1.0, 80)
        prob = 1.0 / (1.0 + np.exp(-2.0 * x))
        y = (rng.random(80) < prob).astype(float)
        return {"x": x.tolist(), "y": y.tolist()}, {}
    if mid == "SC16":
        rng = _rng(15)
        x = rng.uniform(0.0, 2.0, 80)
        y = rng.poisson(np.exp(0.5 + 0.5 * x))
        return {"x": x.tolist(), "y": y.tolist()}, {}
    if mid == "SC17":
        x, y = _line()
        return {"x": x.tolist(), "y": y.tolist()}, {}
    if mid == "SC18":
        x, y = _line()
        y = y.copy()
        y[10] = 500.0
        return {"x": x.tolist(), "y": y.tolist()}, {}
    if mid == "SC19":
        rng = _rng(17)
        X = rng.normal(0.0, 1.0, (60, 3))
        y = X @ np.asarray([1.0, 2.0, 3.0]) + rng.normal(0, 0.1, 60)
        return {"X": X.tolist(), "y": y.tolist()}, {}
    if mid == "SC20":
        return {"X": _rng(19).normal(0.0, 1.0, (60, 3)).tolist()}, {}
    if mid in ("SC21", "SC22", "SC23"):
        x, y = _noisy_line(n=80, noise=1.0)
        return {"x": x.tolist(), "y": y.tolist()}, {}
    if mid == "SC24":
        x, y = _line()
        y = y.copy()
        y[20] = 900.0
        return {"x": x.tolist(), "y": y.tolist()}, {}
    if mid == "SC25":
        vals = [float(v) for v in _rng(21).normal(0.0, 1.0, 36)]
        return {"state": ["a"] * 12 + ["b"] * 12 + ["c"] * 12, "target": vals}, {}
    if mid == "SC26":
        rng = _rng(23)
        a = ["a1", "a2"] * 30
        b = (["b1"] * 2 + ["b2"] * 2) * 15
        y = rng.normal(0.0, 1.0, 60)
        return {"y": y.tolist(), "a": a, "b": b}, {}
    if mid == "SC27":
        rng = _rng(25)
        x = rng.uniform(0.0, 10.0, 60)
        grp = ["g1", "g2"] * 30
        y = 2.0 * x + rng.normal(0.0, 0.2, 60)
        return {"y": y.tolist(), "group": grp, "x": x.tolist()}, {}
    if mid == "SC28":
        rng = _rng(27)
        subj = rng.normal(0.0, 1.0, (40, 1))
        M = subj + rng.normal(0.0, 0.05, (40, 3))
        return M.tolist(), {}
    if mid == "SC29":
        f1 = np.tile([0, 1], 20)
        f2 = np.repeat([0, 1], 20)
        y = 1.0 + 2.0 * f1 + 3.0 * f2
        return {"y": y.tolist(), "f1": f1.tolist(), "f2": f2.tolist()}, {}
    if mid == "SC30":
        g = [float(v) for v in _rng(29).normal(0.0, 1.0, 12)]
        return {"state": ["a"] * 12 + ["b"] * 12 + ["c"] * 12, "target": g + g + g}, {}
    if mid in ("SC31", "SC32", "SC33", "SC34", "SC35", "SC36"):
        return _corr_matrix().tolist(), {}
    if mid == "SC37":
        return _clustered().tolist(), {"k": 3}
    if mid == "SC38":
        return _clustered().tolist(), {"k": 3}
    if mid in ("SC39", "SC41", "SC46"):
        return _sine().tolist(), {}
    if mid in ("SC40", "SC44", "SC45"):
        return _sine(n=64).tolist(), {}
    if mid == "SC42":
        return [5.0] * 64, {}
    if mid == "SC43":
        s = _sine()
        return {"x": s.tolist(), "y": s.tolist()}, {}
    raise KeyError(mid)


# ---------------------------------------------------------------- 目录与门禁


def test_all_46_implemented():
    missing = [mid for mid in SC_IDS if not get(mid).implemented]
    assert missing == [], f"未实现：{missing}"
    assert get("SC01").group == "SC" and get("SC01").min_n == 30


def test_empty_input_gate_all_46():
    for mid in SC_IDS:
        out = run(mid, [])
        assert out["gate"] == "insufficient_samples", mid
        assert out["result"] is None


def test_output_schema_matches_all_46():
    for mid in SC_IDS:
        data, params = _data_for(mid)
        out = run(mid, data, **params)
        assert out["gate"] == "ok", mid
        assert set(out["result"]) == set(get(mid).output_schema), mid


def test_alt_data_contracts_supported():
    import l1agg.methods.research_sc_a as sc  # noqa: F401

    anova = sc.sc25_anova({"groups": [[1.0, 2.0, 3.0], [4.0, 5.0, 6.0]]})
    assert anova["k"] == 2 and anova["n"] == 6

    pca = sc.sc31_pca({"matrix": _corr_matrix().tolist()})
    assert sum(pca["ratio"]) == pytest.approx(1.0, abs=1e-6)


def test_flat_multi_key_groups_contract():
    g1 = [float(v) for v in _rng(31).normal(0.0, 1.0, 30)]
    g2 = [float(v) for v in _rng(32).normal(0.5, 1.0, 30)]
    anova = run("SC25", {"g1": g1, "g2": g2})
    assert anova["gate"] == "ok"
    assert anova["result"]["k"] == 2 and anova["result"]["n"] == 60

    tukey = run("SC30", {"g1": g1, "g2": g2})
    assert tukey["gate"] == "ok"
    assert len(tukey["result"]["p_adj"]) == 1


def test_sc43_short_input_deterministic():
    data = {"x": _rng(41).normal(0, 1, 30).tolist(), "y": _rng(42).normal(0, 1, 30).tolist()}
    a = run("SC43", data)
    b = run("SC43", data)
    assert a["gate"] == "ok"
    assert json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True)
    assert len(a["result"]["coherence"]) == len(a["result"]["scales"])


# ---------------------------------------------------------------- §2.1 推断与不确定度


def test_sc01_power_increases_with_n():
    data, params = _data_for("SC01")
    small = run("SC01", data, **params)["result"]
    large = run("SC01", data * 5, **params)["result"]
    assert large["power"] > small["power"]
    assert 0.0 <= small["power"] <= 1.0
    assert small["effect_size"] == params["effect_size"]


def test_sc02_min_n_for_medium_effect():
    data, params = _data_for("SC02")
    out = run("SC02", data, **params)["result"]
    assert 30 <= out["n_star"] <= 40
    assert out["effect_size"] == 0.5 and out["power_target"] == 0.8


def test_sc03_tost_equivalent_when_near_zero():
    data, params = _data_for("SC03")
    out = run("SC03", data, **params)["result"]
    assert out["equivalent"] is True
    assert out["p"] < 0.05
    assert out["p"] == max(out["p_low"], out["p_high"])


def test_sc04_permutation_detects_shift():
    data, params = _data_for("SC04")
    out = run("SC04", data, trials=300, **params)["result"]
    assert out["p_perm"] <= 0.05
    assert abs(out["stat"] + 5.0) < 1e-6


def test_sc05_bootstrap_ci_contains_mean():
    data, params = _data_for("SC05")
    out = run("SC05", data, trials=500, **params)["result"]
    assert out["ci_low"] < out["mean"] < out["ci_high"]
    assert out["n"] == 60


def test_sc06_bca_interval_contains_mean():
    data, params = _data_for("SC06")
    out = run("SC06", data, trials=800, **params)["result"]
    assert out["ci_low"] < out["mean"] < out["ci_high"]
    assert out["ci_high"] - out["ci_low"] > 0


def test_sc07_jackknife_se_positive():
    data, params = _data_for("SC07")
    out = run("SC07", data, **params)["result"]
    assert out["se_jack"] > 0
    assert abs(out["bias"]) < 1.0
    assert out["theta"] == pytest.approx(100.0, abs=0.5)


def test_sc08_delta_recovers_ratio():
    data, params = _data_for("SC08")
    out = run("SC08", data, **params)["result"]
    assert out["estimate"] == pytest.approx(2.0, abs=1e-6)
    assert out["se"] >= 0


def test_sc09_gum_combines_uncertainties():
    data, params = _data_for("SC09")
    out = run("SC09", data, **params)["result"]
    expected = math.sqrt(30 * (2.0 * 0.1) ** 2)
    assert out["u_c"] == pytest.approx(expected, abs=1e-4)
    assert out["U"] == pytest.approx(2 * expected, abs=1e-4)


def test_sc10_prediction_interval_brackets_point():
    data, params = _data_for("SC10")
    out = run("SC10", data, **params)["result"]
    assert out["yhat"] == pytest.approx(21.0, abs=1.0)
    assert out["pi_low"] < out["yhat"] < out["pi_high"]


def test_sc11_tolerance_interval_wider_than_mean_ci():
    data, params = _data_for("SC11")
    out = run("SC11", data, **params)["result"]
    assert out["ti_low"] < 100.0 < out["ti_high"]
    assert out["k"] > 1.0


def test_sc12_conformal_interval_covers_yhat():
    data, params = _data_for("SC12")
    out = run("SC12", data, **params)["result"]
    assert out["ci_low"] < out["yhat"] < out["ci_high"]
    assert out["n"] == 40


# ---------------------------------------------------------------- §2.2 回归与诊断


def test_sc13_ols_recovers_line():
    data, params = _data_for("SC13")
    out = run("SC13", data, **params)["result"]
    assert out["betas"][0] == pytest.approx(2.0, abs=1e-6)
    assert out["intercept"] == pytest.approx(1.0, abs=1e-6)
    assert out["r2"] == pytest.approx(1.0, abs=1e-6)
    assert out["n"] == 60


def test_sc14_wls_recovers_line():
    data, params = _data_for("SC14")
    out = run("SC14", data, **params)["result"]
    assert out["betas"][0] == pytest.approx(2.0, abs=1e-6)
    assert out["intercept"] == pytest.approx(1.0, abs=1e-6)


def test_sc15_logistic_coef_and_odds():
    data, params = _data_for("SC15")
    out = run("SC15", data, **params)["result"]
    assert out["coef"][0] > 0
    assert out["odds_ratio"][0] > 1.0
    assert 0.0 < out["pseudo_r2"] < 1.0


def test_sc16_poisson_coef_and_irr():
    data, params = _data_for("SC16")
    out = run("SC16", data, **params)["result"]
    assert out["coef"][0] > 0
    assert out["irr"][0] > 1.0
    assert out["deviance"] > 0


def test_sc17_quantile_regression_slopes():
    data, params = _data_for("SC17")
    out = run("SC17", data, **params)["result"]
    assert out["taus"] == [0.1, 0.5, 0.9]
    for tau in ("0.1", "0.5", "0.9"):
        assert out["betas"][tau][1] == pytest.approx(2.0, abs=1e-2)


def test_sc18_huber_resists_outlier():
    data, params = _data_for("SC18")
    out = run("SC18", data, **params)["result"]
    assert out["betas"][0] == pytest.approx(2.0, abs=0.05)
    assert out["scale"] >= 0


def test_sc19_ridge_shrinks_vs_ols():
    data, params = _data_for("SC19")
    ridge = run("SC19", data, **params)["result"]
    X = np.asarray(data["X"], dtype=float)
    y = np.asarray(data["y"], dtype=float)
    Xs = (X - X.mean(axis=0)) / X.std(axis=0)
    ols = run("SC13", {"X": Xs.tolist(), "y": y.tolist()})["result"]
    assert np.linalg.norm(ridge["betas"]) <= np.linalg.norm(ols["betas"]) + 1e-9
    assert ridge["alpha"] == 1.0


def test_sc20_vif_low_for_independent_columns():
    data, params = _data_for("SC20")
    out = run("SC20", data, **params)["result"]
    assert len(out["vif"]) == 3
    assert out["max_vif"] < 5.0


def test_sc21_sc22_heteroskedasticity_pvalues():
    for mid in ("SC21", "SC22"):
        data, params = _data_for(mid)
        out = run(mid, data, **params)["result"]
        assert out["lm"] >= 0
        assert 0.0 <= out["p"] <= 1.0


def test_sc23_durbin_watson_near_two():
    data, params = _data_for("SC23")
    out = run("SC23", data, **params)["result"]
    assert 0.5 < out["dw"] < 3.5


def test_sc24_cooks_flags_outlier():
    data, params = _data_for("SC24")
    out = run("SC24", data, **params)["result"]
    assert out["n_outliers"] >= 1
    assert out["cooks_max"] > 4.0 / out["n"]
    assert out["flags"][20] is True


# ---------------------------------------------------------------- §2.3 实验设计


def test_sc25_anova_no_group_effect():
    data, params = _data_for("SC25")
    out = run("SC25", data, **params)["result"]
    assert out["k"] == 3 and out["n"] == 36
    assert out["p"] > 0.05
    assert out["eta2"] < 0.2


def test_sc26_two_way_anova_no_effects():
    data, params = _data_for("SC26")
    out = run("SC26", data, **params)["result"]
    assert out["n"] == 60
    assert len(out["f"]) == 3
    assert all(p > 0.01 for p in out["p"])


def test_sc27_ancova_covariate_coef():
    data, params = _data_for("SC27")
    out = run("SC27", data, **params)["result"]
    assert out["coef_covariate"] == pytest.approx(2.0, abs=0.1)
    assert 0.0 <= out["p"] <= 1.0


def test_sc28_repeated_measures_no_condition_effect():
    data, params = _data_for("SC28")
    out = run("SC28", data, **params)["result"]
    assert out["n"] == 40
    assert out["df_num"] == 2.0 and out["df_den"] == 78.0
    assert out["p"] > 0.01


def test_sc29_factorial_main_effects():
    data, params = _data_for("SC29")
    out = run("SC29", data, **params)["result"]
    assert out["effects"]["f1"] == pytest.approx(2.0, abs=1e-6)
    assert out["effects"]["f2"] == pytest.approx(3.0, abs=1e-6)
    assert abs(out["effects"]["interaction_f1_f2"]) < 1e-6
    assert out["n"] == 40 and out["k"] == 2


def test_sc30_tukey_identical_groups_not_significant():
    data, params = _data_for("SC30")
    out = run("SC30", data, **params)["result"]
    assert len(out["p_adj"]) == 3
    assert all(p > 0.05 for p in out["p_adj"])
    assert out["reject"] == [False, False, False]


# ---------------------------------------------------------------- §2.4 降维与结构


def test_sc31_pca_ratio_sums_to_one():
    data, params = _data_for("SC31")
    out = run("SC31", data, **params)["result"]
    assert sum(out["ratio"]) == pytest.approx(1.0, abs=1e-6)
    assert out["ratio"][0] > 0.3
    assert out["cum_ratio"][-1] == pytest.approx(1.0, abs=1e-6)
    assert len(out["loadings"]) == out["k"] == 4


def test_sc32_svd_singular_values_sorted():
    data, params = _data_for("SC32")
    out = run("SC32", data, **params)["result"]
    assert len(out["s"]) == 4
    assert out["s"] == sorted(out["s"], reverse=True)
    assert out["s"][0] > 0
    assert len(out["u"]) == 60


def test_sc33_factor_analysis_shapes():
    data, params = _data_for("SC33")
    out = run("SC33", data, **params)["result"]
    assert out["k"] == 2
    assert len(out["loadings"]) == 2 and len(out["loadings"][0]) == 4
    assert len(out["uniqueness"]) == 4
    assert all(u >= -1e-9 for u in out["uniqueness"])


def test_sc34_ica_source_shape():
    data, params = _data_for("SC34")
    out = run("SC34", data, **params)["result"]
    assert len(out["sources"]) == 60
    assert out["k"] == 2
    assert len(out["mixing"]) == 4 and len(out["mixing"][0]) == 2


def test_sc35_graphical_lasso_precision():
    data, params = _data_for("SC35")
    out = run("SC35", data, **params)["result"]
    assert len(out["precision"]) == 4
    assert out["edges"] >= 0
    assert out["alpha"] == 0.1


def test_sc36_hierarchical_linkage_shape():
    data, params = _data_for("SC36")
    out = run("SC36", data, **params)["result"]
    assert out["p"] == 4
    assert len(out["linkage"]) == 3
    assert all(len(row) == 4 for row in out["linkage"])


def test_sc37_kmeans_recovers_three_clusters():
    data, params = _data_for("SC37")
    out = run("SC37", data, **params)["result"]
    assert out["k"] == 3
    assert len(out["labels"]) == 60
    assert len(set(out["labels"])) == 3
    assert out["inertia"] >= 0


def test_sc38_silhouette_high_for_separated_clusters():
    data, params = _data_for("SC38")
    out = run("SC38", data, **params)["result"]
    assert out["k"] == 3
    assert out["silhouette"] > 0.5


# ---------------------------------------------------------------- §2.5 信号与频谱


def test_sc39_fft_dominant_frequency():
    data, params = _data_for("SC39")
    out = run("SC39", data, **params)["result"]
    assert out["dominant_freq"] == pytest.approx(1.0 / 8.0, abs=1e-6)
    assert len(out["freq"]) == 33


def test_sc40_welch_psd_length():
    data, params = _data_for("SC40")
    out = run("SC40", data, **params)["result"]
    assert len(out["psd"]) == len(out["freq"]) == 33
    assert max(out["psd"]) > 0


def test_sc41_lomb_scargle_period():
    data, params = _data_for("SC41")
    out = run("SC41", data, **params)["result"]
    assert 6.0 <= out["period"] <= 10.0
    assert len(out["power"]) == 500


def test_sc42_dwt_constant_signal_has_zero_details():
    data, params = _data_for("SC42")
    out = run("SC42", data, **params)["result"]
    assert out["levels"] == 4
    for band in out["coeffs"][:-1]:
        assert all(abs(v) < 1e-9 for v in band)
    assert sum(out["energy"]) == pytest.approx(1.0, abs=1e-6)


def test_sc43_wavelet_coherence_identical_series():
    data, params = _data_for("SC43")
    out = run("SC43", data, **params)["result"]
    assert out["mean_coherence"] > 0.9
    assert out["max_coherence"] <= 1.0
    assert len(out["coherence"]) == len(out["scales"])


def test_sc44_savgol_preserves_length():
    data, params = _data_for("SC44")
    out = run("SC44", data, **params)["result"]
    assert out["n"] == 64 and len(out["smoothed"]) == 64
    assert out["window"] == 11 and out["polyorder"] == 3


def test_sc45_butterworth_constant_passthrough():
    data, params = _data_for("SC45")
    out = run("SC45", list([5.0] * 64), **params)["result"]
    assert len(out["filtered"]) == 64
    assert max(abs(v - 5.0) for v in out["filtered"]) < 1e-6
    assert out["order"] == 4


def test_sc46_hilbert_envelope_of_sine():
    data, params = _data_for("SC46")
    out = run("SC46", data, **params)["result"]
    inner = out["envelope"][10:-10]
    assert 1.8 < float(np.mean(inner)) < 2.2
    assert len(out["phase"]) == 64


# ---------------------------------------------------------------- 确定性与一致性


def test_deterministic_random_methods():
    cases = {
        "SC04": ({"x": list(range(30)), "y": [float(v + 1) for v in range(30)]}, {"trials": 200}),
        "SC05": (list(100.0 + _rng(4).normal(0, 1.0, 40)), {"trials": 200}),
        "SC12": (_data_for("SC12")[0], {}),
        "SC37": (_clustered().tolist(), {"k": 3}),
        "SC38": (_clustered().tolist(), {"k": 3}),
        "SC34": (_corr_matrix().tolist(), {}),
    }
    for mid, (data, params) in cases.items():
        a = run(mid, data, **params)
        b = run(mid, data, **params)
        assert json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True), mid


def test_deterministic_pure_methods():
    for mid in ("SC13", "SC25", "SC31", "SC39", "SC42", "SC46"):
        data, params = _data_for(mid)
        a = run(mid, data, **params)
        b = run(mid, data, **params)
        assert json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True), mid
