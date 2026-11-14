# -*- coding: utf-8 -*-
"""调研族 P 组（P01–P14 风险与组合描述）+ Q 组（Q01–Q16 研究与检验协议）测试。

覆盖：30 条方法逐条真实数值/性质断言、确定性（含固定 seed 的随机过程）、
空输入门禁、以及「P/Q 全部 implemented」的目录断言。
P 组数据契约：`{"returns": {sym: [...]}}`（`series` 同步提供仅为满足 run 的样本计数）。
"""

import json
import math
import os
import sys

import numpy as np

_MODULE_ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
if _MODULE_ROOT not in sys.path:
    sys.path.insert(0, _MODULE_ROOT)

import l1agg.methods.research_pq  # noqa: E402,F401  # 触发 P/Q 30 条登记
from l1agg.methods import get, run  # noqa: E402
from l1agg.methods.research import specs_of  # noqa: E402

# ---------------------------------------------------------------- 辅助


def _rets(n=150, d=3, seed=3, vol=0.01):
    """面板日收益：等长、独立同分布高斯（固定 seed）。"""
    rng = np.random.default_rng(seed)
    m = rng.normal(0.0, vol, size=(n, d))
    return {f"A{i}": [float(v) for v in m[:, i]] for i in range(d)}


def _panel(rets, **extra):
    payload = {"returns": rets, "series": rets}
    payload.update(extra)
    return payload


def _qf(n=300, seed=5, beta=1.0, noise=0.3):
    """因子 / 前瞻收益对：y = beta·x + noise。"""
    rng = np.random.default_rng(seed)
    x = rng.normal(size=n)
    y = beta * x + noise * rng.normal(size=n)
    return list(x), list(y)


def _call(mid, data, **params):
    """执行并校验：门禁通过 + 返回键与 output_schema 完全一致。"""
    out = run(mid, data, **params)
    assert out["gate"] == "ok", (mid, out["gate"])
    spec = get(mid)
    assert set(out["result"]) == set(spec.output_schema), (mid, sorted(out["result"]))
    return out["result"]


# ---------------------------------------------------------------- P 组


def test_p01_realized_vol():
    const = {"A": [0.01] * 80, "B": [0.02] * 80}
    out = _call("P01", _panel(const))
    assert out["vol"] == {"A": 0.0, "B": 0.0}
    assert out["window"] == 20 and out["n"] == 80
    noisy = _call("P01", _panel(_rets()))
    assert all(v > 0 for v in noisy["vol"].values())


def test_p02_vol_target_scale():
    out = _call("P02", _panel(_rets()), target_vol=0.15)
    for sym, realized in out["realized"].items():
        assert abs(out["scale"][sym] * realized - 0.15) < 5e-4


def test_p03_inverse_vol_weights():
    data = {"A": [0.01, -0.01] * 40, "B": [0.005, -0.005] * 40}
    out = _call("P03", _panel(data))
    assert out["vols"]["A"] > out["vols"]["B"]
    assert out["weights"]["A"] < out["weights"]["B"]
    assert abs(sum(out["weights"].values()) - 1.0) < 1e-6


def test_p04_erc_weights_equal_risk():
    out = _call("P04", _panel(_rets(n=250)))
    w = list(out["weights"].values())
    rc = list(out["risk_contrib"].values())
    assert abs(sum(w) - 1.0) < 1e-4
    assert max(w) - min(w) < 0.05
    assert max(rc) - min(rc) < 1e-5  # 等风险贡献收敛判据
    assert 0 < out["iterations"] <= 500


def test_p05_risk_contrib_sums_to_vol():
    out = _call("P05", _panel(_rets()))
    assert out["total_risk"] > 0
    assert abs(sum(out["risk_contrib"].values()) - out["total_risk"]) < 1e-4
    assert abs(sum(out["share"].values()) - 1.0) < 1e-4


def test_p06_ledoit_wolf_shrinkage():
    out = _call("P06", _panel(_rets()))
    cov = np.asarray(out["cov"], dtype=float)
    assert 0.0 <= out["delta"] <= 1.0
    assert out["backend"] in ("sklearn", "analytic")
    assert np.allclose(cov, cov.T, atol=1e-9)
    assert np.all(np.diag(cov) > 0)


def test_p07_ewma_covariance():
    out = _call("P07", _panel(_rets()), lam=0.97)
    cov = np.asarray(out["cov"], dtype=float)
    assert out["lam"] == 0.97
    assert all(v > 0 for v in out["vol"].values())
    assert np.allclose(cov, cov.T, atol=1e-9)


def test_p08_pca_ratio_descending():
    out = _call("P08", _panel(_rets(n=200)), k=2)
    assert out["k"] == 2 and len(out["ratio"]) == 2
    assert out["ratio"][0] >= out["ratio"][1]
    assert 0.0 < sum(out["ratio"]) <= 1.0
    for row in out["loadings"]:
        assert abs(sum(v * v for v in row) - 1.0) < 1e-5


def test_p09_param_var():
    out = _call("P09", _panel(_rets()))
    assert out["sigma"] > 0
    assert abs(out["var"] - out["z"] * out["sigma"]) < 1e-5


def test_p10_historical_cvar():
    out = _call("P10", _panel(_rets()))
    assert out["quantile"] == 0.05
    assert out["cvar"] >= out["var_hist"] - 1e-9
    assert out["cvar"] > 0


def test_p11_underwater_curve():
    up = _call("P11", _panel({"A": [0.01] * 70}))
    assert up["max_drawdown"]["A"] == 0.0
    data = _panel({"A": [0.05, -0.10, 0.02] * 30})
    out = _call("P11", data)
    assert out["max_drawdown"]["A"] > 0
    assert max(out["underwater"]["A"]) == out["max_drawdown"]["A"]


def test_p12_brinson_decomposition():
    rets = _rets(n=150, d=4, seed=8)
    data = _panel(
        rets,
        sector={"A0": "tech", "A1": "tech", "A2": "bond", "A3": "bond"},
        w={"A0": 0.45, "A1": 0.15, "A2": 0.2, "A3": 0.2},
        wb={"A0": 0.25, "A1": 0.25, "A2": 0.25, "A3": 0.25},
    )
    out = _call("P12", data)
    total = out["allocation"] + out["selection"] + out["interaction"]
    assert abs(total - out["active_return"]) < 1e-5
    assert abs(out["active_return"]) > 0


def test_p13_tail_correlation():
    out = _call("P13", _panel(_rets(n=200)))
    assert 0 < out["n_down"] < out["n"]
    assert len(out["rho_down"]) == 3
    for v in out["rho_down"].values():
        assert -1.0 <= v <= 1.0
    for v in out["rho_full"].values():
        assert -1.0 <= v <= 1.0


def test_p14_correlation_stability():
    rng = np.random.default_rng(13)
    common = rng.normal(0.0, 0.01, 200)
    rets = {f"A{i}": list(common + rng.normal(0.0, 0.004, 200)) for i in range(3)}
    out = _call("P14", _panel(rets), window=60)
    assert out["window"] == 60
    assert out["mean_rho"] > 0.3
    assert out["std_rho"] > 0
    assert all(v is not None for v in out["stability"].values())


# ---------------------------------------------------------------- Q 组


def test_q01_ic_and_rank_ic():
    x, y = _qf()
    out = _call("Q01", {"factor": x, "forward": y})
    assert -1.0 <= out["ic"] <= 1.0
    assert out["ic"] > 0.8 and out["n"] == 300
    same = _call("Q01", {"factor": x, "forward": x})
    assert same["ic"] == 1.0 and same["rank_ic"] == 1.0


def test_q02_icir():
    x, y = _qf()
    out = _call("Q02", {"factor": x, "forward": y}, window=20)
    assert out["icir"] > 0
    assert out["n_periods"] == 15
    assert out["ic_std"] > 0 and out["ic_mean"] > 0


def test_q03_ic_decay_table():
    rng = np.random.default_rng(21)
    f = rng.normal(size=300)
    r = np.zeros(300)
    r[1:] = f[:-1] * 0.01  # r[t+1] = 0.01·factor[t] → h=1 时 IC=1
    out = _call("Q03", {"factor": list(f), "returns": list(r)})
    assert out["horizons"] == [1, 3, 5, 10, 20]
    assert out["ic_by_h"]["1"] > 0.5
    assert out["ic_by_h"]["1"] > out["ic_by_h"]["20"]


def test_q04_quantile_monotonicity():
    x, y = _qf(noise=0.2)
    out = _call("Q04", {"factor": x, "forward": y})
    assert out["monotonic"] == "increasing"
    assert out["rho"] > 0.9
    assert out["p"] < 0.05
    assert out["k"] == 5 and len(out["bucket_returns"]) == 5


def test_q05_fama_macbeth():
    rng = np.random.default_rng(9)
    X = rng.normal(size=(250, 5))
    Y = 1.5 * X + 0.3 * rng.normal(size=(250, 5))
    out = _call("Q05", {"factor": X.tolist(), "target": Y.tolist()})
    assert abs(out["lambda"] - 1.5) < 0.05
    assert out["t"] > 5
    assert out["n_periods"] == 250 and out["n_assets"] == 5


def test_q06_newey_west_t():
    rng = np.random.default_rng(31)
    s = 0.01 + 0.01 * rng.normal(size=300)
    out = _call("Q06", {"series": list(s)})
    assert out["t_nw"] > 2
    assert out["lag"] == int(math.floor(4.0 * (300 / 100.0) ** (2.0 / 9.0)))
    assert out["se"] > 0


def test_q07_deflated_sharpe():
    rng = np.random.default_rng(41)
    s = 0.002 + 0.01 * rng.normal(size=300)
    lo = _call("Q07", {"series": list(s)}, n_trials=2)
    hi = _call("Q07", {"series": list(s)}, n_trials=500)
    assert 0.0 <= hi["dsr"] <= 1.0
    assert hi["sr0"] > lo["sr0"]
    assert hi["dsr"] <= lo["dsr"]


def test_q08_subsample_robustness():
    x, y = _qf()
    out = _call("Q08", {"factor": x, "forward": y})
    assert out["robust"] is True
    assert abs(out["delta"]) < 0.2
    assert out["ic_first"] > 0.5 and out["ic_second"] > 0.5


def test_q09_parameter_perturbation():
    x, y = _qf()
    out = _call("Q09", {"factor": x, "forward": y})
    assert out["pass_ratio"] == 1.0
    assert out["windows"] == [10, 20, 60, 120]
    assert all(v > 0 for v in out["ic_by_window"].values())


def _event_series(n=400, seed=11, events=(150, 300), lift=0.02):
    rng = np.random.default_rng(seed)
    r = rng.normal(0.0, 0.01, n)
    for e in events:
        r[e - 5 : e + 11] += lift
    return r, list(events)


def test_q10_event_car():
    r, events = _event_series()
    out = _call("Q10", {"series": list(r)}, events=events)
    assert out["n"] == len(events)
    assert 0.2 < out["car"] < 0.45  # 0.02×16 ≈ 0.32 的植入效应
    assert out["est_window"] == [-120, -20]
    assert out["event_window"] == [-5, 10]


def test_q11_patell_bmp():
    r, events = _event_series()
    out = _call("Q11", {"series": list(r)}, events=events)
    assert out["n"] == len(events)
    assert out["z_patell"] > 2
    assert 0.0 <= out["p"] <= 1.0


def test_q12_bootstrap_ci():
    x, y = _qf()
    out = _call("Q12", {"factor": x, "forward": y})
    assert out["ci_low"] <= out["point"] <= out["ci_high"]
    assert out["b"] == 1000 and out["seed"] == 42
    assert out["n"] == 300


def test_q13_permutation_test():
    x, y = _qf()
    out = _call("Q13", {"factor": x, "forward": y}, n_perm=500)
    assert out["observed"] > 0.8
    assert out["p_perm"] < 0.02
    assert 0 < out["p_perm"] <= 1.0


def test_q14_multiple_comparison_bh():
    p = [0.00001, 0.008, 0.02, 0.04] + [0.2 + 0.003 * i for i in range(246)]
    assert len(p) == 250
    out = _call("Q14", {"p": p})
    assert out["m"] == 250
    assert all(q >= pp - 1e-9 for q, pp in zip(out["p_adj"], p, strict=False))  # BH: q_i ≥ p_i
    assert out["p_adj"] == sorted(out["p_adj"])  # 输入升序时 q 亦单调
    assert out["reject"][0] is True
    bonf = _call("Q14", {"p": p}, method="bonferroni")
    assert bonf["method"] == "bonferroni"
    assert abs(bonf["p_adj"][0] - 0.0025) < 1e-9


def test_q15_sample_sufficiency():
    short = _call("Q15", {"series": [0.0] * 250}, required=500)
    assert short["sufficient"] is False and short["ok"] is False
    assert "< required" in short["reason"]
    ok = _call("Q15", {"series": [0.0] * 250}, required=200)
    assert ok["sufficient"] is True and ok["n"] == 250


def test_q16_pit_check():
    avail = list(range(300))
    sig = list(range(300))
    out = _call("Q16", {"available": avail, "signal": sig})
    assert out["pass"] is True
    assert out["n_violations"] == 0 and out["n"] == 300
    bad_avail = list(range(300))
    bad_avail[10] = 1000
    bad = _call("Q16", {"available": bad_avail, "signal": sig})
    assert bad["pass"] is False
    assert bad["n_violations"] == 1 and bad["violations"] == [10]


# ---------------------------------------------------------------- 确定性 / 门禁 / 目录


def test_determinism_panel_methods():
    rets = _rets(n=200, seed=17, d=3)
    plain = _panel(rets)
    brinson = _panel(
        rets,
        sector={"A0": "tech", "A1": "tech", "A2": "bond"},
        w={"A0": 0.5, "A1": 0.2, "A2": 0.3},
        wb={"A0": 1 / 3, "A1": 1 / 3, "A2": 1 / 3},
    )
    cases = [("P04", plain, {}), ("P06", plain, {}), ("P08", plain, {"k": 2}), ("P12", brinson, {})]
    for mid, data, params in cases:
        a = run(mid, data, **params)
        b = run(mid, data, **params)
        assert json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True), mid


def test_determinism_seeded_methods():
    x, y = _qf(seed=23)
    cases = [("Q12", {"b": 200}), ("Q13", {"n_perm": 200})]
    for mid, params in cases:
        a = run(mid, {"factor": x, "forward": y}, **params)
        b = run(mid, {"factor": x, "forward": y}, **params)
        assert json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True), mid


def test_empty_input_gate():
    for mid in ("P01", "P04", "P12", "Q01", "Q14", "Q15"):
        out = run(mid, {})
        assert out["gate"] == "insufficient_samples", mid
        assert out["result"] is None, mid


def test_all_pq_methods_implemented():
    for group, expected in (("P", 14), ("Q", 16)):
        rows = specs_of(group)
        assert len(rows) == expected
        for row in rows:
            spec = get(row[0])
            assert spec.implemented is True, row[0]
            assert spec.func is not None, row[0]
            assert spec.output_schema, row[0]
            assert spec.name == row[1] and spec.min_n == row[4], row[0]
