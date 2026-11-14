"""M4-3 测试：resonance_sensor（on-demand R/F_macro/t_arrive/regime_overlay）。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from core.resonance_sensor import ResonanceSensor, derive_regime_overlay


def _write(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f)


@pytest.fixture
def data_dir(tmp_path):
    d = tmp_path / "40"
    d.mkdir()
    _write(
        d / "cycle_state.json",
        {
            "real_cycle": {"last_change": "down", "state": "cutting", "confidence": "high"},
            "technical_anchor": {
                "assets": {"BTC": {"above": True}, "ETH": {"above": True}},
                "regime": "bull",
            },
        },
    )
    _write(
        d / "sector_transmission.json",
        {
            "layers": {"L1_anchor": ["BTC/USDT"], "L2_major": ["ETH/USDT"]},
            "assets": {
                "BTC/USDT": {"layer": "L1_anchor", "momentum_3m_pct": 5.0},
                "ETH/USDT": {"layer": "L2_major", "momentum_3m_pct": 10.0},
            },
            "layer_median_momentum_3m_pct": {"L1_anchor": 5.0, "L2_major": 10.0},
            "transmission": {"state": "expanding", "meme_vs_major_gap_pct": -7.0},
        },
    )
    _write(
        d / "resonance_matrix.json",
        {
            "generated_at": "2026-11-09T00:00:00Z",
            "assets": {
                "ETH/USDT": {
                    "corr0": 0.9,
                    "lag_profile": [0.9, 0.8, 0.4, 0.2],
                    "beta": 1.3,
                    "down_corr": 1.0,
                    "granger_p": 0.01,
                }
            },
        },
    )
    _write(d / "washout_verdicts.json", {"ETH/USDT": {"verdict": "washout", "confidence": 0.8}})
    return str(d)


class TestRegimeOverlay:
    def test_cutting_maps_to_trend(self):
        assert derive_regime_overlay({"real_cycle": {"state": "cutting"}}, None) == "trend"

    def test_plateau_maps_to_range(self):
        assert derive_regime_overlay({"real_cycle": {"state": "plateau"}}, None) == "range"

    def test_fallback_to_transmission_expanding(self):
        assert derive_regime_overlay({}, {"transmission": {"state": "expanding"}}) == "trend"

    def test_fallback_neutral_to_range(self):
        assert derive_regime_overlay({}, {"transmission": {"state": "neutral"}}) == "range"

    def test_empty_unknown(self):
        assert derive_regime_overlay({}, None) == "unknown"


class TestSnapshot:
    def test_full_snapshot(self, data_dir):
        snap = ResonanceSensor(data_dir=data_dir).get_snapshot("ETH/USDT")
        assert snap.layer == "L2_major"
        assert snap.r["corr0"] == 0.9
        assert snap.r["granger_p"] == 0.01
        assert snap.t_arrive == 2.0  # G2 显著 → 启用
        assert snap.regime_overlay == "trend"  # cutting
        assert snap.f_macro["D1"] > 0  # F_cycle 正 × corr0 正

    def test_washout_force_in_snapshot(self, data_dir):
        snap = ResonanceSensor(data_dir=data_dir).get_snapshot("ETH/USDT")
        # base>0 → washout force = -conf
        assert snap.f_macro["washout"] == -0.8

    def test_symbol_normalization(self, data_dir):
        snap = ResonanceSensor(data_dir=data_dir).get_snapshot("ETH-USDT-SWAP")
        assert snap.symbol == "ETH"
        assert snap.layer == "L2_major"

    def test_btc_direct_force(self, data_dir):
        snap = ResonanceSensor(data_dir=data_dir).get_snapshot("BTC/USDT")
        assert snap.layer == "L1_anchor"
        assert abs(snap.f_macro["D1"] - 1.0) < 1e-9  # F_cycle=1.0 × L1 D1 权重 1.0

    def test_unknown_symbol_fail_open(self, data_dir):
        snap = ResonanceSensor(data_dir=data_dir).get_snapshot("XYZ/USDT")
        assert snap.r["corr0"] == 1.0
        assert "symbol_not_in_layers" in snap.degraded
        assert snap.f_macro == {"D1": 0.0, "D2": 0.0, "D4": 0.0, "washout": 0.0}

    def test_missing_artifacts_fail_open(self, tmp_path):
        empty = tmp_path / "empty"
        empty.mkdir()
        snap = ResonanceSensor(data_dir=str(empty)).get_snapshot("ETH/USDT")
        assert snap.r["corr0"] == 1.0
        assert snap.degraded  # 有降级标注

    def test_granger_not_significant_disables_t_arrive(self, tmp_path):
        d = tmp_path / "40b"
        d.mkdir()
        _write(d / "cycle_state.json", {"real_cycle": {"state": "cutting"}})
        _write(
            d / "sector_transmission.json",
            {
                "layers": {"L1_anchor": ["BTC/USDT"], "L2_major": ["ETH/USDT"]},
                "assets": {"ETH/USDT": {"momentum_3m_pct": 0}},
                "layer_median_momentum_3m_pct": {"L1_anchor": 0, "L2_major": 0},
                "transmission": {"state": "expanding"},
            },
        )
        _write(
            d / "resonance_matrix.json",
            {
                "assets": {
                    "ETH/USDT": {
                        "corr0": 0.9,
                        "lag_profile": [0.9, 0.8, 0.4, 0.2],
                        "granger_p": 0.5,
                    }
                }
            },
        )
        snap = ResonanceSensor(data_dir=str(d)).get_snapshot("ETH/USDT")
        assert snap.t_arrive is None
        assert "granger_not_significant" in snap.degraded

    def test_cache_reuses_within_ttl(self, data_dir):
        sensor = ResonanceSensor(data_dir=data_dir, ttl_sec=60)
        s1 = sensor.get_snapshot("ETH/USDT")
        # 修改产出物但 TTL 内 + mtime 不变 → 仍用缓存
        s2 = sensor.get_snapshot("ETH/USDT")
        assert s1.to_dict()["f_macro"] == s2.to_dict()["f_macro"]

    def test_cache_invalidated_on_mtime_change(self, data_dir):
        import os
        import time

        sensor = ResonanceSensor(data_dir=data_dir, ttl_sec=600)
        sensor.get_snapshot("ETH/USDT")
        # 改写 resonance_matrix 并推进 mtime
        path = os.path.join(data_dir, "resonance_matrix.json")
        _write(
            path,
            {
                "assets": {
                    "ETH/USDT": {
                        "corr0": 0.5,
                        "lag_profile": [0.5, 0.5, 0.5],
                        "granger_p": 0.01,
                    }
                }
            },
        )
        future = time.time() + 5
        os.utime(path, (future, future))
        snap = sensor.get_snapshot("ETH/USDT")
        assert snap.r["corr0"] == 0.5


def test_leader_resonance_overrides_identity_for_member(data_dir):
    """类内龙头共振优先：XAG 用相对 XAU 的 R，而非恒等传导。"""
    _write(
        Path(data_dir) / "leader_resonance.json",
        {
            "assets": {
                "XAG": {
                    "class": "precious_metal",
                    "leader": "XAU",
                    "inst_id": "XAG-USDT-SWAP",
                    "corr0": 0.82,
                    "lag_profile": [0.82, 0.5, 0.2],
                    "beta": 1.4,
                    "down_corr": 0.61,
                    "granger_p": 0.02,
                    "n_samples": 180,
                    "degraded": [],
                }
            }
        },
    )
    snap = ResonanceSensor(data_dir=data_dir).get_snapshot("XAG/USDT")
    assert snap.r["corr0"] == 0.82
    assert snap.r["down_corr"] == 0.61
    assert snap.r["beta"] == 1.4
    assert snap.layer == "precious_metal"
    assert snap.degraded == []
    assert snap.t_arrive == 2.0
