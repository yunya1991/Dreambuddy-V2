"""factor_priors_overlay 单测（G4 升级：先验参与决策计算）。"""

from __future__ import annotations

from core.factor_priors_overlay import (
    MAX_COEF,
    _bucket_factors_by_dimension,
    apply_factor_priors_overlay,
    dimension_net_strength,
)
from core.path_synthesis import Path


def _mk(direction="long", confidence=0.5, dimension="D3", source="11-bcrm-tactical"):
    return Path(
        path_id=f"ev:{source}:X:{dimension}:hours:trend",
        source=source,
        symbol="BTC-USDT-SWAP",
        direction=direction,
        confidence=confidence,
        expected_return=0.0,
        resistance=0.0,
        continuation_score=0.5,
        dimension=dimension,
        horizon="hours",
        intent="trend",
        metadata={"weight": 0.35},
    )


FACTORS = {
    "technical.trend": {"dominant_direction": "bullish", "total_weight": 16.0},
    "technical.level": {"dominant_direction": "bullish", "total_weight": 16.0},
    "macro.rate": {"dominant_direction": "bearish", "total_weight": 11.6},
    "flow.oi": {"dominant_direction": "bullish", "total_weight": 22.8},
}


def test_zero_coef_is_baseline():
    paths = [_mk()]
    out = apply_factor_priors_overlay(paths, FACTORS, 0.0)
    assert out[0].confidence == paths[0].confidence


def test_empty_factors_is_baseline():
    paths = [_mk()]
    assert apply_factor_priors_overlay(paths, {}, 0.3)[0].confidence == 0.5
    assert apply_factor_priors_overlay(paths, None, 0.3)[0].confidence == 0.5


def test_aligned_direction_boosts_confidence():
    # D3 命中 technical(bullish)+flow(bullish)，path=long → 全支持，strength=+1
    paths = [_mk(direction="long", confidence=0.5, dimension="D3")]
    out = apply_factor_priors_overlay(paths, FACTORS, 0.2)
    assert out[0].confidence > 0.5
    # strength=+1 → factor=1+0.2*1=1.2 → 0.5*1.2=0.6
    assert abs(out[0].confidence - 0.6) < 1e-6


def test_opposed_direction_reduces_confidence():
    # D3 全 bullish，path=short → 全反对，strength=-1
    paths = [_mk(direction="short", confidence=0.5, dimension="D3")]
    out = apply_factor_priors_overlay(paths, FACTORS, 0.2)
    assert out[0].confidence < 0.5
    assert abs(out[0].confidence - 0.4) < 1e-6  # 0.5*(1-0.2)=0.4


def test_unmatched_dimension_unchanged():
    # C6 无任何因子前缀映射 → 不变
    paths = [_mk(dimension="C6", source="11-bdsm")]
    out = apply_factor_priors_overlay(paths, FACTORS, 0.3)
    assert out[0].confidence == 0.5


def test_neutral_path_not_modulated():
    paths = [_mk(direction="neutral", dimension="D3")]
    out = apply_factor_priors_overlay(paths, FACTORS, 0.5)
    assert out[0].confidence == 0.5


def test_confidence_clamped_to_one():
    # 高 confidence + 全支持 + 大系数 → 截断到 1.0
    paths = [_mk(direction="long", confidence=0.95, dimension="D3")]
    out = apply_factor_priors_overlay(paths, FACTORS, MAX_COEF)
    assert out[0].confidence == 1.0


def test_coef_clamped_to_max():
    # coef 超上限被截断：0.9 → MAX_COEF=0.5，strength=+1 → 0.5*(1+0.5)=0.75
    paths = [_mk(direction="long", confidence=0.5, dimension="D3")]
    out = apply_factor_priors_overlay(paths, FACTORS, 0.9)
    assert abs(out[0].confidence - 0.75) < 1e-6


def test_bullish_bearish_normalized():
    buckets = _bucket_factors_by_dimension(FACTORS)
    # D1 只有 macro.rate(bearish) → short
    assert buckets["D1"] == [("short", 11.6)]
    # D3 有 technical×2 + flow，全部 bullish → long
    assert all(d == "long" for d, _ in buckets["D3"])


def test_net_strength_mixed():
    # 构造混合方向：D1 同时有 bullish(10) 与 bearish(30)
    factors = {
        "macro.equity": {"dominant_direction": "bullish", "total_weight": 10.0},
        "macro.rate": {"dominant_direction": "bearish", "total_weight": 30.0},
    }
    buckets = _bucket_factors_by_dimension(factors)
    # path=long: support=10-30=-20, total=40 → -0.5
    assert abs(dimension_net_strength("D1", "long", buckets) - (-0.5)) < 1e-6
    # path=short: support=-10+30=20, total=40 → +0.5
    assert abs(dimension_net_strength("D1", "short", buckets) - 0.5) < 1e-6
    # 无命中维度 → 0
    assert dimension_net_strength("C6", "long", buckets) == 0.0


def test_original_paths_not_mutated():
    paths = [_mk(direction="long", confidence=0.5, dimension="D3")]
    _ = apply_factor_priors_overlay(paths, FACTORS, 0.3)
    assert paths[0].confidence == 0.5  # 原对象不被修改


def test_event_factor_maps_to_c7_only():
    # SPEC-M4 v0.2 Q2 裁决：event.* 首轮仅映射 C7，不再双映射 NEWS。
    buckets = _bucket_factors_by_dimension(
        {"event.listing": {"dominant_direction": "bullish", "total_weight": 19.0}}
    )
    assert set(buckets.keys()) == {"C7"}


def test_min_n_samples_declared():
    # SPEC-M4 v0.2 Q4 裁决：先验样本量下限 200，低于下限由调用方 no-op。
    from core.factor_priors_overlay import MIN_N_SAMPLES

    assert MIN_N_SAMPLES == 200


def test_probe_summary_includes_decision_threshold_states():
    from tools.priors_differential_probe import _summarize_w4

    summary = _summarize_w4(
        {
            "direction": "long",
            "total": 0.61,
            "force": 0.7,
            "urgency": 0.3,
            "consistency": 0.5,
            "impact": 0.8,
            "resonance": True,
            "dominant": True,
        }
    )

    assert summary["resonance"] is True
    assert summary["dominant"] is True
