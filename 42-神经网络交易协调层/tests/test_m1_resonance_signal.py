"""WP-M1 测试：40-resonance 共振信号外发。

cycle_state_adapter.py 增读 resonance_matrix.json，
发布 40-resonance 源（symbol=MACRO，confidence=0.8×|corr0|×granger_ratio）。
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

_42_ROOT = str(Path(__file__).resolve().parent.parent)
if _42_ROOT not in sys.path:
    sys.path.insert(0, _42_ROOT)

from adapters.cycle_state_adapter import build_resonance_signal  # noqa: E402


def _matrix(assets=None, generated_at="2026-11-09T14:00:00+00:00"):
    return {
        "generated_at": generated_at,
        "anchor": "BTC/USDT",
        "assets": assets or {},
    }


def test_resonance_signal_source_and_symbol():
    sig = build_resonance_signal(_matrix())
    assert sig["source"] == "40-resonance"
    assert sig["symbol"] == "MACRO"
    assert sig["horizon"] == "days"


def test_resonance_empty_matrix_is_neutral_and_degraded():
    """resonance_matrix 为空 → direction=neutral, confidence=0, degraded=resonance_matrix_empty"""
    sig = build_resonance_signal(_matrix(assets={}))
    assert sig["direction"] == "neutral"
    assert sig["confidence"] == 0.0
    assert "resonance_matrix_empty" in sig["payload"]["degraded"]


def test_resonance_direction_btc_corr0_positive():
    """BTC corr0 > 0.1 → long"""
    m = _matrix(assets={"BTC/USDT": {"corr0": 0.8, "granger_p": 0.01}})
    sig = build_resonance_signal(m)
    assert sig["direction"] == "long"


def test_resonance_direction_btc_corr0_negative():
    """BTC corr0 < -0.1 → short"""
    m = _matrix(assets={"BTC/USDT": {"corr0": -0.7, "granger_p": 0.02}})
    sig = build_resonance_signal(m)
    assert sig["direction"] == "short"


def test_resonance_confidence_formula():
    """confidence = 0.8 × |corr0| × granger_significant_ratio"""
    # 2 个标的，1 个 Granger 显著（p<0.05），ratio=0.5
    m = _matrix(
        assets={
            "BTC/USDT": {"corr0": 0.6, "granger_p": 0.01},
            "ETH/USDT": {"corr0": 0.5, "granger_p": 0.3},
        }
    )
    sig = build_resonance_signal(m)
    # 0.8 × 0.6 × 0.5 = 0.24
    assert sig["confidence"] == pytest.approx(0.24, abs=1e-4)


def test_resonance_granger_not_significant_degraded():
    """所有标的 Granger 不显著 → degraded=granger_not_significant"""
    m = _matrix(
        assets={
            "BTC/USDT": {"corr0": 0.5, "granger_p": 0.5},
            "ETH/USDT": {"corr0": 0.4, "granger_p": 0.6},
        }
    )
    sig = build_resonance_signal(m)
    assert "granger_not_significant" in sig["payload"]["degraded"]
    assert sig["confidence"] == 0.0  # ratio=0 → confidence=0


def test_resonance_payload_carries_btc_rs():
    """payload 应携带 BTC 的 corr0/beta/lag_profile"""
    m = _matrix(
        assets={
            "BTC/USDT": {"corr0": 0.9, "beta": 1.2, "lag_profile": [0.9, 0.1], "granger_p": 0.001},
        }
    )
    sig = build_resonance_signal(m)
    assert sig["payload"]["btc_corr0"] == pytest.approx(0.9)
    assert sig["payload"]["btc_beta"] == 1.2
    assert sig["payload"]["btc_lag_profile"] == [0.9, 0.1]
    assert sig["payload"]["n_granger_significant"] == 1
