# -*- coding: utf-8 -*-
"""调研族 X（横截面 12 条）/ O（时序算子 15 条）实现测试。

覆盖：27 条逐条数值/性质断言、输出 schema 一致性、确定性、空输入门禁。
"""

import json
import math
import os
import sys

_MODULE_ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
if _MODULE_ROOT not in sys.path:
    sys.path.insert(0, _MODULE_ROOT)

import l1agg.methods.research_xo  # noqa: E402,F401
from l1agg.methods import get, run  # noqa: E402

X_IDS = [f"X{i:02d}" for i in range(1, 13)]
O_IDS = [f"O{i:02d}" for i in range(1, 16)]
ALL_IDS = X_IDS + O_IDS


# ---------------------------------------------------------------- 数据构造


def _panel(n=40, k=12):
    """有横截面差异、且标的排序在时间上稳定的面板。"""
    return {
        "series": {
            f"S{s:02d}": [100.0 + 2.0 * s + 0.5 * math.sin(0.3 * t + 0.7 * s) for t in range(n)]
            for s in range(k)
        }
    }


def _panel_trend(n=40, k=12):
    """全部标的单调上涨的面板（宽度/同向率用）。"""
    return {
        "series": {f"S{s:02d}": [100.0 + 2.0 * s + 0.3 * t for t in range(n)] for s in range(k)}
    }


_FACTOR = {"S00": -1.5, "S01": -1.0, "S02": -0.5, "S03": 0.0, "S04": 0.5, "S05": 1.0, "S06": 1.5}


def _reg_panel(beta=2.0, n=40):
    """最近一期收益 = beta × 因子暴露（可精确回收系数）。"""
    return {"series": {sym: [100.0 + beta * f * t for t in range(n)] for sym, f in _FACTOR.items()}}


def _ramp(n=40, start=1.0, step=1.0):
    return [start + step * t for t in range(n)]


def _wave(n=40):
    return [math.sin(0.4 * t) + 0.3 * math.cos(0.9 * t) for t in range(n)]


# ---------------------------------------------------------------- 目录契约


def test_all_27_ids_implemented():
    assert len(ALL_IDS) == 27
    for mid in ALL_IDS:
        spec = get(mid)
        assert spec.implemented is True, mid
        assert spec.func is not None, mid
        assert spec.output_schema, mid


def test_output_schema_matches_returned_keys():
    for mid in X_IDS:
        out = run(mid, _panel())
        assert out["gate"] == "ok", mid
        assert set(out["result"]) == set(get(mid).output_schema), mid
    for mid in O_IDS:
        data = {"x": _wave(), "y": _wave()} if mid in ("O09", "O10") else _wave()
        out = run(mid, data)
        assert out["gate"] == "ok", mid
        assert set(out["result"]) == set(get(mid).output_schema), mid


def test_empty_input_blocked_by_gate():
    cases = {
        "X01": {"series": {}},
        "X09": {"series": {}},
        "O01": [],
        "O09": {"x": [], "y": []},
        "O15": [],
    }
    for mid, data in cases.items():
        out = run(mid, data)  # 不抛异常
        assert out["gate"] == "insufficient_samples", mid
        assert out["result"] is None, mid


# ---------------------------------------------------------------- X 组


def test_x01_zscore_mean_zero():
    out = run("X01", _panel())["result"]
    assert out["n"] == 12
    assert abs(sum(out["z"].values()) / out["n"]) < 1e-5


def test_x02_pct_rank_bounds():
    out = run("X02", _panel())["result"]
    pct = list(out["pct"].values())
    assert all(0.0 < p < 1.0 + 1e-12 for p in pct)
    assert abs(min(pct) - 1.0 / 12.0) < 1e-6
    assert abs(max(pct) - 1.0) < 1e-12


def test_x03_neutralize_group_means_zero():
    groups = {f"S{s:02d}": ("a" if s < 6 else "b") for s in range(12)}
    out = run("X03", _panel(), group=groups)["result"]
    for members in (range(6), range(6, 12)):
        vals = [out["resid"][f"S{s:02d}"] for s in members]
        assert abs(sum(vals) / len(vals)) < 1e-5


def test_x04_quantile_buckets():
    out = run("X04", _panel(), k=4)["result"]
    assert all(0 <= b <= 3 for b in out["bucket"].values())
    assert sum(out["counts"].values()) == out["n"] == 12


def test_x05_long_short_spread_positive():
    out = run("X05", _panel_trend(), k=5)["result"]
    assert out["spread"] > 0
    assert out["t"] > 0
    assert out["n"] == 12


def test_x06_dispersion_positive():
    out = run("X06", _panel())["result"]
    assert out["dispersion"] > 0
    assert out["n"] == 12


def test_x07_breadth_all_rising():
    out = run("X07", _panel_trend())["result"]
    assert out["breadth"] == 1.0
    assert out["advance"] == 12 and out["decline"] == 0


def test_x08_same_direction_ratio():
    out = run("X08", _panel_trend())["result"]
    assert out["ratio"] == 1.0
    assert out["pairs"] == 66
    assert out["agree"] == 66


def test_x09_factor_exposure_recovers_beta():
    out = run("X09", _reg_panel(), factor=_FACTOR)["result"]
    assert abs(out["betas"]["factor"] - 2.0) < 1e-6
    assert abs(out["alpha"]) < 1e-6
    assert abs(out["r2"] - 1.0) < 1e-6


def test_x10_specific_return_zero_on_exact_model():
    out = run("X10", _reg_panel(), factor=_FACTOR)["result"]
    assert all(abs(v) < 1e-6 for v in out["specific"].values())
    assert out["std"] < 1e-6


def test_x11_wls_factor_return():
    weights = {sym: 1.0 + i for i, sym in enumerate(sorted(_FACTOR))}
    out = run("X11", _reg_panel(), factor=_FACTOR, weights=weights)["result"]
    assert abs(out["factor_ret"]["factor"] - 2.0) < 1e-6
    assert out["n"] == 7


def test_x12_cross_section_autocorr_stable_order():
    out = run("X12", _panel())["result"]
    assert abs(out["rho"] - 1.0) < 1e-6
    assert out["lag"] == 1 and out["n"] == 12


# ---------------------------------------------------------------- O 组


def test_o01_delay_leading_none():
    out = run("O01", _ramp(), d=5)["result"]
    assert out["series"][:5] == [None] * 5
    assert out["series"][5] == 1.0
    assert out["n"] == 40


def test_o02_delta_constant_step():
    out = run("O02", _ramp(), d=5)["result"]
    assert out["series"][5] == 5.0
    assert all(v == 5.0 for v in out["series"][5:])


def test_o03_ts_sum_window():
    out = run("O03", [1.0] * 40, d=5)["result"]
    assert out["series"][4] == 5.0
    assert out["series"][-1] == 5.0


def test_o04_ts_mean_std():
    out = run("O04", _ramp(), d=5)["result"]
    assert out["mean"][4] == 3.0
    assert abs(out["std"][4] - math.sqrt(2.5)) < 1e-5
    assert out["mean"][3] is None


def test_o05_ts_min_max():
    xs = [3.0, 1.0, 4.0, 1.0, 5.0] + [2.0] * 35
    out = run("O05", xs, d=5)["result"]
    assert out["min"][4] == 1.0 and out["max"][4] == 5.0
    assert out["min"][-1] == 2.0 and out["max"][-1] == 2.0


def test_o06_ts_arg_extremes():
    out = run("O06", _ramp(), d=5)["result"]
    assert out["argmax"][-1] == 0
    assert out["argmin"][-1] == 4


def test_o07_ts_rank_monotone():
    out = run("O07", _ramp(), d=5)["result"]
    assert out["series"][-1] == 1.0
    assert out["series"][4] == 1.0


def test_o08_ts_zscore():
    out = run("O08", _ramp(), d=5)["result"]
    assert abs(out["series"][-1] - 2.0 / math.sqrt(2.5)) < 1e-5
    flat = run("O08", [7.0] * 40, d=5)["result"]
    assert flat["series"][-1] == 0.0


def test_o09_ts_corr_identical_series():
    xs = _wave()
    out = run("O09", {"x": xs, "y": xs}, d=10)["result"]
    assert out["corr"][-1] > 0.999
    assert out["corr"][8] is None


def test_o10_ts_cov_matches_variance():
    xs = _wave()
    out = run("O10", {"x": xs, "y": xs}, d=20)["result"]
    win = xs[-20:]
    mu = sum(win) / len(win)
    var = sum((v - mu) ** 2 for v in win) / (len(win) - 1)
    assert abs(out["cov"][-1] - var) < 1e-5


def test_o11_decay_linear_weights_recent_more():
    out = run("O11", _ramp(), d=5)["result"]
    # 窗口 36..40，权重 1..5 → 580/15
    assert abs(out["series"][-1] - 580.0 / 15.0) < 1e-5
    assert out["series"][-1] > 38.0


def test_o12_scale_abs_sum_equals_a():
    out = run("O12", _wave(), a=2.0)["result"]
    # 文档口径 x·a/Σ|x|：缩放后绝对值之和 = a，绝对值均值 = a/n
    assert abs(sum(abs(v) for v in out["scaled"]) - 2.0) < 1e-5
    assert abs(sum(abs(v) for v in out["scaled"]) / out["n"] - 2.0 / out["n"]) < 1e-6
    assert out["a"] == 2.0


def test_o13_signedpower_preserves_sign():
    xs = [-2.0, -1.0, 0.0, 1.0, 2.0] * 8
    out = run("O13", xs, e=2.0)["result"]
    assert out["series"][0] == -4.0
    assert out["series"][2] == 0.0
    assert out["series"][3] == 1.0


def test_o14_rank_percentile():
    out = run("O14", _wave())["result"]
    ranks = out["rank"]
    assert all(0.0 < r <= 1.0 for r in ranks)
    assert max(ranks) == 1.0


def test_o15_indneutralize_within_group_mean_zero():
    xs = [float(i) for i in range(20)] + [100.0 + i for i in range(20)]
    groups = ["a"] * 20 + ["b"] * 20
    out = run("O15", xs, g=groups)["result"]
    assert out["group_n"] == 2
    for members in (range(20), range(20, 40)):
        vals = [out["resid"][i] for i in members]
        assert abs(sum(vals) / len(vals)) < 1e-5


# ---------------------------------------------------------------- 确定性


def test_deterministic_panel_methods():
    a = run("X01", _panel())
    b = run("X01", _panel())
    assert json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True)


def test_deterministic_series_methods():
    a = run("O11", _wave(), d=15)
    b = run("O11", _wave(), d=15)
    assert json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True)
    c = run("X09", _reg_panel(), factor=_FACTOR)
    d = run("X09", _reg_panel(), factor=_FACTOR)
    assert json.dumps(c, sort_keys=True) == json.dumps(d, sort_keys=True)
