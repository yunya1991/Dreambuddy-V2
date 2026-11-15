# -*- coding: utf-8 -*-
"""调研批次（S/D/T/F/H/B/M/R 全量注册）测试。

覆盖：descriptive.py（S/D）、timeseries.py（T/F）、inference.py（H/B/M/R）。
重点验证：目录完整性、门禁、与 numpy/手算口径一致、负例、确定性。
"""

import json
import math
import os
import sys

_MODULE_ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
if _MODULE_ROOT not in sys.path:
    sys.path.insert(0, _MODULE_ROOT)

from l1agg.methods import all_specs, get, run  # noqa: E402

# ---------------------------------------------------------------- 数据构造


def _linear(n=30):
    return [float(i) for i in range(n)]


def _growth(n=101, rate=0.001):
    return [100.0 * (1.0 + rate) ** i for i in range(n)]


def _ar1(n=256, phi=0.6, seed=7):
    import random

    rng = random.Random(seed)
    out, prev = [], 0.01
    for _ in range(n):
        prev = phi * prev + rng.gauss(0, 0.004)
        out.append(prev)
    return out


def _grouped(a, b):
    return {"state": ["a"] * len(a) + ["b"] * len(b), "target": list(a) + list(b)}


# ---------------------------------------------------------------- 目录


RESEARCH_IDS = [
    "S01",
    "S02",
    "S03",
    "S04",
    "S05",
    "S06",
    "S07",
    "S08",
    "S09",
    "S10",
    "S12",
    "S13",
    "S14",
    "S15",
    "S16",
    "S17",
    "S18",
    "S19",
    "S20",
    "S21",
    "S22",
    "S23",
    "S24",
    "S27",
    "S28",
    "D01",
    "D02",
    "D03",
    "D04",
    "D05",
    "D06",
    "D07",
    "D08",
    "D09",
    "D10",
    "D11",
    "D12",
    "D13",
    "D16",
    "D17",
    "D18",
    "D19",
    "D20",
    "D21",
    "D22",
    "D23",
    "D24",
    "T01",
    "T02",
    "T03",
    "T04",
    "T07",
    "T08",
    "T09",
    "T11",
    "T12",
    "T13",
    "T14",
    "T15",
    "T16",
    "T17",
    "T19",
    "T20",
    "T21",
    "T22",
    "T24",
    "T27",
    "T28",
    "F07",
    "F08",
    "F09",
    "F10",
    "F11",
    "F12",
    "F13",
    "F14",
    "F17",
    "F18",
    "F20",
    "F21",
    "H02",
    "H03",
    "H04",
    "H05",
    "H06",
    "H07",
    "H08",
    "H13",
    "H14",
    "H15",
    "H16",
    "H17",
    "H18",
    "B04",
    "B06",
    "B07",
    "B08",
    "B09",
    "B10",
    "B17",
    "B18",
    "M17",
    "M23",
    "R08",
    "R09",
    "R10",
    "R11",
    "R16",
    "R17",
]


def test_research_batch_registered():
    missing = [m for m in RESEARCH_IDS if not get(m).implemented]
    assert missing == [], f"未登记：{missing}"


def test_no_core_method_stays_placeholder():
    for mid in ("T05", "T06", "T10", "T18", "T23", "T25", "T26", "D14", "D15", "C11"):
        assert get(mid).implemented is True, mid
    assert [s.method_id for s in all_specs(scope="core") if not s.implemented] == []


def test_gate_blocks_short_series():
    for mid in ("S03", "D01", "B10", "T13", "H16"):
        out = run(mid, [])
        assert out["gate"] == "insufficient_samples", mid
        assert out["result"] is None


# ---------------------------------------------------------------- S 组


def test_s03_s08_s12_basic():
    data = [1.0, 2.0, 3.0, 4.0, 5.0]
    assert run("S03", data)["result"]["mean"] == 3.0
    assert run("S08", data)["result"]["var"] == 2.5
    assert run("S12", data)["result"]["iqr"] == 2.0


def test_s05_mode_picks_densest_bin():
    data = [0.0] * 8 + [10.0] * 2
    out = run("S05", data, k=10)["result"]
    assert out["count"] == 8
    assert out["mode"] < 1.0


def test_s14_ci_contains_mean():
    out = run("S14", _linear(30))["result"]
    assert out["ci_low"] < out["mean"] < out["ci_high"]
    assert out["n"] == 30


def test_s18_cum_price_and_returns():
    prices = [100.0, 110.0, 121.0]
    assert abs(run("S18", prices)["result"]["cum"] - 0.21) < 1e-6
    rets = [0.10, 0.10]
    assert abs(run("S18", rets, is_returns=True)["result"]["cum"] - 0.21) < 1e-6


def test_s19_cagr_matches_formula():
    prices = _growth(101, 0.001)
    out = run("S19", prices, days=100)["result"]
    expected = (prices[-1] / prices[0]) ** (365.0 / 100.0) - 1.0
    assert abs(out["cagr"] - expected) < 1e-5


def test_s20_rolling_mean_leading_none():
    out = run("S20", [1.0, 2.0, 3.0, 4.0], k=2)["result"]
    assert out["series"][:1] == [None]
    assert out["series"][1:] == [1.5, 2.5, 3.5]


def test_s24_s28_rank_and_direction():
    assert run("S24", [5.0, 3.0, 9.0])["result"]["rank"] == 1
    assert run("S28", _linear(40), k=20)["result"]["direction"] == "up"
    assert run("S28", [10.0, 9.0, 8.0, 7.0])["result"]["direction"] == "down"


# ---------------------------------------------------------------- D 组


def test_d01_d03_moments():
    data = [1.0, 2.0, 3.0, 4.0, 5.0]
    assert abs(run("D01", data)["result"]["skew"]) < 1e-9
    assert run("D03", data)["result"]["mad"] == 1.0


def test_d07_d08_outlier_flags():
    data = [1.0, 2.0, 3.0, 4.0, 5.0, 100.0]
    out_iqr = run("D07", data)["result"]
    assert out_iqr["n_outliers"] == 1
    assert out_iqr["flags"][-1] is True
    out_mad = run("D08", data)["result"]
    assert out_mad["n_outliers"] >= 1


def test_d13_jarque_bera_range():
    out = run("D13", _linear(60))["result"]
    assert 0.0 <= out["p"] <= 1.0
    assert out["jb"] >= 0.0


def test_d16_hill_on_positive_tail():
    data = [float(2 ** (i / 4)) for i in range(40)]
    out = run("D16", data, k=8)["result"]
    assert out["alpha"] is not None and out["k"] == 8


def test_d17_d18_tail_risk_positive_loss():
    rets = [-0.05 + 0.001 * i for i in range(100)]
    var = run("D17", rets)["result"]["var"]
    cvar = run("D18", rets)["result"]["cvar"]
    assert var > 0 and cvar >= var


def test_d20_d21_drawdown():
    prices = [100.0, 120.0, 90.0, 110.0]
    assert run("D20", prices)["result"]["mdd"] == 0.25
    out = run("D21", prices)["result"]
    assert out["duration_days"] == 1 and out["recovered"] is False
    recovered = run("D21", [100.0, 120.0, 90.0, 130.0])["result"]
    assert recovered["recovered"] is True and recovered["recovery_days"] == 1


def test_d22_d23_d24_ratios():
    rets = [0.02, -0.01, 0.03, -0.02, 0.01, -0.03] * 2
    assert run("D22", rets)["result"]["ratio"] is not None
    assert run("D23", rets)["result"]["pl_ratio"] is not None
    assert run("D24", rets)["result"]["win_rate"] == 0.5


# ---------------------------------------------------------------- T 组


def test_t01_alternating_acf_negative():
    out = run("T01", [1.0, 2.0] * 20, max_lag=3)["result"]
    assert out["acf"][0] < -0.9


def test_t02_pacf_length():
    out = run("T02", _ar1(120), max_lag=5)["result"]
    assert len(out["pacf"]) == 5
    assert all(v is None for v in out["pacf"]) is False


def test_t03_t04_lead_lag():
    x = [float(i % 7) for i in range(60)]
    y = [0.0, 0.0] + x[:-2]  # x 领先 y 两步
    data = {"x": x, "y": y}
    out = run("T04", data, max_lag=6)["result"]
    assert out["lag"] == 2
    assert out["ccf"] > 0.9


def test_t07_ljung_box_detects_alternation():
    out = run("T07", [1.0, 2.0] * 30, max_lag=5)["result"]
    assert out["q"] > 10 and out["p"] < 0.05


def test_t08_t09_trend_linear():
    prices = [100.0 * math.exp(0.001 * i) for i in range(60)]
    out = run("T08", prices)["result"]
    assert abs(out["slope_per_day"] - 0.001) < 1e-6
    assert out["r2"] > 0.999
    sig = run("T09", prices)["result"]
    assert sig["hac_corrected"] is False
    assert sig["t"] is not None


def test_t13_hurst_persistent_series():
    out = run("T13", _ar1(256))["result"]
    assert out["h"] is not None and 0.2 < out["h"] < 1.0


def test_t14_variance_ratio_trending():
    out = run("T14", _ar1(256), q=5)["result"]
    assert out["vr"] is not None and out["vr"] > 1.0


def test_t20_t21_halflife_ar1():
    out = run("T20", _ar1(256))["result"]
    assert 0.3 < out["phi"] < 0.9
    assert 0.5 < out["halflife_days"] < 3.0
    mr = run("T21", _ar1(256))["result"]
    assert mr["regime"] == "mean_revert"


def test_t22_cusum_finds_shift():
    data = [0.0] * 40 + [5.0] * 40
    out = run("T22", data, threshold=2.0)["result"]
    assert len(out["breakpoints"]) >= 1


def test_t27_t28_complexity_measures():
    fd = run("T27", _ar1(128))["result"]
    assert fd["fd"] is not None and 0.5 < fd["fd"] < 2.0
    se = run("T28", _ar1(60))["result"]
    assert se["sampen"] is not None and se["sampen"] > 0


# ---------------------------------------------------------------- F 组


def test_f07_f08_risk_adjusted_ratios():
    prices = [100.0 + 5.0 * math.sin(i / 3.0) + 0.1 * i for i in range(120)]
    assert run("F07", prices)["result"]["sortino"] is not None
    assert run("F08", prices)["result"]["calmar"] is not None


def test_f09_f10_match_drawdown():
    prices = [100.0, 120.0, 90.0, 110.0]
    assert run("F09", prices)["result"]["mdd"] == 0.25
    assert run("F10", prices)["result"]["recovered"] is False
    assert run("F10", [100.0, 120.0, 90.0, 130.0])["result"]["recovery_days"] == 1


def test_f12_f13_return_acf():
    prices = _growth(60, 0.001)
    assert len(run("F12", prices, max_lag=3)["result"]["acf"]) == 3
    assert len(run("F13", prices, max_lag=3)["result"]["acf"]) == 3


def test_f17_reversal_ratio():
    prices = [100.0]
    for i in range(10):
        prices.append(prices[-1] * (1.1 if i % 2 == 0 else 0.9))
    out = run("F17", prices)["result"]
    assert out["p_down_given_up"] == 1.0
    assert out["p_up_given_down"] == 1.0


def test_f18_runs_alternating():
    out = run("F18", [0.01, -0.01] * 10)["result"]
    assert out["max_run"] == 1 and out["n_runs"] == 20


def test_f20_f21_abnormal_returns():
    rets = [0.01] * 40
    assert all(abs(v) < 1e-9 for v in run("F20", rets)["result"]["ar"])
    assert abs(run("F21", rets, window=5)["result"]["car"]) < 1e-9


# ---------------------------------------------------------------- H 组


def test_h02_h03_h17_two_group_stats():
    a = [1.0 + 0.1 * i for i in range(12)]
    b = [2.0 + 0.1 * i for i in range(12)]
    data = _grouped(a, b)
    t2 = run("H02", data)["result"]
    assert abs(t2["diff"] + 1.0) < 1e-6
    assert t2["df"] == 22
    assert run("H03", data)["result"]["p"] is not None
    d = run("H17", data)["result"]
    assert d["d"] < 0


def test_h04_mann_whitney_separated():
    data = _grouped([float(i) for i in range(12)], [float(100 + i) for i in range(12)])
    out = run("H04", data)["result"]
    assert out["p"] < 0.01


def test_h05_wilcoxon_positive_shift():
    data = {
        "actual": [float(i) + 1.0 for i in range(15)],
        "expected": [float(i) for i in range(15)],
    }
    out = run("H05", data)["result"]
    assert out["w"] > 0 and out["p"] < 0.05


def test_h06_chi2_dependent_table():
    rows = ["a"] * 10 + ["b"] * 10
    cols = ["x"] * 10 + ["x"] * 1 + ["y"] * 9
    out = run("H06", {"row": rows, "col": cols})["result"]
    assert out["df"] == 1 and out["p"] < 0.01


def test_h07_h08_multi_group_difference():
    data = {
        "group": ["a"] * 10 + ["b"] * 10 + ["c"] * 10,
        "value": [1.0 + 0.01 * i for i in range(10)]
        + [5.0 + 0.01 * i for i in range(10)]
        + [9.0 + 0.01 * i for i in range(10)],
    }
    assert run("H07", data)["result"]["p"] < 0.01
    assert run("H08", data)["result"]["p"] < 0.01


def test_h13_bonferroni():
    out = run("H13", {"p": [0.01, 0.02, 0.03]})["result"]
    assert out["p_adj"] == [0.03, 0.06, 0.09]
    assert out["m"] == 3


def test_h14_bh_fdr_monotone():
    out = run("H14", {"p": [0.001, 0.02, 0.2, 0.5]})["result"]
    assert out["q"] == sorted(out["q"])
    assert out["significant"][0] is True


def test_h15_permutation_and_determinism():
    data = _grouped([float(i) for i in range(20)], [float(10 + i) for i in range(20)])
    a = run("H15", data, trials=100)
    b = run("H15", data, trials=100)
    assert json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True)
    assert a["result"]["p_perm"] <= 0.05


def test_h16_bootstrap_contains_mean():
    xs = _linear(50)
    out = run("H16", xs, trials=300)["result"]
    assert out["ci_low"] <= out["mean"] <= out["ci_high"]


def test_h18_power_increases_with_n():
    small = run("H18", _linear(20), d=0.5)["result"]["power"]
    large = run("H18", _linear(200), d=0.5)["result"]["power"]
    assert large > small


# ---------------------------------------------------------------- B 组


def test_b04_discretize():
    out = run("B04", [0.1, 0.6, 0.9], threshold=0.5)["result"]
    assert out["states"] == ["low", "high", "high"]
    assert out["counts"] == {"high": 2, "low": 1}


def test_b06_crosstab_counts():
    out = run("B06", {"row": ["a", "a", "b"], "col": ["x", "y", "x"]})["result"]
    assert out["rows"] == ["a", "b"]
    assert out["table"]["a"]["x"] == 1 and out["table"]["b"]["x"] == 1


def test_b07_b08_b09_markov():
    labels = ["a", "b"] * 10
    tm = run("B07", labels)["result"]
    assert tm["states"] == ["a", "b"]
    assert tm["matrix"][0][1] == 1.0
    st = run("B08", labels)["result"]
    assert abs(sum(st["stationary"]) - 1.0) < 1e-6
    dwell = run("B09", labels)["result"]
    assert dwell["dwell"] == [1.0, 1.0]


def test_b10_requires_250_samples():
    small = {"state": ["s"] * 40 + ["t"] * 40, "target": [float(i) for i in range(80)]}
    assert run("B10", small)["gate"] == "insufficient_samples"
    big = {
        "state": ["s"] * 130 + ["t"] * 130,
        "target": [float(i) for i in range(130)] + [float(i) * 2 for i in range(130)],
    }
    out = run("B10", big)["result"]
    assert out["states"] == ["s", "t"]
    assert out["percentiles"]["t"]["p50"] == 129.0


def test_b17_b18_counts():
    co = run("B17", {"x": ["yes", "no", "yes"], "y": ["true", "true", "false"]})["result"]
    assert co["count"] == 1 and co["total"] == 3
    freq = run("B18", ["a", "b", "a"])["result"]
    assert freq["freq"] == {"a": 2, "b": 1}


# ---------------------------------------------------------------- M 组


def test_m17_beta_recovers_slope():
    xs = [0.01 * (i % 5) for i in range(40)]
    ys = [2.0 * v for v in xs]
    out = run("M17", {"x": xs, "y": ys})["result"]
    assert abs(out["beta"] - 2.0) < 1e-6
    assert out["r2"] > 0.999


def test_m23_comovement_identical():
    xs = [0.01, -0.02, 0.03, -0.01, 0.02] * 2
    out = run("M23", {"x": xs, "y": xs})["result"]
    assert out["ratio"] == 1.0


# ---------------------------------------------------------------- R 组


def test_r08_monotonic_phrase():
    data = {"factor": [float(i) for i in range(300)], "target": [0.001 * i for i in range(300)]}
    out = run("R08", data, k=5)["result"]
    assert out["monotonic"] == "increasing"
    assert "越好" in out["phrase"]


def test_r09_count_phrase():
    out = run("R09", [0.01, -0.01, 0.02], label="CPI 超预期")["result"]
    assert out["up_n"] == 2 and out["down_n"] == 1
    assert "上涨 2 次" in out["phrase"]


def test_r10_cooccurrence_phrase():
    out = run("R10", {"x": ["yes", "yes", "no"], "y": ["true", "false", "true"]})["result"]
    assert out["count"] == 1
    assert "占比" in out["phrase"]


def test_r11_drawdown_profile():
    out = run("R11", [100, 120, 90, 110, 100, 121, 95, 125])["result"]
    assert out["mdd"] == 0.25
    assert out["recoveries"] == 2
    assert "最大回撤" in out["phrase"]


def test_r16_comovement_phrase():
    xs = [0.01, -0.02, 0.03] * 4
    out = run("R16", {"x": xs, "y": xs})["result"]
    assert out["ratio"] == 1.0 and "同涨同跌" in out["phrase"]


def test_r17_level_compare():
    out = run("R17", [100.0, 110.0, 120.0])["result"]
    assert out["current"] == 120.0 and out["base"] == 100.0
    assert out["percentile"] == 100.0
    assert "+20.00%" in out["phrase"]


# ---------------------------------------------------------------- 确定性


def test_all_new_methods_deterministic():
    cases = {
        "S03": (_linear(20), {}),
        "D13": (_linear(60), {}),
        "T01": ([1.0, 2.0] * 20, {"max_lag": 3}),
        "T07": ([1.0, 2.0] * 20, {"max_lag": 3}),
        "T28": (_ar1(40), {}),
        "H16": (_linear(30), {"trials": 100}),
        "B08": (["a", "b"] * 10, {}),
        "R11": ([100, 120, 90, 110], {}),
    }
    for mid, (data, params) in cases.items():
        a = run(mid, data, **params)
        b = run(mid, data, **params)
        assert json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True), mid
