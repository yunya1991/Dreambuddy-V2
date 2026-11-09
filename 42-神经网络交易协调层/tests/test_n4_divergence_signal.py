"""WP-R1 N4 测试：40-divergence 背离信号外发。

cycle_state_adapter.py 增读 asset_rotation.json.divergence，
发布 40-divergence 源（symbol=MACRO，confidence=0.8×(1-n_divergent/n_scored)）。
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

# 将 42 根目录加入 path，使 adapters 可 import
_42_ROOT = str(Path(__file__).resolve().parent.parent)
if _42_ROOT not in sys.path:
    sys.path.insert(0, _42_ROOT)

from adapters.cycle_state_adapter import build_divergence_signal  # noqa: E402


def _rot(n_divergent=0, n_scored=6, quadrant="stagflation", checks=None):
    if checks is None:
        checks = [{"asset": "equity_spx", "verdict": "consistent"}] * n_scored
    return {
        "divergence": {
            "generated_at": "2026-11-09T13:34:30+00:00",
            "quadrant": quadrant,
            "checks": checks,
            "n_divergent": n_divergent,
            "n_scored": n_scored,
            "quadrant_confidence": "high",
        }
    }


def test_divergence_signal_source_and_symbol():
    sig = build_divergence_signal(_rot())
    assert sig["source"] == "40-divergence"
    assert sig["symbol"] == "MACRO"


def test_divergence_confidence_formula_zero_divergence():
    """n_divergent=0 → confidence=0.8×(1-0)=0.8"""
    sig = build_divergence_signal(_rot(n_divergent=0, n_scored=6))
    assert sig["confidence"] == pytest.approx(0.8)


def test_divergence_confidence_formula_half_divergence():
    """n_divergent=3, n_scored=6 → confidence=0.8×(1-0.5)=0.4"""
    sig = build_divergence_signal(_rot(n_divergent=3, n_scored=6))
    assert sig["confidence"] == pytest.approx(0.4)


def test_divergence_confidence_formula_all_divergent():
    """n_divergent=6, n_scored=6 → confidence=0.8×(1-1)=0.0"""
    sig = build_divergence_signal(_rot(n_divergent=6, n_scored=6))
    assert sig["confidence"] == pytest.approx(0.0)


def test_divergence_direction_low_divergence_is_long():
    """背离率 < 0.5 → long（时钟被印证，趋势延续）"""
    sig = build_divergence_signal(_rot(n_divergent=1, n_scored=6))
    assert sig["direction"] == "long"


def test_divergence_direction_high_divergence_is_short():
    """背离率 >= 0.5 → short（时钟被打破，潜在反转）"""
    sig = build_divergence_signal(_rot(n_divergent=4, n_scored=6))
    assert sig["direction"] == "short"


def test_divergence_no_scored_data_is_neutral():
    """n_scored=0 → neutral（无动量数据可判定）"""
    sig = build_divergence_signal(_rot(n_divergent=0, n_scored=0))
    assert sig["direction"] == "neutral"
    assert sig["confidence"] == 0.0


def test_divergence_missing_divergence_block_is_neutral():
    """asset_rotation 无 divergence 字段 → neutral"""
    sig = build_divergence_signal({})
    assert sig["direction"] == "neutral"
    assert sig["confidence"] == 0.0
