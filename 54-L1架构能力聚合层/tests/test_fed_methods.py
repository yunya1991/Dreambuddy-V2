# -*- coding: utf-8 -*-
"""美联储调研方法单测（SPEC-54 §4.12/§4.14：I35–I39 + 四个工具函数）。"""

import math
import os
import random
import sys

_MODULE_ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
if _MODULE_ROOT not in sys.path:
    sys.path.insert(0, _MODULE_ROOT)

from l1agg.methods import REGISTRY, run  # noqa: E402
from l1agg.methods import fed_methods as fed  # noqa: E402

_N = 600


def _cointegrated_pair():
    rng = random.Random(7)
    x = [100.0 + 0.1 * i + rng.gauss(0, 0.2) for i in range(_N)]
    y = [2.0 * x[i] + rng.gauss(0, 0.3) for i in range(_N)]
    return x, y


def _price_path(n=800):
    return [
        100.0 * math.exp(0.0005 * i + 0.02 * math.sin(2.0 * math.pi * i / 60.0)) for i in range(n)
    ]


# ---------------- 登记与门禁 ----------------


def test_i35_to_i39_are_registered():
    implemented = {"I35", "I36", "I37", "I38", "I39"}
    assert implemented <= set(REGISTRY)
    for method_id in implemented:
        spec = REGISTRY[method_id]
        assert spec.func is not None
        assert spec.output_schema


def test_insufficient_samples_gate():
    x, y = _cointegrated_pair()
    assert run("I35", {"x": x[:10], "y": y[:10]})["gate"] == "insufficient_samples"
    assert run("I36", {"x": x[:10], "y": y[:10]})["gate"] == "insufficient_samples"
    assert run("I37", {"values": _price_path(50)})["gate"] == "insufficient_samples"
    assert run("I39", {"series": _price_path(100)})["gate"] == "insufficient_samples"


# ---------------- I35 协整 ----------------


def test_i35_recovers_cointegration_and_gap():
    x, y = _cointegrated_pair()
    out = run("I35", {"x": x, "y": y})["result"]
    assert abs(out["beta"] - 2.0) < 0.05
    assert out["cointegrated"] is True
    assert out["adf_p"] < 0.05
    assert abs(out["gap"]) < 1.5
    assert -3.0 < out["gap_z"] < 3.0
    assert out["half_life"] is not None and out["half_life"] > 0
    assert out["n"] == _N


def test_i35_structure_is_deterministic():
    x, y = _cointegrated_pair()
    assert run("I35", {"x": x, "y": y}) == run("I35", {"x": x, "y": y})


# ---------------- I36 分位回归 ----------------


def test_i36_quantile_ordering_and_dispersion():
    x, y = _cointegrated_pair()
    out = run("I36", {"x": x, "y": y})["result"]
    assert out["q10"] <= out["q50"] <= out["q90"]
    assert out["dispersion"] == round(out["q90"] - out["q10"], 10)
    assert set(out["slopes"]) == {"0.1", "0.5", "0.9"}


def test_i36_dispersion_grows_with_heteroskedasticity():
    rng = random.Random(11)
    x = [i / _N for i in range(_N)]
    calm = [0.01 * x[i] + rng.gauss(0, 0.001) for i in range(_N)]
    wild = [0.01 * x[i] + rng.gauss(0, 0.05) for i in range(_N)]
    calm_disp = run("I36", {"x": x, "y": calm})["result"]["dispersion"]
    wild_disp = run("I36", {"x": x, "y": wild})["result"]["dispersion"]
    assert wild_disp > calm_disp


# ---------------- I37 Kalman ----------------


def test_i37_kalman_band_and_slope_se():
    values = [100.0 + 0.5 * i for i in range(400)]
    out = run("I37", {"values": values})["result"]
    assert out["band"][0] < out["level"] < out["band"][1]
    assert abs(out["slope"] - 0.5) < 0.02
    assert out["level_sigma"] > 0
    assert out["slope_se"] > 0
    assert len(out["path"]) == 400
    assert out["path"][-1]["lower"] <= out["path"][-1]["level"] <= out["path"][-1]["upper"]


def test_i37_path_is_capped_and_deterministic():
    values = _price_path(900)
    first = run("I37", {"values": values})["result"]
    second = run("I37", {"values": values})["result"]
    assert first == second
    assert len(first["path"]) == 500


# ---------------- I38 DMA ----------------


def test_i38_dma_tracks_better_model():
    path = _price_path(800)
    out = run(
        "I38",
        {
            "series": {
                "actual": path,
                "good": path,
                "bad": [v * 1.01 for v in path],
            }
        },
    )["result"]
    assert out["best"] == "good"
    assert out["weights"]["good"] > 0.9
    assert out["entropy"] >= 0
    assert out["lambda"] == 0.99
    assert out["n"] == 800


# ---------------- I39 带通 ----------------


def test_i39_bandpass_recovers_period():
    out = run("I39", {"series": _price_path(900)})["result"]
    assert 50.0 <= out["period_days"] <= 72.0
    assert out["amplitude"] > 0
    assert out["phase_deg"] is not None
    assert out["cycle_slope"] is not None
    assert len(out["cycle"]) <= 750


# ---------------- 工具函数：MIDAS / FCI / 不确定性 / 泰勒 gap ----------------


def test_midas_weights_sum_to_one_and_decay():
    out = fed.midas_weights([20, 60, 120, 250])
    assert abs(out["sum"] - 1.0) < 1e-9
    assert out["weights"][0] > out["weights"][-1]
    assert out["windows"] == [20, 60, 120, 250]


def test_fci_composite_weights_and_index():
    path = _price_path(300)
    out = fed.fci_composite({"credit": path, "rate": [v * 1.001 for v in path]}, window=100)
    assert abs(sum(out["weights"]) - 1.0) < 1e-6
    assert out["components"] == ["credit", "rate"]
    assert 0.0 <= out["shrinkage"] <= 1.0
    assert len(out["index"]) == 100


def test_uncertainty_index_bounded_and_lambda_capped():
    noisy = [100 + 10 * math.sin(i / 3.0) * (1 + i / 200.0) for i in range(300)]
    out = fed.uncertainty_index(noisy)
    assert 0.0 <= out["index"] <= 1.0
    assert 0.0 <= out["lambda_u"] <= 0.5


def test_taylor_gap_explicit_coefficients_and_clip():
    out = fed.taylor_gap(3.2, neutral=2.5, scale=1.0, coefficient=1.5)
    assert abs(out["gap"] - 1.05) < 1e-9
    assert out["coefficient"] == 1.5
    assert fed.taylor_gap(10.0, neutral=0.0, scale=1.0, coefficient=1.0)["gap"] == 3.0
