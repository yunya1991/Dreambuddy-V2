# -*- coding: utf-8 -*-
"""M 组多变量补齐批测试：M08–M10、M13–M16、M18–M22、M26。"""

import json
import math
import os
import random
import statistics
import sys

import pytest

_MODULE_ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
if _MODULE_ROOT not in sys.path:
    sys.path.insert(0, _MODULE_ROOT)

import l1agg.methods.correlation  # noqa: F401,E402
from l1agg.methods import get, run  # noqa: E402

N = 160
EXTRA_IDS = [
    "M08",
    "M09",
    "M10",
    "M13",
    "M14",
    "M15",
    "M16",
    "M18",
    "M19",
    "M20",
    "M21",
    "M22",
    "M26",
]


def _gauss(n, seed, sigma=1.0):
    rng = random.Random(seed)
    return [rng.gauss(0.0, sigma) for _ in range(n)]


def _panel_three_groups(n=140):
    """3 组、每组 2 个高相关资产的合成面板。"""
    rng = random.Random(3)
    series = {}
    for gi in range(3):
        base = [rng.gauss(0.0, 1.0) for _ in range(n)]
        for j in range(2):
            series[f"g{gi}_{j}"] = [v + 0.02 * rng.gauss(0.0, 1.0) for v in base]
    return {"series": series}


# ---------- 注册与契约 ----------


def test_extra_batch_registered():
    for mid in EXTRA_IDS:
        assert get(mid).implemented is True, mid
        assert get(mid).output_schema, mid
    assert get("M08").input_kind == "panel"
    assert get("M13").input_kind == "pairs"
    assert get("M19").input_kind == "panel"
    assert get("M18").layer == "D1"
    assert get("M13").layer == "D3"


def test_output_schema_matches_result_keys():
    for mid in EXTRA_IDS:
        spec = get(mid)
        case = spec.checks.synthetic()
        out = run(mid, case["data"], **case.get("params", {}))
        assert out["gate"] == "ok", mid
        assert set(out["result"]) == set(spec.output_schema), mid


@pytest.mark.parametrize("mid", EXTRA_IDS)
def test_empty_input_returns_gate(mid):
    spec = get(mid)
    empty = {"series": {}} if spec.input_kind == "panel" else {"x": [], "y": []}
    out = run(mid, empty)
    assert out["gate"] == "insufficient_samples"
    assert out["result"] is None


# ---------- M08–M10 ----------


def test_m08_partial_corr_removes_common_driver():
    n = 200
    z = _gauss(n, 1)
    x = [a + b for a, b in zip(z, _gauss(n, 2), strict=False)]
    y = [a + b for a, b in zip(z, _gauss(n, 3), strict=False)]
    res = run("M08", {"series": {"x": x, "y": y, "z": z}})["result"]
    assert res["r_xy"] > 0.4  # 原始相关显著
    assert abs(res["r"]) < 0.10  # 控制 z 后几乎消失
    assert res["control"] == "z"
    assert res["n"] == n
    assert res["p"] > 0.05


def test_m09_distance_corr_properties():
    n = 120
    x = [float(i) - (n - 1) / 2.0 for i in range(n)]  # 关于 0 对称
    y_lin = [2.0 * v + 5.0 for v in x]
    y_sq = [v * v for v in x]
    lin = run("M09", {"x": x, "y": y_lin})["result"]
    sq = run("M09", {"x": x, "y": y_sq})["result"]
    assert lin["dcor"] == pytest.approx(1.0, abs=1e-6)  # 线性变换不变
    assert lin["dcor2"] == pytest.approx(lin["dcor"] ** 2, abs=1e-6)
    assert sq["dcor"] > 0.3  # 捕捉非线性
    assert abs(_pearson(x, y_sq)) < 1e-6  # 线性相关为 0


def test_m10_mutual_info_and_nmi():
    n = 400
    x = _gauss(n, 7)
    indep = _gauss(n, 8)
    res_ind = run("M10", {"x": x, "y": indep})["result"]
    res_det = run("M10", {"x": x, "y": [2.0 * v - 3.0 for v in x]})["result"]
    assert res_ind["mi"] < 0.15
    assert res_ind["nmi"] < 0.25
    assert res_det["nmi"] == pytest.approx(1.0, abs=1e-3)
    assert res_det["mi"] > res_ind["mi"]
    assert res_det["bins"] == 8


# ---------- M13–M16 ----------


def test_m13_cointegration_recovers_beta():
    n = 240
    rng = random.Random(21)
    x = [0.0]
    for _ in range(n - 1):
        x.append(x[-1] + rng.gauss(0, 1))
    y = [2.0 * v + rng.gauss(0, 0.5) for v in x]
    res = run("M13", {"x": x, "y": y})["result"]
    assert res["p"] < 0.05
    assert res["beta"] == pytest.approx(2.0, abs=0.05)
    assert res["stat"] < res["crit_5pct"]
    assert res["n"] == n


def test_m14_ols_slope_and_r2():
    x = [float(i) for i in range(N)]
    y = [2.0 * v + 3.0 + 1e-3 * math.sin(i * 1.7) for i, v in enumerate(x)]
    res = run("M14", {"x": x, "y": y})["result"]
    assert res["beta"] == pytest.approx(2.0, abs=1e-3)
    assert res["alpha"] == pytest.approx(3.0, abs=1e-2)
    assert res["r2"] > 0.999
    assert res["t"] > 10
    assert res["p"] < 1e-6
    assert res["n"] == N


def test_m15_multi_factor_betas():
    n = 160
    f1 = _gauss(n, 1)
    f2 = _gauss(n, 2)
    y = [2.0 * a + 3.0 * b + 0.01 * e for a, b, e in zip(f1, f2, _gauss(n, 3), strict=False)]
    res = run("M15", {"target": y, "factors": {"f1": f1, "f2": f2}})["result"]
    assert res["betas"]["f1"] == pytest.approx(2.0, abs=0.02)
    assert res["betas"]["f2"] == pytest.approx(3.0, abs=0.02)
    assert res["factor_names"] == ["f1", "f2"]
    assert res["r2"] > 0.99
    assert set(res["t"]) == {"f1", "f2"}


def test_m16_regression_residuals_stationary():
    n = 200
    x = [math.sin(i * 0.5) + 0.2 * math.cos(i * 1.1) for i in range(n)]
    noise = _gauss(n, 31, sigma=0.3)
    y = [2.0 * a + e for a, e in zip(x, noise, strict=False)]
    res = run("M16", {"series": {"y": y, "x": x}})["result"]
    assert res["p"] < 0.01
    assert res["adf"] < 0
    assert res["r2"] > 0.8
    assert res["lags"] >= 0


# ---------- M18–M22 ----------


def test_m18_tracking_error_matches_stdev():
    bench = _gauss(150, 41, sigma=0.01)
    port = [b + 0.0002 for b in bench]
    res = run("M18", {"x": port, "y": bench})["result"]
    assert res["te"] == pytest.approx(0.0, abs=1e-12)
    assert res["mean_excess"] == pytest.approx(0.0002, abs=1e-12)
    assert res["te_annual"] == pytest.approx(0.0, abs=1e-9)

    port2 = [2.0 * b for b in bench]
    res2 = run("M18", {"x": port2, "y": bench})["result"]
    diff = [a - b for a, b in zip(port2, bench, strict=False)]
    assert res2["te"] == pytest.approx(statistics.stdev(diff), abs=1e-6)
    assert res2["n"] == 150


def test_m19_pca_explained_variance():
    data = _panel_three_groups()
    res = run("M19", data)["result"]
    assert res["n_features"] == 6
    assert res["k"] == 3
    assert all(0.0 <= v <= 1.0 for v in res["ratio"])
    assert sum(res["ratio"]) <= 1.0 + 1e-6
    assert res["cum_ratio"][-1] == pytest.approx(sum(res["ratio"]), abs=1e-6)

    a = [float(i) for i in range(N)]
    collinear = run("M19", {"series": {"A": a, "B": [2.0 * v for v in a], "C": [-v for v in a]}})[
        "result"
    ]
    assert collinear["ratio"][0] == pytest.approx(1.0, abs=1e-6)


def test_m20_pca_loadings_sign_convention():
    a = [float(i) for i in range(N)]
    data = {"series": {"A": a, "B": [2.0 * v for v in a], "C": [-1.5 * v for v in a]}}
    res = run("M20", data)["result"]
    pc1 = res["loadings"][0]
    assert set(pc1) == {"A", "B", "C"}
    assert pc1["A"] * pc1["B"] > 0  # 同向
    assert pc1["A"] * pc1["C"] < 0  # 反向
    assert max(pc1.values(), key=abs) > 0  # 最大绝对值载荷为正
    assert res["explained"][0] == pytest.approx(1.0, abs=1e-6)
    assert len(res["loadings"]) == res["k"] == 3


def test_m21_hierarchical_recovers_three_groups():
    res = run("M21", _panel_three_groups(), k=3)["result"]
    labels = res["labels"]
    assert res["n_clusters"] == 3
    assert labels["g0_0"] == labels["g0_1"]
    assert labels["g0_0"] != labels["g1_0"]
    assert len(set(labels.values())) == 3
    assert res["names"] == list(labels)


def test_m22_kmeans_recovers_three_groups():
    res = run("M22", _panel_three_groups(), k=3)["result"]
    labels = res["labels"]
    assert res["n_clusters"] == 3
    assert labels["g2_0"] == labels["g2_1"]
    assert labels["g2_0"] != labels["g0_0"]
    assert res["inertia"] >= 0.0
    assert res["n"] == 140


# ---------- M26 ----------


def test_m26_factor_exposures():
    n = 180
    market = _gauss(n, 51)
    size = _gauss(n, 52)
    momentum = _gauss(n, 53)
    y = [
        1.5 * a - 0.5 * b + 0.8 * c + 0.01 * e
        for a, b, c, e in zip(market, size, momentum, _gauss(n, 54), strict=False)
    ]
    res = run(
        "M26", {"target": y, "factors": {"market": market, "size": size, "momentum": momentum}}
    )["result"]
    assert res["exposures"]["market"] == pytest.approx(1.5, abs=0.02)
    assert res["exposures"]["size"] == pytest.approx(-0.5, abs=0.02)
    assert res["exposures"]["momentum"] == pytest.approx(0.8, abs=0.02)
    assert res["factor_names"] == ["market", "size", "momentum"]
    assert res["r2"] > 0.99


# ---------- 确定性 ----------


def test_determinism_pca_and_clustering():
    data = _panel_three_groups()
    assert json.dumps(run("M19", data), sort_keys=True) == json.dumps(
        run("M19", data), sort_keys=True
    )
    assert json.dumps(run("M20", data), sort_keys=True) == json.dumps(
        run("M20", data), sort_keys=True
    )
    assert run("M21", data, k=3) == run("M21", data, k=3)
    assert json.dumps(run("M22", data, k=3), sort_keys=True) == json.dumps(
        run("M22", data, k=3), sort_keys=True
    )


def test_determinism_regression_paths():
    x = _gauss(160, 61)
    y = _gauss(160, 62)
    pair = {"x": x, "y": y}
    assert run("M14", pair) == run("M14", pair)
    assert json.dumps(run("M09", pair), sort_keys=True) == json.dumps(
        run("M09", pair), sort_keys=True
    )

    f1, f2 = _gauss(160, 63), _gauss(160, 64)
    data = {
        "target": [2.0 * a + 3.0 * b for a, b in zip(f1, f2, strict=False)],
        "factors": {"f1": f1, "f2": f2},
    }
    assert json.dumps(run("M15", data), sort_keys=True) == json.dumps(
        run("M15", data), sort_keys=True
    )
    assert run("M26", data) == run("M26", data)


# ---------- 内部工具 ----------


def _pearson(xs, ys):
    mx = sum(xs) / len(xs)
    my = sum(ys) / len(ys)
    sxy = sum((a - mx) * (b - my) for a, b in zip(xs, ys, strict=False))
    sxx = sum((a - mx) ** 2 for a in xs)
    syy = sum((b - my) ** 2 for b in ys)
    return sxy / math.sqrt(sxx * syy)
