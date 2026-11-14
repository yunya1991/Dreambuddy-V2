# -*- coding: utf-8 -*-
"""T/F/D 补齐批次测试：T05/T06/T10/T18/T23/T25/T26、F15/F16/F19/F22–F26、D14/D15。"""

import json
import math
import os
import random
import sys

import pytest

_MODULE_ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
if _MODULE_ROOT not in sys.path:
    sys.path.insert(0, _MODULE_ROOT)

import l1agg.methods.descriptive  # noqa: F401,E402  # 触发 D 登记
import l1agg.methods.timeseries  # noqa: F401,E402  # 触发 T/F 登记
from l1agg.methods import get, run  # noqa: E402

_T_IDS = ("T05", "T06", "T10", "T18", "T23", "T25", "T26")
_F_IDS = ("F15", "F16", "F19", "F22", "F23", "F24", "F25", "F26")
_D_IDS = ("D14", "D15")
_ALL_IDS = _T_IDS + _F_IDS + _D_IDS


def _white_noise(n=200, seed=7, sd=0.01):
    rng = random.Random(seed)
    return [rng.gauss(0.0, sd) for _ in range(n)]


def _random_walk(n=200, seed=7, sd=0.01, start=100.0):
    out = [start]
    for r in _white_noise(n, seed, sd):
        out.append(out[-1] * (1.0 + r))
    return out


def _sine(n=240, period=20, amp=5.0, drift=0.002):
    return [100.0 + amp * math.sin(2.0 * math.pi * i / period) + drift * i for i in range(n)]


def _garch_returns(n=600, seed=11, omega=2e-6, alpha=0.08, beta=0.90):
    rng = random.Random(seed)
    var = omega / (1.0 - alpha - beta)
    out = []
    for _ in range(n):
        r = rng.gauss(0.0, math.sqrt(var))
        out.append(r)
        var = omega + alpha * r * r + beta * var
    return out


def _event_prices(n=400, growth=1.01):
    return [100.0 * growth**i for i in range(n)]


def _events(n=400, step=10):
    return list(range(10, n, step))


# ---------------- 注册与契约 ----------------


def test_all_ids_implemented():
    for mid in _T_IDS + _F_IDS:
        spec = get(mid)
        assert spec.implemented is True, mid
        assert spec.func is not None, mid
        assert spec.min_n > 0, mid
        assert spec.output_schema, mid
    for mid in _T_IDS:
        assert get(mid).group == "T", mid
    for mid in _F_IDS:
        assert get(mid).group == "F", mid
    for mid in _D_IDS:
        assert get(mid).group == "D", mid
        assert get(mid).layer == "D3", mid


def test_output_schema_matches_result_keys():
    cases = {
        "T05": (_white_noise(), {}),
        "T06": (_white_noise(), {}),
        "T10": (_sine(140), {"period": 7}),
        "T18": (_garch_returns(300), {}),
        "T23": ([0.0] * 60 + [10.0] * 140, {}),
        "T25": (_sine(), {}),
        "T26": (_sine(), {}),
        "F15": (
            {"x": [100.0 + i for i in range(40)], "y": [100.0 + 0.5 * i for i in range(40)]},
            {},
        ),
        "F16": ({"a": [100.0 + i for i in range(40)], "b": [100.0 + 2 * i for i in range(40)]}, {}),
        "F19": ({"prices": _event_prices(), "events": _events()}, {}),
        "F22": (["fomc"] * 40, {}),
        "F23": ({"prices": _event_prices(), "events": _events()}, {}),
        "F24": ([0.0001] * 40, {}),
        "F25": ({"futures": [110.0] * 40, "spot": [100.0] * 40}, {}),
        "F26": ({"a": list(range(80)), "b": list(range(80)), "c": list(range(80))}, {}),
        "D14": (_white_noise(120, seed=3), {}),
        "D15": ([random.Random(5).gauss(0.0, 1.0) for _ in range(120)], {}),
    }
    for mid, (data, params) in cases.items():
        out = run(mid, data, **params)
        assert out["gate"] == "ok", mid
        assert set(out["result"]) == set(get(mid).output_schema), mid


# ---------------- T 组 ----------------


def test_t05_adf_white_noise_vs_random_walk():
    wn = run("T05", _white_noise())["result"]
    rw = run("T05", _random_walk())["result"]
    # 白噪声拒绝单位根（ADF 的 H0 = 有单位根）
    assert wn["stat"] < 0 and wn["p"] < 0.05
    assert wn["stationary"] is True
    # 随机游走不应拒绝单位根
    assert rw["p"] > 0.10 and rw["stationary"] is False
    assert wn["n"] == 200 and wn["used_lag"] >= 1


def test_t06_kpss_white_noise_vs_random_walk():
    wn = run("T06", _white_noise())["result"]
    rw = run("T06", _random_walk())["result"]
    # KPSS 的 H0 = 平稳
    assert wn["p"] >= 0.05 and wn["stationary"] is True
    assert rw["p"] < 0.05 and rw["stationary"] is False
    assert wn["lags"] >= 1


def test_t10_stl_decomposition_lengths_and_reconstruction():
    xs = _sine(140, period=7, amp=10.0, drift=0.1)
    out = run("T10", xs, period=7)["result"]
    assert len(out["trend"]) == len(out["seasonal"]) == len(out["resid"]) == len(xs)
    err = max(
        abs(a - t - s - r)
        for a, t, s, r in zip(xs, out["trend"], out["seasonal"], out["resid"], strict=False)
    )
    assert err < 1e-4
    assert out["period"] == 7
    assert out["trend"][-1] - out["trend"][0] > 10.0  # 恢复上行漂移
    assert out["seasonal_strength"] > 0.5
    assert out["method"] in ("statsmodels_stl", "classical_fallback")


def test_t18_garch_fit_and_forecast():
    out = run("T18", _garch_returns(600))["result"]
    assert 0.0 < out["alpha"] < 0.5
    assert 0.0 < out["beta"] < 1.0
    assert 0.80 < out["persistence"] < 1.0
    assert out["omega"] >= 0.0
    assert out["forecast_vol"] > 0.0
    assert out["loglik"] is not None and math.isfinite(out["loglik"])
    assert out["method"] == "grid_qmle_variance_targeting"


def test_t23_pelt_detects_level_shift():
    xs = [0.0] * 60 + [10.0] * 140
    out = run("T23", xs)["result"]
    assert out["n_changepoints"] == 1
    assert abs(out["breakpoints"][0] - 60) <= 2


def test_t23_pelt_no_false_positive_on_constant():
    out = run("T23", [3.0] * 200)["result"]
    assert out["breakpoints"] == [] and out["n_changepoints"] == 0


def test_t25_fft_recovers_period():
    out = run("T25", _sine(240, period=20))["result"]
    assert out["period"] == pytest.approx(20.0, abs=0.5)
    assert out["freq_index"] == 12
    assert out["amplitude"] == pytest.approx(5.0, abs=0.2)


def test_t26_power_ratio_high_for_sine():
    out = run("T26", _sine(240, period=20))["result"]
    assert out["period"] == pytest.approx(20.0, abs=0.5)
    assert out["power_ratio"] > 0.90


# ---------------- F 组 ----------------


def test_f15_relative_strength():
    xs = [100.0 * 2 ** (i / 39) for i in range(40)]
    ys = [100.0 * 1.10 ** (i / 39) for i in range(40)]
    out = run("F15", {"x": xs, "y": ys})["result"]
    assert out["ratio"] == pytest.approx(2.0 / 1.10, rel=1e-4)
    assert out["rs"][0] == pytest.approx(1.0)
    assert out["asset_ret"] == pytest.approx(1.0, rel=1e-4)
    assert out["bench_ret"] == pytest.approx(0.10, rel=1e-3)


def test_f16_momentum_ranking_order():
    data = {
        "a": [100.0 + 10.0 * i for i in range(40)],
        "b": [100.0 + 20.0 * i for i in range(40)],
        "c": [200.0 - 2.0 * i for i in range(40)],
    }
    out = run("F16", data, k=20)["result"]
    assert [row["asset"] for row in out["ranking"]] == ["b", "a", "c"]
    assert [row["rank"] for row in out["ranking"]] == [1, 2, 3]
    assert out["ranking"][0]["ret"] == pytest.approx(880.0 / 480.0 - 1.0, abs=1e-6)
    assert out["n_assets"] == 3


def test_f19_event_window_car():
    out = run("F19", {"prices": _event_prices(), "events": _events()}, k=5)["result"]
    expected = 1.01**10 - 1.0
    assert out["n_events"] == len(_events())
    assert out["car"] == pytest.approx(expected, abs=1e-6)
    assert all(v == pytest.approx(expected, abs=1e-6) for v in out["cars"])


def test_f22_event_count():
    labels = ["cpi"] * 140 + ["fomc"] * 60
    out = run("F22", labels)["result"]
    assert out["event"] == "fomc"
    assert out["count"] == 60 and out["unique"] == 2 and out["total"] == 200


def test_f23_post_event_distribution():
    out = run("F23", {"prices": _event_prices(), "events": _events()}, k=5)["result"]
    expected = 1.01**5 - 1.0
    assert out["n_events"] == len(_events())
    assert out["mean"] == pytest.approx(expected, abs=1e-6)
    assert out["win_rate"] == 1.0
    assert all(v > 0 for v in out["dist"])


def test_f24_funding_apr():
    out = run("F24", [0.0001] * 50)["result"]
    assert out["apr"] == pytest.approx(0.0001 * 3 * 365, abs=1e-6)
    assert out["mean_rate"] == pytest.approx(0.0001)
    assert out["periods_per_day"] == 3


def test_f25_basis():
    out = run("F25", {"futures": [110.0] * 40, "spot": [100.0] * 40})["result"]
    assert out["basis"] == pytest.approx(0.1)
    assert out["mean_basis"] == pytest.approx(0.1)
    assert out["futures"] == 110.0 and out["spot"] == 100.0


def test_f26_crowding_score_at_max():
    data = {
        "funding": [float(i) for i in range(80)],
        "oi": [float(i) for i in range(80)],
        "basis": [float(i) for i in range(80)],
    }
    out = run("F26", data)["result"]
    assert out["score"] == pytest.approx(1.0)
    assert out["weights"] == [0.4, 0.3, 0.3]
    assert out["components"] == {"funding": 1.0, "oi": 1.0, "basis": 1.0}


# ---------------- D 组 ----------------


def test_d14_shapiro_normal_vs_exponential():
    rng = random.Random(13)
    normal = run("D14", [rng.gauss(0.0, 1.0) for _ in range(200)])["result"]
    skewed = run("D14", [rng.expovariate(1.0) for _ in range(200)])["result"]
    assert 0.0 < normal["w"] < 1.0
    assert normal["p"] > 0.05 and normal["normal"] is True
    assert skewed["p"] < 0.01 and skewed["normal"] is False


def test_d15_dist_fit_selects_by_aic():
    rng = random.Random(17)
    normal = run("D15", [rng.gauss(0.0, 1.0) for _ in range(300)])["result"]
    lognormal = run("D15", [math.exp(rng.gauss(0.0, 0.5)) for _ in range(300)])["result"]
    assert normal["best"] == "normal"
    assert set(normal["params"]) == {"mu", "sigma"}
    assert normal["aic"] <= normal["aic_t"]
    assert lognormal["best"] == "lognormal"
    assert set(lognormal["params"]) == {"mu_log", "sigma_log"}
    assert lognormal["aic"] <= lognormal["aic_normal"]
    assert lognormal["aic_t"] is not None


# ---------------- 确定性与门禁 ----------------


def test_timeseries_methods_deterministic():
    cases = {
        "T10": (_sine(140), {"period": 7}),
        "T18": (_garch_returns(300), {}),
        "T23": ([0.0] * 60 + [5.0] * 140, {}),
        "T25": (_sine(), {}),
        "T26": (_sine(), {}),
    }
    for mid, (data, params) in cases.items():
        first = json.dumps(run(mid, data, **params)["result"], sort_keys=True)
        second = json.dumps(run(mid, data, **params)["result"], sort_keys=True)
        assert first == second, mid


def test_event_and_fit_methods_deterministic():
    f16 = {"a": [100.0 + i for i in range(40)], "b": [100.0 + 2 * i for i in range(40)]}
    f26 = {"x": list(range(80)), "y": list(range(80)), "z": list(range(80))}
    rng = random.Random(23)
    sample = [rng.gauss(0.0, 1.0) for _ in range(120)]
    cases = {
        "F16": (f16, {}),
        "F26": (f26, {}),
        "D15": (sample, {}),
    }
    for mid, (data, params) in cases.items():
        first = json.dumps(run(mid, data, **params)["result"], sort_keys=True)
        second = json.dumps(run(mid, data, **params)["result"], sort_keys=True)
        assert first == second, mid


def test_empty_input_gate():
    for mid in _ALL_IDS:
        out = run(mid, [])
        assert out["gate"] == "insufficient_samples", mid
        assert out["result"] is None, mid
