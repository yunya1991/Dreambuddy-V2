"""P1 测试：G1 大类龙头跨类宏观力（compute_cross_class_forces）+ sensor 接入。"""

from __future__ import annotations

import json

from core.macro_force import (
    ASSET_CLASS_WEIGHTS,
    DEFAULT_ASSET_WEIGHTS,
    compute_cross_class_forces,
)
from core.resonance_sensor import ResonanceSensor

_BULL_STATE = {
    "real_cycle": {"last_change": "down", "state": "cutting"},
    "technical_anchor": {
        "assets": {"BTC": {"above": True}, "ETH": {"above": True}},
        "regime": "bull",
    },
}


def _matrix(assets):
    return {"anchor": "BTC", "assets": assets}


def _btc_entry(mom=5.0):
    return {
        "class": "crypto",
        "corr0": 1.0,
        "lag_profile": [1.0],
        "beta": 1.0,
        "down_corr": 1.0,
        "momentum_3m_pct": mom,
        "granger_p": None,
        "degraded": [],
    }


# ── 权重表 ────────────────────────────────────────────────────────


def test_asset_class_weights_cover_ten_classes():
    assert len(ASSET_CLASS_WEIGHTS) == 10
    for weights in ASSET_CLASS_WEIGHTS.values():
        assert set(weights) == {"D1", "D2", "D4"}


def test_no_crypto_layer_weights_leaked_into_classes():
    assert "L4_meme" not in ASSET_CLASS_WEIGHTS
    assert "L1_anchor" not in ASSET_CLASS_WEIGHTS


# ── 跨类宏观力 ────────────────────────────────────────────────────


def test_empty_matrix_returns_empty_dict():
    assert compute_cross_class_forces(None, _BULL_STATE) == {}
    assert compute_cross_class_forces({}, _BULL_STATE) == {}
    assert compute_cross_class_forces({"assets": {}}, _BULL_STATE) == {}


def test_btc_identity_force():
    forces = compute_cross_class_forces(_matrix({"BTC": _btc_entry()}), _BULL_STATE)
    btc = forces["BTC"]
    # F_cycle = (rate +1 + ma200 +1 + regime +1)/3 = 1.0；BTC 恒等 × w_D1=1.0
    assert btc.layer == "crypto"
    assert abs(btc.d1_trend - 1.0) < 1e-9
    assert btc.t_arrive_days is None
    assert btc.washout == 0.0


def test_non_btc_uses_class_weight():
    entry = {
        "class": "precious_metal",
        "corr0": 0.5,
        "lag_profile": [0.5],
        "momentum_3m_pct": 5.0,
        "granger_p": 0.01,
        "degraded": [],
    }
    forces = compute_cross_class_forces(
        _matrix({"BTC": _btc_entry(5.0), "XAU": entry}), _BULL_STATE
    )
    assert forces["XAU"].layer == "precious_metal"
    # D1 = F_cycle 1.0 × corr0 0.5 × w_D1 0.8
    assert abs(forces["XAU"].d1_trend - 0.4) < 1e-9


def test_unknown_class_falls_back_to_default_weights():
    entry = {
        "class": "mystery",
        "corr0": 0.5,
        "lag_profile": [0.5],
        "momentum_3m_pct": 0.0,
        "granger_p": None,
        "degraded": [],
    }
    forces = compute_cross_class_forces(_matrix({"BTC": _btc_entry(), "XYZ": entry}), _BULL_STATE)
    expected = 1.0 * 0.5 * DEFAULT_ASSET_WEIGHTS["D1"]
    assert abs(forces["XYZ"].d1_trend - expected) < 1e-9


def test_granger_significant_enables_t_arrive():
    entry = {
        "class": "energy",
        "corr0": 0.9,
        "lag_profile": [0.9, 0.8, 0.4, 0.1],
        "momentum_3m_pct": 0.0,
        "granger_p": 0.01,
        "degraded": [],
    }
    forces = compute_cross_class_forces(_matrix({"BTC": _btc_entry(), "CL": entry}), _BULL_STATE)
    assert forces["CL"].t_arrive_days == 2.0


def test_granger_not_significant_disables_t_arrive():
    entry = {
        "class": "energy",
        "corr0": 0.9,
        "lag_profile": [0.9, 0.8, 0.4, 0.1],
        "momentum_3m_pct": 0.0,
        "granger_p": 0.5,
        "degraded": [],
    }
    forces = compute_cross_class_forces(_matrix({"BTC": _btc_entry(), "CL": entry}), _BULL_STATE)
    assert forces["CL"].t_arrive_days is None
    assert "granger_not_significant" in forces["CL"].degraded


def test_entry_degraded_propagates():
    entry = {
        "class": "rates_credit",
        "corr0": 1.0,
        "lag_profile": [1.0],
        "momentum_3m_pct": None,
        "granger_p": None,
        "degraded": ["fetch_failed"],
    }
    forces = compute_cross_class_forces(_matrix({"BTC": _btc_entry(), "TLT": entry}), _BULL_STATE)
    assert "fetch_failed" in forces["TLT"].degraded


# ── sensor 接入 ───────────────────────────────────────────────────


def _write(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f)


def test_sensor_reads_cross_asset_for_g1_anchor(tmp_path):
    d = tmp_path / "40"
    d.mkdir()
    _write(d / "cycle_state.json", _BULL_STATE)
    _write(
        d / "cross_asset_matrix.json",
        _matrix(
            {
                "BTC": _btc_entry(),
                "XAU": {
                    "class": "precious_metal",
                    "corr0": 0.5,
                    "lag_profile": [0.5, 0.4, 0.3],
                    "beta": 0.7,
                    "down_corr": 0.4,
                    "momentum_3m_pct": 5.0,
                    "granger_p": 0.01,
                    "degraded": [],
                },
            }
        ),
    )
    snap = ResonanceSensor(data_dir=str(d)).get_snapshot("XAU-USDT-SWAP")
    assert snap.symbol == "XAU"
    assert snap.layer == "precious_metal"
    assert snap.r["corr0"] == 0.5
    assert snap.r["beta"] == 0.7
    assert snap.f_macro["D1"] > 0


def test_sensor_without_cross_matrix_degrades(tmp_path):
    d = tmp_path / "40"
    d.mkdir()
    _write(d / "cycle_state.json", _BULL_STATE)
    snap = ResonanceSensor(data_dir=str(d)).get_snapshot("XAU")
    assert snap.layer == "unknown"
    assert "symbol_not_in_layers" in snap.degraded
    assert "cross_asset_missing" in snap.degraded
