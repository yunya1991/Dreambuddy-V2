"""WP-R1 测试：dimension_forces（N1）+ contradiction（N2）。

SPEC-M1 M4/M5：50 复刻 23 矛盾框架设计口径（独立实现，不 import 23）。
"""

from __future__ import annotations

from core.contradiction import identify_primary_contradiction
from core.dimension_forces import DimensionForce, aggregate_dimension_forces
from core.path_synthesis import Path


def _path(
    source="11-bcrm",
    symbol="BTC-USDT-SWAP",
    direction="long",
    confidence=0.8,
    dimension="D3",
    horizon="hours",
    weight=0.15,
    path_id=None,
):
    return Path(
        path_id=path_id or f"{source}-{symbol}-{direction}",
        source=source,
        symbol=symbol,
        direction=direction,
        confidence=confidence,
        expected_return=0.0,
        resistance=0.0,
        continuation_score=0.0,
        dimension=dimension,
        horizon=horizon,
        intent="trend",
        metadata={"weight": weight, "weight_raw": weight, "source_path_count": 1},
    )


# ── N1: dimension_forces ──────────────────────────────────────────


def test_n1_single_dimension_long_force():
    paths = [_path(direction="long", confidence=0.8, weight=0.15, dimension="D3")]
    forces = aggregate_dimension_forces(paths)
    d3 = forces["D3"]
    assert d3.direction == "long"
    assert d3.strength == 0.8 * 0.15
    assert d3.long_force == 0.8 * 0.15
    assert d3.short_force == 0.0
    assert d3.path_count == 1


def test_n1_mixed_directions_net_to_short():
    paths = [
        _path(direction="long", confidence=0.5, weight=0.15, dimension="D3"),
        _path(direction="short", confidence=0.9, weight=0.20, dimension="D3"),
    ]
    d3 = aggregate_dimension_forces(paths)["D3"]
    assert d3.long_force == 0.5 * 0.15
    assert d3.short_force == 0.9 * 0.20
    assert d3.direction == "short"
    assert d3.strength == d3.short_force - d3.long_force


def test_n1_empty_paths_returns_empty():
    assert aggregate_dimension_forces([]) == {}


def test_n1_dimension_without_paths_is_neutral():
    paths = [_path(dimension="D3")]
    forces = aggregate_dimension_forces(paths)
    assert set(forces.keys()) == {"D3"}
    # D2/D4 等无源维度不出现（仅聚合有 path 的维度）
    assert "D2" not in forces
    assert forces["D3"].degraded is None


def test_n1_neutral_when_long_equals_short():
    paths = [
        _path(direction="long", confidence=0.5, weight=0.2),
        _path(direction="short", confidence=0.5, weight=0.2),
    ]
    d3 = aggregate_dimension_forces(paths)["D3"]
    assert d3.direction == "neutral"
    assert d3.strength == 0.0


def test_n1_strength_clamped_at_one():
    # 多条高置信同带路力量叠加，strength 截断 [0,1]
    paths = [
        _path(direction="long", confidence=1.0, weight=0.6),
        _path(direction="long", confidence=1.0, weight=0.6),
    ]
    d3 = aggregate_dimension_forces(paths)["D3"]
    assert d3.long_force == 1.2
    assert d3.strength == 1.0


# ── N2: contradiction 三步法 ─────────────────────────────────────


def _force(dim, direction, strength, path_count=3):
    return DimensionForce(
        dimension=dim,
        direction=direction,
        strength=strength,
        long_force=strength if direction == "long" else 0.0,
        short_force=strength if direction == "short" else 0.0,
        path_count=path_count,
        degraded=None,
    )


def test_n2_all_dims_agree_resonance():
    forces = {
        "D1": _force("D1", "long", 0.6),
        "D3": _force("D3", "long", 0.7),
        "D4": _force("D4", "long", 0.5),
    }
    result = identify_primary_contradiction(forces)
    assert result["type"] == "resonance"
    assert result["direction"] == "long"
    assert result["resonance"] == 1.0
    assert result["strength"] == 1.0


def test_n2_majority_below_threshold_triggers_conflict():
    # 3 维中 2 看多 1 看空 → 共振 2/3 ≈ 0.667 ≥ 0.6 仍是共振
    forces = {
        "D1": _force("D1", "long", 0.5),
        "D3": _force("D3", "long", 0.5),
        "D4": _force("D4", "short", 0.8),
    }
    result = identify_primary_contradiction(forces)
    # 2/3 = 0.667 ≥ 0.6 → resonance
    assert result["type"] == "resonance"
    assert result["direction"] == "long"


def test_n2_conflict_picks_strongest_dimension():
    # 4 维：2 看多 2 看空 → 共振 0.5 < 0.6 → 冲突裁决
    forces = {
        "D1": _force("D1", "long", 0.3),
        "D2": _force("D2", "short", 0.9),
        "D3": _force("D3", "long", 0.4),
        "D4": _force("D4", "short", 0.5),
    }
    result = identify_primary_contradiction(forces)
    assert result["type"] == "conflict"
    # D2 力量最强 → 主导维度
    assert result["leader_dimension"] == "D2"
    assert result["direction"] == "short"


def test_n2_dominance_when_leader_exceeds_half():
    # 单维力量碾压 → dominant=True
    forces = {
        "D1": _force("D1", "long", 0.9, path_count=10),
        "D3": _force("D3", "short", 0.1, path_count=2),
    }
    result = identify_primary_contradiction(forces)
    assert result["dominant"] is True


def test_n2_single_dimension_resonance():
    forces = {"D3": _force("D3", "short", 0.7)}
    result = identify_primary_contradiction(forces)
    assert result["type"] == "resonance"
    assert result["direction"] == "short"
    assert result["resonance"] == 1.0


def test_n2_no_forces_returns_neutral():
    result = identify_primary_contradiction({})
    assert result["type"] == "neutral"
    assert result["direction"] == "neutral"
    assert result["strength"] == 0.0


def test_n2_all_neutral_returns_neutral():
    forces = {
        "D1": _force("D1", "neutral", 0.0),
        "D3": _force("D3", "neutral", 0.0),
    }
    result = identify_primary_contradiction(forces)
    assert result["type"] == "neutral"
