"""WP-R1 N3 测试：macro_force 角色四分 + 权重表注册（G1 红线：权重暂为 0）。

SPEC-M1 M4/M5：40-cycle / 43-strategic / 40-divergence 归入 macro_force 角色，
产 D1 维度、days 周期的 path；R0 未完成前权重保持 0（G1 红线）。
"""

from __future__ import annotations

from datetime import datetime, timezone

from core.mappings import (
    MACRO_FORCE_SOURCES,
    SOURCE_DIM_MAP,
    SOURCE_TF_MAP,
    SOURCE_WEIGHT_MAP,
    role_of,
)
from core.path_synthesis import synthesize_paths

NOW = datetime(2026, 11, 8, 1, 0, tzinfo=timezone.utc)


def evidence(**overrides):
    base = {
        "evidence_id": "e1",
        "source": "40-cycle",
        "symbol": "BTC-USDT-SWAP",
        "granularity": "per_symbol",
        "direction": "long",
        "confidence": 0.8,
        "horizon": "days",
        "intent": None,
        "ts": "2026-11-08T00:00:00Z",
        "expires_at": "2026-11-09T00:00:00Z",
        "provenance": "42-bus",
        "payload": {},
    }
    base.update(overrides)
    return base


# ── 角色四分 ────────────────────────────────────────────────────


def test_macro_force_sources_registered():
    assert "40-cycle" in MACRO_FORCE_SOURCES
    assert "43-strategic" in MACRO_FORCE_SOURCES
    assert "40-divergence" in MACRO_FORCE_SOURCES


def test_role_of_macro_force():
    assert role_of("40-cycle") == "macro_force"
    assert role_of("43-strategic") == "macro_force"
    assert role_of("40-divergence") == "macro_force"


# ── 权重表注册（G1 红线：R0 未完成前权重 = 0）──────────────────


def test_macro_force_weights_registered_but_zero_g1_redline():
    """权重表键必须注册（等比缩放用），但 R0 未完成前值为 0。"""
    assert "40-cycle" in SOURCE_WEIGHT_MAP
    assert "43-strategic" in SOURCE_WEIGHT_MAP
    assert "40-divergence" in SOURCE_WEIGHT_MAP
    # G1 红线：当前权重 0，不参与裁决
    assert SOURCE_WEIGHT_MAP["40-cycle"] == 0.0
    assert SOURCE_WEIGHT_MAP["43-strategic"] == 0.0
    assert SOURCE_WEIGHT_MAP["40-divergence"] == 0.0


def test_macro_force_dimension_is_d1_horizon_days():
    assert SOURCE_DIM_MAP["40-cycle"] == "D1"
    assert SOURCE_DIM_MAP["43-strategic"] == "D1"
    assert SOURCE_DIM_MAP["40-divergence"] == "D1"
    assert SOURCE_TF_MAP["40-cycle"] == "days"
    assert SOURCE_TF_MAP["43-strategic"] == "days"
    assert SOURCE_TF_MAP["40-divergence"] == "days"


# ── path_synthesis：macro_force 产 path ────────────────────────


def test_macro_force_source_generates_path_with_zero_weight():
    """macro_force 源产 path（D1/days），但权重为 0（G1 红线）。"""
    paths = synthesize_paths([evidence(source="40-cycle")], now=NOW)
    assert len(paths) == 1
    p = paths[0]
    assert p.source == "40-cycle"
    assert p.dimension == "D1"
    assert p.horizon == "days"
    # G1 红线：权重为 0
    assert p.metadata["weight"] == 0.0
    assert p.metadata["weight_raw"] == 0.0


def test_macro_force_path_does_not_influence_dimension_force():
    """权重为 0 的 macro_force path 对维度力量贡献为 0。"""
    from core.dimension_forces import aggregate_dimension_forces

    paths = synthesize_paths([evidence(source="40-cycle", confidence=0.9)], now=NOW)
    forces = aggregate_dimension_forces(paths)
    d1 = forces["D1"]
    # weight=0 → long_force=0 → neutral
    assert d1.long_force == 0.0
    assert d1.direction == "neutral"
    assert d1.strength == 0.0


def test_self_mirror_still_no_path():
    """self_mirror 角色（29-event / 23-contradiction）仍不产 path。"""
    paths = synthesize_paths(
        [evidence(source="29-event"), evidence(source="23-contradiction")],
        now=NOW,
    )
    assert paths == []
