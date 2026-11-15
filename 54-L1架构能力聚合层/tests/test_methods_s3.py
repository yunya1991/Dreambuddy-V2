# -*- coding: utf-8 -*-
"""S3 批（条件收益 / IC / 分组）测试：S11/S25/S26、F01–F06、B01–B03/B05/B11–B16、H01、R01/R02。"""

import json
import math
import os
import random
import sys

import pytest

_MODULE_ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
if _MODULE_ROOT not in sys.path:
    sys.path.insert(0, _MODULE_ROOT)

from l1agg.methods import get, run  # noqa: E402

DIST_N = 30
COND_N = 300


def _linear(n=DIST_N):
    return [float(i) for i in range(n)]


def _growth(n=DIST_N, rate=0.01):
    return [100.0 * (1.0 + rate) ** i for i in range(n)]


def _cond_pair(n=COND_N):
    return {"factor": [float(i) for i in range(n)], "target": [0.001 * i for i in range(n)]}


# ---------- 目录与门禁 ----------


def test_s3_batch_registered():
    ids = [
        "S11",
        "S25",
        "S26",
        "F01",
        "F02",
        "F03",
        "F04",
        "F05",
        "F06",
        "B01",
        "B02",
        "B03",
        "B05",
        "B11",
        "B12",
        "B13",
        "B14",
        "B15",
        "B16",
        "H01",
        "R01",
        "R02",
    ]
    for mid in ids:
        assert get(mid).implemented is True, mid


def test_cond_batch_gate_needs_250():
    short = {"factor": _linear(100), "target": _linear(100)}
    assert run("B13", short)["gate"] == "insufficient_samples"
    assert run("B13", _cond_pair())["gate"] == "ok"
    assert get("B13").min_n == 250


def test_dist_batch_gate_needs_30():
    assert run("S11", _linear(10))["gate"] == "insufficient_samples"
    assert run("F03", [1.0, 2.0])["gate"] == "ok"  # F03 只需 2 点


# ---------- S11 / S25 / S26 ----------


def test_s11_matches_numpy():
    np = pytest.importorskip("numpy")
    xs = [3.0, 1.0, 4.0, 1.0, 5.0, 9.0, 2.0, 6.0, 5.0, 3.0] * 3
    out = run("S11", xs)["result"]
    for q in (1, 25, 50, 90, 99):
        assert out[f"p{q}"] == pytest.approx(float(np.percentile(xs, q)), abs=1e-6)


def test_s25_percentile_pit():
    out = run("S25", _linear())["result"]
    assert out["value"] == 29.0
    assert out["percentile"] == 100.0
    assert out["n"] == 30


def test_s26_zscore_winsorized():
    out = run("S26", _linear())["result"]
    assert out["mean"] == pytest.approx(14.5)
    assert out["winsorized"] is True
    # 末点为最大值，z 必为正
    assert out["z"] > 0


def test_s26_zero_variance_returns_null():
    out = run("S26", [5.0] * 30)["result"]
    assert out["z"] is None


# ---------- F01–F06 ----------


def test_f01_f02_returns():
    prices = _growth()
    f01 = run("F01", prices)["result"]
    f02 = run("F02", prices)["result"]
    assert f01["mean"] == pytest.approx(0.01, abs=1e-9)
    assert f02["mean"] == pytest.approx(math.log(1.01), abs=1e-6)  # 输出保留 6 位
    assert f01["n"] == DIST_N


def test_f03_interval_return():
    out = run("F03", [100.0] * 15 + [200.0] * 15)["result"]
    assert out["ret"] == pytest.approx(1.0)


def test_f04_f05_annualized():
    prices = _growth(rate=0.001)
    f04 = run("F04", prices)["result"]
    f05 = run("F05", prices)["result"]
    assert f04["mean_daily"] == pytest.approx(0.001, abs=1e-9)
    assert f04["ann"] == pytest.approx(1.001**365 - 1.0, abs=1e-6)
    assert f05["vol"] == pytest.approx(0.0, abs=1e-6)


def test_f06_sharpe_null_when_zero_vol():
    assert run("F06", _growth(rate=0.1))["result"]["sharpe"] is None
    # 有波动时 sharpe 为有限数
    rng = random.Random(11)
    noisy = [100.0 * (1.0 + 0.01 + rng.gauss(0, 0.01)) ** i for i in range(60)]
    out = run("F06", noisy)["result"]
    assert out["sharpe"] is not None and out["ann_vol"] > 0


# ---------- B01–B03 ----------


def test_b01_equal_width_counts():
    out = run("B01", _linear(), k=10)["result"]
    assert len(out["edges"]) == 11
    assert sum(out["counts"]) == DIST_N
    assert out["counts"][0] == 3 and out["counts"][9] == 3


def test_b02_quantile_bins():
    out = run("B02", _linear(), k=5)["result"]
    assert out["counts"] == [6, 6, 6, 6, 6]
    assert out["bucket"] == 4


def test_b03_threshold_levels():
    out = run("B03", [float(i) for i in range(101)], thresholds=(25, 50, 75))["result"]
    assert out["level"] == 3 and out["label"] == ">=75"
    assert out["counts"] == [25, 25, 25, 26]


# ---------- B05 / B11–B16 ----------


def _state_pair(n=COND_N):
    return {
        "state": [str(i % 2) for i in range(n)],
        "target": [0.01 if i % 2 else -0.01 for i in range(n)],
    }


def test_b05_conditional_table():
    out = run("B05", _state_pair())["result"]
    table = {row["state"]: row for row in out["table"]}
    assert table["1"]["mean"] == pytest.approx(0.01)
    assert table["0"]["mean"] == pytest.approx(-0.01)
    assert table["1"]["win_rate"] == 1.0


def test_b16_group_stats_and_spread():
    out = run("B16", _cond_pair(), k=5)["result"]
    assert len(out["table"]) == 5
    assert sum(row["n"] for row in out["table"]) == COND_N
    assert out["spread"] == pytest.approx(0.24, abs=1e-6)


def test_b11_monotonic_increasing():
    out = run("B11", _cond_pair(), k=5)["result"]
    assert out["monotonic"] == "increasing"
    assert out["rho_bin"] == pytest.approx(1.0)
    assert out["n"] == COND_N


def test_b11_skips_empty_buckets_with_tied_factor():
    """真实数据并列值导致分位边界塌缩时，空桶（mean=None）不得触发 float(None)。"""
    half = COND_N // 2
    pair = {
        "factor": [0.0] * half + [1.0] * (COND_N - half),
        "target": [0.01] * half + [0.02] * (COND_N - half),
    }
    out = run("B11", pair, k=5)["result"]
    assert out["monotonic"] == "increasing"
    assert out["bin_means"] == [0.01, 0.02]
    assert out["n"] == COND_N


def test_b11_rejects_single_bucket():
    pair = {"factor": [0.0] * COND_N, "target": [0.01] * COND_N}
    with pytest.raises(ValueError):
        run("B11", pair, k=5)


def test_b12_gradient_matches_b16():
    b12 = run("B12", _cond_pair(), k=5)["result"]
    b16 = run("B16", _cond_pair(), k=5)["result"]
    assert b12["spread"] == b16["spread"]
    assert b12["spread_pp"] == pytest.approx(24.0, abs=1e-6)


def test_b13_b14_ic():
    perfect = {"factor": _linear(COND_N), "target": _linear(COND_N)}
    assert run("B13", perfect)["result"]["ic"] == pytest.approx(1.0)
    assert run("B14", perfect)["result"]["rank_ic"] == pytest.approx(1.0)
    # 单调非线性：Pearson < Spearman
    cubic = {"factor": _linear(COND_N), "target": [float(i) ** 3 for i in range(COND_N)]}
    assert run("B13", cubic)["result"]["ic"] < run("B14", cubic)["result"]["rank_ic"]


def test_b13_null_random_not_significant():
    rng = random.Random(7)
    data = {
        "factor": [rng.gauss(0, 1) for _ in range(COND_N)],
        "target": [rng.gauss(0, 1) for _ in range(COND_N)],
    }
    res = run("B13", data)["result"]
    assert abs(res["ic"]) < 0.15
    assert res["p"] > 0.01


def test_b15_ic_decay_reuses_frozen_impl():
    prices = [100.0 * math.exp(0.001 * i + 0.05 * math.sin(i / 5.0)) for i in range(400)]
    out = run("B15", prices, lookback=20, horizons=(1, 5, 20))["result"]
    assert out["lookback"] == 20
    assert out["n"] == 400
    assert [item["h"] for item in out["items"]] == [1, 5, 20]
    assert all("ric_nonoverlap" in item for item in out["items"])


# ---------- H01 ----------


def test_h01_one_sample_t():
    out = run("H01", [0.01, 0.02] * 15)["result"]
    assert out["mean"] == pytest.approx(0.015)
    assert out["p"] < 0.001
    assert out["is_significant"] is True


# ---------- R01 / R02 ----------


def test_r01_phrase_uses_fixed_template():
    out = run("R01", _state_pair(), h=1, state="1")["result"]
    assert "历史" in out["phrase"] and "上涨" in out["phrase"]
    assert out["state"] == "1"
    assert "+1.00%" in out["phrase"] and "n=" in out["phrase"]


def test_r02_percentile_forward():
    data = {
        "indicator": [float(i) for i in range(COND_N)],
        "price": [100.0 * math.exp(0.0005 * i) for i in range(COND_N)],
    }
    out = run("R02", data, buckets=10, horizons=(1, 5))["result"]
    assert out["current_percentile"] == 100.0
    assert out["bucket"] == 9
    assert out["pit"] is False
    assert [item["h"] for item in out["by_horizon"]] == [1, 5]
    assert "样本内回顾" in out["phrase"] and "含未来函数" in out["phrase"]
    # 价格单调上涨 → 同桶前瞻收益全为正
    assert all(item["n"] > 0 and item["mean"] > 0 for item in out["by_horizon"])
    assert all(item["effective_n"] == item["n"] for item in out["by_horizon"])
    assert out["by_horizon"][0]["nonoverlap_n"] == out["by_horizon"][0]["effective_n"]
    assert out["by_horizon"][1]["nonoverlap_n"] < out["by_horizon"][1]["effective_n"]


def _r02_pit_data(n=COND_N):
    return {
        "indicator": [float(i % 10) for i in range(n)],
        "price": [100.0 * math.exp(0.0005 * i) for i in range(n)],
        "timestamps": list(range(n)),
        "align_method": "daily_last+ffill",
    }


def test_r02_pit_discloses_rolling_conditional_samples():
    out = run("R02", _r02_pit_data(), pit=True, window=30, buckets=2, horizons=(1, 5))["result"]
    assert out["pit"] is True
    assert out["as_of"] == COND_N - 1
    assert out["window"] == 30
    assert out["align_method"] == "daily_last+ffill"
    assert out["current_percentile"] == 100.0
    assert out["bucket"] == 1
    for item in out["by_horizon"]:
        assert item["pit"] is True
        assert item["as_of"] == COND_N - 1
        assert item["window"] == 30
        assert item["align_method"] == "daily_last+ffill"
        assert item["effective_n"] == item["n"] > 0
        assert 0 < item["nonoverlap_n"] <= item["effective_n"]
        assert item["mean"] > 0
    assert out["by_horizon"][0]["nonoverlap_n"] == out["by_horizon"][0]["effective_n"]
    assert out["by_horizon"][1]["nonoverlap_n"] < out["by_horizon"][1]["effective_n"]
    assert out["by_horizon"][1]["t"] is None
    assert out["by_horizon"][1]["p"] is None
    assert "按当时可见数据" in out["phrase"]


def test_r02_pit_discloses_every_bucket_and_return_interval():
    out = run("R02", _r02_pit_data(), pit=True, window=30, buckets=2, horizons=(1,))["result"]
    current = out["by_horizon"][0]
    assert current["p10"] <= current["median"] <= current["p90"]
    assert [row["bucket"] for row in current["by_bucket"]] == [0, 1]
    for row in current["by_bucket"]:
        assert row["effective_n"] == row["n"] > 0
        assert row["nonoverlap_n"] == row["effective_n"]
        assert row["p10"] <= row["median"] <= row["p90"]


def test_r02_pit_future_rows_do_not_change_as_of_result():
    full = _r02_pit_data()
    prefix = {
        key: (value[:270] if isinstance(value, list) else value) for key, value in full.items()
    }
    params = {"pit": True, "window": 40, "buckets": 4, "horizons": (1, 5), "as_of": 269}
    expected = run("R02", prefix, **params)["result"]
    full["indicator"][270:] = [1e9] * (COND_N - 270)
    full["price"][270:] = [1e9] * (COND_N - 270)
    actual = run("R02", full, **params)["result"]
    assert actual == expected


def test_r02_pit_release_ts_controls_visibility():
    data = _r02_pit_data()
    data["indicator"] = [0.0] * COND_N
    data["release_ts"] = list(range(COND_N))
    for i in range(100, 130):
        data["indicator"][i] = 1000.0
        data["release_ts"][i] = 150

    before = run("R02", data, pit=True, window=60, buckets=2, horizons=(1,), as_of=120)["result"]
    after = run("R02", data, pit=True, window=60, buckets=2, horizons=(1,), as_of=150)["result"]
    assert before["current_percentile"] == 100.0
    assert after["current_percentile"] == pytest.approx(50.0)


# ---------- 确定性 ----------


def test_determinism_identical_runs():
    a = run("B16", _cond_pair(), k=5)
    b = run("B16", _cond_pair(), k=5)
    assert json.dumps(a, sort_keys=True, default=str) == json.dumps(b, sort_keys=True, default=str)
