# -*- coding: utf-8 -*-
"""SC47–SC92 科研方法族单测：逐条真实数值/性质断言 + 确定性 + 门禁 + 实现完整性。"""

from __future__ import annotations

import math
import random

import l1agg.methods.research_sc_b  # noqa: F401  （必须先导入以完成 register）
import numpy as np
import pytest
from l1agg.methods import get, run

TOL = 1e-6


# ---------------------------------------------------------------- 固定样本（确定性）


def _gauss(n: int, seed: int = 7, mu: float = 0.0, sd: float = 1.0):
    rng = random.Random(seed)
    return [mu + sd * rng.gauss(0.0, 1.0) for _ in range(n)]


SER = _gauss(200, seed=7)  # 白噪声 n=200
X_T = [float(i) for i in range(200)]
Y_LIN = [0.7 * v + 0.0 for v in X_T]
STEP = [0.0] * 60 + [5.0] * 60
SPIKE = [0.0] * 120
SPIKE[40] = 20.0

GRID = [[float(i % 10), float(i // 10)] for i in range(100)]
GRID_VALS = [GRID[i][0] * 1.0 + GRID[i][1] * 0.5 + 1.0 for i in range(100)]
SPATIAL = {"coords": GRID, "values": GRID_VALS}

T_SURV = [float(i) for i in range(1, 61)]
E_SURV = [1.0] * 40 + [0.0] * 20
GROUP_ALT = ["a" if i % 2 == 0 else "b" for i in range(60)]

EFFECT = [0.3 + 0.02 * (i % 7) for i in range(30)]
SE = [0.1 + 0.01 * (i % 5) for i in range(30)]
META = {"effect": EFFECT, "se": SE}

MAT = [[None if (i % 7 == 0 and j == 2) else float(i + j) for j in range(4)] for i in range(40)]


def _ring_adj(n: int = 40) -> list:
    a = np.zeros((n, n))
    for i in range(n):
        a[i, (i + 1) % n] = a[(i + 1) % n, i] = 1.0
    for grp in (range(0, 10), range(20, 30)):
        for i in grp:
            for j in grp:
                if i != j:
                    a[i, j] = 1.0
    return a.tolist()


def _res(mid: str, data, **params):
    out = run(mid, data, **params)
    assert out["gate"] == "ok", f"{mid} gate={out['gate']}"
    res = out["result"]
    spec = get(mid)
    assert set(res) == set(spec.output_schema), (mid, sorted(res), spec.output_schema)
    return res


# ---------------------------------------------------------------- SC47–SC54


def test_sc47_kalman():
    r = _res("SC47", SER)
    assert len(r["state"]) == 200 and len(r["gain"]) == 200
    assert all(0.0 < g < 1.0 for g in r["gain"])
    assert abs(r["last_state"] - sum(SER[-20:]) / 20.0) < 1.0
    assert r["loglik"] is not None


def test_sc48_coherence():
    r = _res("SC48", {"x": X_T, "y": [3.0 * v for v in X_T]})
    assert r["peak_coherence"] > 0.95
    assert len(r["freqs"]) == len(r["coherence"]) > 0


def test_sc49_cusum():
    r = _res("SC49", STEP)
    assert any(abs(bp - 60) <= 3 for bp in r["breakpoints"]), r["breakpoints"]


def test_sc50_pelt():
    r = _res("SC50", STEP)
    assert r["n_changepoints"] >= 1
    assert any(58 <= bp <= 62 for bp in r["breakpoints"]), r["breakpoints"]
    assert r["method"] == "exact_dp_l2"


def test_sc51_pettitt():
    r = _res("SC51", STEP)
    assert r["p"] < 0.01
    assert 55 <= r["point"] <= 65


def test_sc52_mann_kendall():
    r = _res("SC52", X_T)
    assert r["tau"] == pytest.approx(1.0, abs=1e-4)
    assert r["trend"] == "increasing"
    assert r["p"] < 0.05


def test_sc53_sen():
    r = _res("SC53", Y_LIN)
    assert r["slope"] == pytest.approx(0.7, abs=0.01)
    assert r["ci_low"] <= r["slope"] <= r["ci_high"]


def test_sc54_seasonal_mk():
    season, value = [], []
    for yr in range(10):
        for s in range(12):
            season.append(f"s{s}")
            value.append(yr * 1.0 + s * 0.1)
    r = _res("SC54", {"season": season, "value": value})
    assert r["trend"] == "increasing"
    assert r["n_seasons"] == 12
    assert r["p"] < 0.05


# ---------------------------------------------------------------- SC55–SC62


def test_sc55_shannon_entropy():
    r = _res("SC55", SER, bins=10)
    assert 0 < r["h"] <= math.log(10) + TOL
    assert 0 < r["h_norm"] <= 1.0


def test_sc56_mutual_info():
    r = _res("SC56", {"x": X_T, "y": [2.0 * v for v in X_T]})
    assert r["mi"] > 0.5
    assert r["mi_norm"] > 0.8


def test_sc57_transfer_entropy():
    r = _res("SC57", {"x": SER, "y": [0.0] + SER[:-1]})
    assert r["te"] > r["te_reverse"]
    assert r["net"] > 0


def test_sc58_kl_divergence():
    same = _res("SC58", {"x": SER, "y": list(SER)})
    diff = _res("SC58", {"x": SER, "y": [3.0 * v for v in SER]})
    assert same["kl"] < 0.01 and same["js"] < 0.01
    assert diff["kl"] > 0.05
    assert diff["kl_reverse"] > 0.05


def test_sc59_lempel_ziv():
    r = _res("SC59", SER)
    assert 0 < r["c"] < 2.0
    flat = _res("SC59", [1.0] * 100)
    assert flat["c_raw"] == 2


def test_sc60_sample_entropy():
    r = _res("SC60", SER)
    assert 0 <= r["sampen"] < 5.0
    assert r["m"] == 2 and r["r"] > 0


def test_sc61_permutation_entropy():
    r = _res("SC61", SER)
    assert 0 < r["pe_norm"] <= 1.0
    mono = _res("SC61", [float(i) for i in range(60)])
    assert mono["pe"] == pytest.approx(0.0)


def test_sc62_dfa():
    r = _res("SC62", SER)
    assert 0.2 < r["alpha"] < 1.0
    assert r["h"] == r["alpha"]


# ---------------------------------------------------------------- SC63–SC70


def test_sc63_gev():
    r = _res("SC63", SER, block_size=10)
    assert r["blocks"] == 20
    assert r["sigma"] > 0
    assert abs(r["xi"]) < 2.0


def test_sc64_gpd():
    r = _res("SC64", SER)
    assert r["n_exceed"] == 10
    assert r["xi"] < 1.0 and r["beta"] > 0


def test_sc65_return_level():
    r = _res("SC65", SER, return_period=10.0)
    assert r["return_period"] == 10.0
    assert r["level"] > r["mu"]


def test_sc66_hill():
    r = _res("SC66", [abs(v) + 0.1 for v in SER])
    assert r["k"] == 20
    assert r["alpha"] > 0 and r["threshold"] > 0


def test_sc67_moran():
    r = _res("SC67", SPATIAL)
    assert -1.0 <= r["i"] <= 1.0
    assert r["i"] > 0.5
    assert r["z"] > 1.96


def test_sc68_geary():
    r = _res("SC68", SPATIAL)
    assert 0 <= r["c"] < 1.0
    assert 0 <= r["p"] <= 1.0


def test_sc69_semivariogram():
    r = _res("SC69", SPATIAL, n_bins=8)
    assert len(r["lags"]) == len(r["gamma"]) == len(r["counts"]) == 8
    assert sum(r["counts"]) == 100 * 99 // 2
    assert r["gamma"][-1] > r["gamma"][0]


def test_sc70_kriging():
    r = _res("SC70", SPATIAL, targets=[[3.5, 3.5], [0.0, 0.0]])
    assert abs(r["pred"][1] - 1.0) < 0.05  # 观测点插值忠实
    assert abs(r["pred"][0] - 6.25) < 0.5  # 线性面上内插合理
    assert r["var"][1] < r["var"][0]
    assert r["sill"] > 0 and r["range"] > 0


# ---------------------------------------------------------------- SC71–SC78


def test_sc71_centrality():
    r = _res("SC71", {"adj": _ring_adj()})
    assert r["n_nodes"] == 40 and r["n_edges"] > 40
    assert max(r["betweenness"]) > 0
    assert isinstance(r["top_node"], int)


def test_sc72_communities():
    r = _res("SC72", {"adj": _ring_adj()})
    assert r["n_communities"] >= 2
    assert -1.0 <= r["modularity"] <= 1.0
    assert r["modularity"] > 0


def test_sc73_kaplan_meier():
    r = _res("SC73", {"time": T_SURV, "event": E_SURV})
    assert all(b <= a + TOL for a, b in zip(r["survival"], r["survival"][1:], strict=False))
    assert r["median"] == pytest.approx(30.0)
    assert r["n_events"] == 40


def test_sc74_logrank():
    r = _res("SC74", {"time": T_SURV, "event": E_SURV, "group": GROUP_ALT})
    assert r["p"] > 0.05  # 两组同分布 → 无差异
    assert r["chi2"] >= 0 and r["n"] == 60


def test_sc75_cox():
    x = _gauss(60, seed=11, mu=0.0, sd=1.0)
    r = _res("SC75", {"time": T_SURV, "event": E_SURV, "x": x})
    assert len(r["coef"]) == 1
    assert r["hr"][0] == pytest.approx(math.exp(r["coef"][0]), rel=1e-3)
    assert 0 <= r["p"][0] <= 1


def test_sc76_weibull():
    r = _res("SC76", T_SURV)
    assert r["shape"] > 0 and r["scale"] > 0
    assert r["mean"] == pytest.approx(float(np.mean(T_SURV)), abs=1e-4)


def test_sc77_mtbf():
    r = _res("SC77", {"time": T_SURV, "event": E_SURV})
    assert r["n_events"] == 40
    assert r["mtbf"] == pytest.approx(r["total_time"] / 40)
    assert r["failure_rate"] == pytest.approx(1.0 / r["mtbf"], rel=1e-3)


def test_sc78_control_chart():
    r = _res("SC78", SPIKE)
    assert 40 in r["alarms"]
    assert r["ucl"] > r["center"] > r["lcl"]


# ---------------------------------------------------------------- SC79–SC86


def test_sc79_meta_fixed():
    r = _res("SC79", META)
    assert min(EFFECT) <= r["pooled"] <= max(EFFECT)
    assert r["ci_low"] < r["pooled"] < r["ci_high"]
    assert r["p"] < 0.01


def test_sc80_meta_random():
    r = _res("SC80", META)
    assert r["tau2"] >= 0
    assert 0 <= r["i2"] <= 1
    assert r["ci_low"] < r["pooled"] < r["ci_high"]


def test_sc81_heterogeneity():
    r = _res("SC81", META)
    assert r["df"] == 29
    assert r["q"] > 0
    assert 0 <= r["i2"] <= 1 and r["h2"] > 0


def test_sc82_funnel_asymmetry():
    r = _res("SC82", META)
    assert r["p"] > 0.05  # 对称数据 → Egger 不显著
    assert 0 <= r["p"] <= 1


def test_sc83_trim_and_fill():
    r = _res("SC83", META)
    assert isinstance(r["n_filled"], int) and r["n_filled"] >= 0
    assert r["side"] in ("left", "right")
    assert math.isfinite(r["adj_pooled"])
    again = _res("SC83", META)
    assert again == r


def test_sc84_missing_mechanism():
    r = _res("SC84", {"matrix": MAT})
    assert r["df"] >= 1
    assert r["chi2"] >= 0
    assert 0 <= r["p"] <= 1
    assert r["missing_rate"] == pytest.approx(6 / 160, rel=1e-3)


def test_sc85_knn_impute():
    r = _res("SC85", {"matrix": MAT})
    assert r["n_filled"] == 6
    assert all(v is not None for row in r["filled"] for v in row)
    assert len(r["filled"]) == 40 and all(len(row) == 4 for row in r["filled"])


def test_sc86_mahalanobis():
    rows = [[0.0] * 3 for _ in range(40)]
    rng = random.Random(5)
    rows = [[rng.gauss(0, 1) for _ in range(3)] for _ in range(40)] + [[9.0, 9.0, 9.0]]
    r = _res("SC86", {"matrix": rows})
    assert r["n_outliers"] >= 1
    assert r["flags"][-1] is True
    assert r["threshold"] > 0


# ---------------------------------------------------------------- SC87–SC92


def test_sc87_missing_patterns():
    r = _res("SC87", {"matrix": MAT})
    assert r["n_cols"] == 4 and r["n"] == 40
    assert any(p["pattern"] == "0010" and p["count"] == 6 for p in r["patterns"])
    assert r["column_missing"] == [0, 0, 6, 0]
    assert sum(p["count"] for p in r["patterns"]) == 40


def test_sc88_duplicate_records():
    rows = [[float(i % 7), float(i % 5), float(i % 3)] for i in range(40)] + [[0.0, 0.0, 0.0]]
    r = _res("SC88", {"matrix": rows})
    assert [0, 40] in r["exact_groups"]
    assert r["n_dups"] >= 1


def test_sc89_consistency_rules():
    table = {
        "a": [float(i + 1) for i in range(30)],
        "b": [float(50 - i) for i in range(30)],
        "c": [1.0] * 29 + [None],
    }
    rules = [
        {"type": "range", "column": "a", "lo": 1.0, "hi": 2.5},
        {"type": "monotone", "column": "a", "direction": "up"},
        {"type": "compare", "left": "a", "right": "b", "op": "<="},
        {"type": "notnull", "column": "c"},
    ]
    rules += [{"type": "notnull", "column": "a"} for _ in range(26)]
    r = _res("SC89", {"table": table, "rules": rules})
    assert r["n_rules"] == 30 and r["n_rows"] == 30
    assert r["n_violations"] >= 3
    assert any(v["type"] == "compare" for v in r["violations"])
    assert any(v["type"] == "notnull" for v in r["violations"])
    assert any(v["type"] == "range" for v in r["violations"])


def test_sc90_pit_time():
    avail = [f"2024-01-{d:02d}T00:00:00" for d in range(1, 31)]
    used = list(avail)
    used[1] = "2024-01-01T00:00:00"  # 可用时间(1/2)晚于使用时间 → 违规
    r = _res("SC90", {"available": avail, "used": used})
    assert r["pass"] is False
    assert r["n_violations"] == 1 and r["violations"] == [1]
    assert r["max_lag"] == pytest.approx(86400.0)


def test_sc91_stl_decompose():
    rng = random.Random(3)
    ser = [10.0 + 0.2 * i + 3.0 * ((i % 12) == 0) + rng.gauss(0, 0.3) for i in range(120)]
    r = _res("SC91", ser)
    assert r["period"] == 12
    assert len(r["trend"]) == len(r["seasonal"]) == len(r["resid"]) == 120
    recon = np.array(r["trend"]) + np.array(r["seasonal"]) + np.array(r["resid"])
    assert np.allclose(recon, ser, atol=1e-4)
    assert r["seasonal_strength"] > 0.5


def test_sc92_outliers():
    spike = _res("SC92", SPIKE)
    assert [o["index"] for o in spike["outliers"]] == [40]
    assert spike["outliers"][0]["type"] == "AO"
    step = _res("SC92", STEP)
    assert any(o["type"] == "LS" for o in step["outliers"])
    assert all(abs(o["index"] - 60) <= 3 for o in step["outliers"])


# ---------------------------------------------------------------- 确定性 / 门禁 / 完整性


def test_determinism_repeat_calls():
    assert _res("SC50", STEP) == _res("SC50", STEP)
    assert _res("SC92", SPIKE) == _res("SC92", SPIKE)


def test_determinism_no_random_state_leak():
    a = _res("SC67", SPATIAL)
    _res("SC92", SER)
    b = _res("SC67", SPATIAL)
    assert a == b


def test_gate_insufficient_samples():
    out = run("SC47", [1.0, 2.0, 3.0])
    assert out["gate"] == "insufficient_samples" and out["result"] is None
    out2 = run("SC58", {"x": [1.0] * 5, "y": [2.0] * 5})
    assert out2["gate"] == "insufficient_samples" and out2["result"] is None


def test_meta_synthetic_cases_hit():
    """SC79–SC83 自带 synthetic 用例可跑，且解析解期望值全部命中（harness 复用同一用例）。"""
    for mid in ("SC79", "SC80", "SC81", "SC82", "SC83"):
        make = get(mid).checks.synthetic
        assert make is not None, mid
        case = make()
        out = run(mid, case["data"], **case.get("params", {}))
        assert out["gate"] == "ok", mid
        assert case["expect"], mid
        for path, expect in case["expect"].items():
            node = out
            for part in path.split("."):
                node = node[part]
            if isinstance(expect, float):
                assert node == pytest.approx(expect, rel=1e-3, abs=1e-3), (mid, path, node)
            else:
                assert node == expect, (mid, path, node)


def test_all_46_methods_implemented():
    for i in range(47, 93):
        mid = f"SC{i}"
        spec = get(mid)
        assert spec.implemented is True, mid
        assert spec.group == "SC"
        assert spec.func is not None
        assert spec.output_schema, mid
