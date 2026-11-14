# -*- coding: utf-8 -*-
"""方法注册表 + S2 相关性批（自举批次）测试。"""

import math
import os
import sys

import pytest

_MODULE_ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
if _MODULE_ROOT not in sys.path:
    sys.path.insert(0, _MODULE_ROOT)

from l1agg.methods import (  # noqa: E402
    MethodUnavailable,
    RegistryError,
    all_specs,
    get,
    register,
    run,
)
from l1agg.methods.correlation import _ccf_core  # noqa: E402

N = 140


def _linear(n=N, slope=2.0, offset=3.0):
    xs = [float(i) for i in range(n)]
    return xs, [slope * x + offset for x in xs]


def _wave(n=N):
    return [math.sin(i * 0.7) + 0.3 * math.cos(i * 1.3) for i in range(n)]


# ---------- 注册表契约 ----------


def test_catalog_covers_method_library():
    specs = all_specs()
    assert len(specs) == 238  # §1 分类总览容量
    assert get("M01").implemented is True
    assert get("T18").implemented is True


def test_placeholder_method_cannot_run():
    with pytest.raises(MethodUnavailable):
        run("C11", [])


def test_duplicate_registration_rejected():
    with pytest.raises(RegistryError):

        @register(
            "M01",
            name="dup",
            group="M",
            layer="D2",
            input_kind="pairs",
            min_n=1,
            output_schema=("r",),
        )
        def _dup(data):
            return {}


def test_invalid_method_id_rejected():
    with pytest.raises(RegistryError):
        get("Z99")


def test_gate_returns_insufficient_samples():
    out = run("M01", {"x": list(range(10)), "y": list(range(10))})
    assert out["gate"] == "insufficient_samples"
    assert out["result"] is None


def test_ccf_gate_needs_120():
    xs, ys = _linear(100)
    assert run("M11", {"x": xs, "y": ys})["gate"] == "insufficient_samples"


# ---------- M01–M03 ----------


def test_m01_pearson_perfect():
    xs, ys = _linear()
    out = run("M01", {"x": xs, "y": ys})
    assert out["result"]["r"] == pytest.approx(1.0)
    assert out["result"]["p"] < 1e-9
    assert out["result"]["n"] == N
    assert out["layer"] == "D2"


def test_m02_spearman_monotonic():
    xs = [float(i) for i in range(N)]
    out = run("M02", {"x": xs, "y": [x**3 for x in xs]})
    assert out["result"]["r"] == pytest.approx(1.0)


def test_m03_kendall_perfect():
    xs, ys = _linear()
    out = run("M03", {"x": xs, "y": ys})
    assert out["result"]["tau"] == pytest.approx(1.0)


# ---------- M04–M07 ----------


def test_m04_rolling_constant_corr():
    xs, ys = _linear()
    out = run("M04", {"x": xs, "y": ys}, window=30)
    assert out["result"]["n_windows"] == N - 30 + 1
    assert out["result"]["mean_r"] == pytest.approx(1.0)


def test_m05_matrix_signs():
    xs = [float(i) for i in range(N)]
    out = run("M05", {"series": {"A": xs, "B": [2 * x for x in xs], "C": [-x for x in xs]}})
    m = out["result"]["matrix"]
    assert m["A"]["B"] == pytest.approx(1.0)
    assert m["A"]["C"] == pytest.approx(-1.0)
    assert m["A"]["A"] == 1.0


def test_m06_topk_phrase_and_fdr():
    xs = [float(i) for i in range(N)]
    noise = [float((i * 37) % 11) for i in range(N)]
    out = run("M06", {"series": {"A": xs, "B": [2 * x for x in xs], "C": noise}}, k=2)
    res = out["result"]
    assert "相关性最高" in res["phrase"]
    assert res["topk"][0]["r"] == pytest.approx(1.0)
    assert all("q" in p and "significant" in p for p in res["pairs"])


def test_m07_avg_corr():
    xs = [float(i) for i in range(N)]
    out = run("M07", {"series": {"A": xs, "B": [2 * x for x in xs], "C": [3 * x for x in xs]}})
    assert out["result"]["avg_abs_r"] == pytest.approx(1.0)
    assert out["result"]["n_assets"] == 3


# ---------- M11–M12 ----------


def test_ccf_detects_lead_one():
    x = _wave()
    y = [0.0] + x[:-1]  # y[t]=x[t-1] → x 领先 y 1 期
    out = run("M12", {"x": x, "y": y}, max_lag=10)
    assert out["result"]["lag"] == 1
    assert out["result"]["r"] > 0.9


def test_ccf_lag_grid_and_fdr():
    x = _wave()
    y = [0.0] + x[:-1]
    ccf = _ccf_core(x, y, 5)
    assert ccf["lags"] == list(range(-5, 6))
    assert len(ccf["p"]) == len(ccf["q"]) == 11
    assert ccf["significant"][ccf["lags"].index(1)] is True


# ---------- M24–M25 ----------


def test_m24_stability_perfect():
    xs, ys = _linear()
    out = run("M24", {"x": xs, "y": ys}, window=30)
    assert out["result"]["stability"] == pytest.approx(1.0)
    assert out["result"]["sign_consistency"] == pytest.approx(1.0)


def test_m25_detects_regime_break():
    n = N * 2
    x = [math.sin(i * 0.7) for i in range(n)]
    y = [x[i] if i < n // 2 else -x[i] for i in range(n)]
    out = run("M25", {"x": x, "y": y}, window=20, threshold=2.0)
    assert out["result"]["breakpoints"]
    assert all(0 < b < len(out["result"]["z"]) for b in out["result"]["breakpoints"])
