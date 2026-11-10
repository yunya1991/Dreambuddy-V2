"""主导因素一致率门控测试 — SPEC-D1-MULTIDIM-STATE §2.7.3 / §7 P3-a。

三档（预注册阈值冻结）：
  consistent            主导维 = 实测最强维且方向一致 → 权重 1.0
  divergent_but_valid   主导维 |z|≥1 且方向一致（不是最强） → 权重 1.5
  no_signal             主导维 |z|<0.5 或方向相反 → 权重 0.3
  unmeasurable          主导维无可用数据 → 不参与一致率统计
"""

from __future__ import annotations

import pytest
from data_center.processing.dimension_context import DimensionContext
from data_center.processing.dominance_agreement import (
    GATE_WEIGHTS,
    evaluate_claim,
    summarize,
)


def _ctx(dim, direction="up", strength=0.5, z=1.0, availability="long"):
    return DimensionContext(
        dimension=dim,
        as_of="2026-06-01",
        direction=direction,
        strength=strength,
        z=z,
        percentile=0.8,
        data_points=300,
        availability=availability,
        series_id=f"test:{dim}",
        factors_used=(),
    )


def _claim(dim, direction="bullish"):
    return {
        "claim_type": "dominance",
        "doc_id": "d1",
        "dominant_factor": "flow.funding",
        "dominant_dimension": dim,
        "direction": direction,
        "horizon": "days",
    }


def _matrix(**kw):
    base = {
        "D1": _ctx("D1", "neutral", 0.05, 0.1),
        "D2": _ctx("D2", "down", 0.2, -0.6),
        "D3": _ctx("D3", "up", 0.7, 1.4),
        "D4": _ctx("D4", "neutral", 0.1, 0.2),
        "C6": _ctx("C6", availability="none", direction="neutral", strength=0.0, z=0.0),
        "C7": _ctx("C7", availability="none", direction="neutral", strength=0.0, z=0.0),
        "C8": _ctx("C8", availability="none", direction="neutral", strength=0.0, z=0.0),
        "NEWS": _ctx("NEWS", availability="none", direction="neutral", strength=0.0, z=0.0),
    }
    base.update(kw)
    return base


def test_consistent_when_top_and_same_direction():
    m = _matrix(D3=_ctx("D3", "up", 0.85, 1.8))
    r = evaluate_claim(_claim("D3", "bullish"), m)
    assert r["gate"] == "consistent"
    assert r["weight"] == GATE_WEIGHTS["consistent"]
    assert r["agreement"] is True


def test_divergent_but_valid_when_z_ge_1_same_direction():
    m = _matrix(
        D3=_ctx("D3", "up", 0.9, 2.0),
        D2=_ctx("D2", "up", 0.5, 1.2),
    )
    r = evaluate_claim(_claim("D2", "bullish"), m)
    assert r["gate"] == "divergent_but_valid"
    assert r["weight"] == pytest.approx(1.5)


def test_no_signal_when_direction_opposite():
    m = _matrix(D2=_ctx("D2", "down", 0.5, -1.4))
    r = evaluate_claim(_claim("D2", "bullish"), m)
    assert r["gate"] == "no_signal"
    assert r["weight"] == pytest.approx(0.3)
    assert r["agreement"] is False


def test_no_signal_when_z_below_half():
    m = _matrix(D2=_ctx("D2", "neutral", 0.05, 0.2))
    r = evaluate_claim(_claim("D2", "bullish"), m)
    assert r["gate"] == "no_signal"


def test_unmeasurable_when_dimension_has_none():
    r = evaluate_claim(_claim("C6"), _matrix())
    assert r["gate"] == "unmeasurable"
    assert r["weight"] is None
    assert r["agreement"] is None


def test_summarize_excludes_unmeasurable():
    rows = [
        {"gate": "consistent", "agreement": True},
        {"gate": "divergent_but_valid", "agreement": True},
        {"gate": "no_signal", "agreement": False},
        {"gate": "unmeasurable", "agreement": None},
    ]
    s = summarize(rows)
    assert s["n_total"] == 4
    assert s["n_measurable"] == 3
    assert s["agreement_rate"] == pytest.approx(2 / 3)
    assert s["gate_counts"]["unmeasurable"] == 1


def test_summarize_empty():
    s = summarize([])
    assert s["n_total"] == 0
    assert s["agreement_rate"] is None
