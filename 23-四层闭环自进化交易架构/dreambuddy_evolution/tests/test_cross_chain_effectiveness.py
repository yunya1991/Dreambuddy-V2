"""横向双链路有效性验证（模拟数据）.

覆盖：
  1. 矛盾链 → L1 阻力场（当轮调制）与 Level0 代价变化
  2. 交叉验证链 → 路径评分 / 开仓阈值（纵向决策真实改变）
  3. 门禁状态跨周期累积 → 质变判定可达（缺陷 1 回归）
  4. head_multipliers 跨轮传入路径生成（横向→纵向回声）
  5. G 侧供给状态诊断（缺陷 2 可归因）
"""

from __future__ import annotations

import types

import numpy as np
import pytest

PATH_BASE = {
    "path_id": "p1",
    "source": "test",
    "direction": "long",
    "expected_return": 0.10,
    "confidence": 0.625,
    "resistance": 0.20,
}  # base score = 0.10 × 0.625 × 0.80 = 0.05


def _closes(n: int = 60, drift: float = 0.15, seed: int = 7) -> list[float]:
    rng = np.random.default_rng(seed)
    return list(100.0 + np.cumsum(rng.normal(drift, 1.0, n)))


def _rv_market_data() -> dict:
    return {
        "close": _closes(120),
        "high": [c * 1.01 for c in _closes(120)],
        "low": [c * 0.99 for c in _closes(120)],
        "volume": [1000.0] * 120,
        "okx_positions": {"long": 0.62, "short": 0.38},
        "liquidation_buy": [1.0, 2.0, 1.5],
        "liquidation_sell": [0.5, 0.8],
        "ma_200": 100.0,
    }


def _new_pipeline(tmp_path):
    from dreambuddy_evolution.evolution_pipeline import EvolutionPipeline

    return EvolutionPipeline(gene_root=tmp_path)


def _patch_contradiction(monkeypatch, dim="technical", direction="long", strength=0.0):
    from dreambuddy_evolution.core.contradiction_identifier import (
        PrimaryContradictionIdentifier,
    )

    monkeypatch.setattr(
        PrimaryContradictionIdentifier,
        "identify",
        lambda self, *a, **k: {
            "dimension": dim,
            "direction": direction,
            "strength": strength,
            "timeframe": "medium",
        },
    )


def _patch_a_dim(monkeypatch, a_dim: str):
    import dreambuddy_evolution.core.attention_shadow as att

    monkeypatch.setattr(
        att,
        "compute_a_dim_shadow",
        lambda pc: {"available": True, "a_dim_attention": a_dim, "source": "test"},
    )


def _patch_g_dim(monkeypatch, g_dim):
    from dreambuddy_evolution.core.granger_pipeline_adapter import GrangerPipelineAdapter

    monkeypatch.setattr(
        GrangerPipelineAdapter,
        "evaluate",
        lambda self, factors, returns: {
            "G_dim": g_dim,
            "G_confidence": 0.9 if g_dim else 0.0,
            "p_values": {"technical": 1e-4} if g_dim else {},
        },
    )


def _patch_cv_side_effects(monkeypatch):
    """隔离认知记录与基因创新等写盘副作用."""
    import dreambuddy_evolution.adapters.cognitive_bridge as cb
    from dreambuddy_evolution.evolution_pipeline import EvolutionPipeline

    monkeypatch.setattr(
        cb,
        "CognitiveBridge",
        lambda: types.SimpleNamespace(record_quality_change=lambda *a, **k: None),
    )
    monkeypatch.setattr(EvolutionPipeline, "_get_ftc_evolution_bridge", lambda self: None)
    monkeypatch.setattr(EvolutionPipeline, "_get_exogenous_evaluator", lambda self: None)
    monkeypatch.setenv("ENABLE_DIMENSION_FORCE_V2", "0")
    monkeypatch.setenv("ENABLE_HJB_SOLVER", "0")


def test_contradiction_chain_modulates_l1_resistance(tmp_path):
    """矛盾链当轮调制 R_up/R_down，并改变 Level0 代价."""
    from dreambuddy_evolution.core.level0_path_cost import compute_d_star
    from dreambuddy_evolution.core.resistance_vector import ResistanceVector

    md = _rv_market_data()
    rv = ResistanceVector()
    base = rv.calculate("BTC", md)
    mod = rv.calculate(
        "BTC",
        md,
        primary_contradiction={"direction": "long", "strength": 0.5, "dimension": "technical"},
    )

    assert mod["R_up"] < base["R_up"], "做多主矛盾应降低上行阻力"
    assert mod["R_down"] > base["R_down"], "做多主矛盾应抬高下行阻力"

    costs_base = compute_d_star(base)["costs"]
    costs_mod = compute_d_star(mod)["costs"]
    assert costs_mod["long"] < costs_base["long"]
    assert costs_mod["short"] > costs_base["short"]
    assert costs_mod != costs_base, "L1 变化必须传导到 Level0 代价"


def test_cv_chain_changes_path_score_and_entry_validation(monkeypatch, tmp_path):
    """G/A 一致 → ×1.15 通过验证；分歧 → ×0.9 且阈值上浮 → 不通过."""
    _patch_cv_side_effects(monkeypatch)
    _patch_contradiction(monkeypatch, dim="technical", strength=0.0)
    _patch_a_dim(monkeypatch, "technical")

    pipe_agree = _new_pipeline(tmp_path)
    _patch_g_dim(monkeypatch, "technical")
    agree = pipe_agree._select_optimal_path([dict(PATH_BASE)], {}, {"close": _closes(60)})
    assert agree["cross_validation"]["confidence_mult"] == pytest.approx(1.15)
    assert agree["statistical_validation"]["validated"] is True
    assert agree["optimal_path"]["score"] == pytest.approx(0.05 * 1.15, rel=1e-3)

    pipe_diverge = _new_pipeline(tmp_path)
    _patch_g_dim(monkeypatch, "fundamental")
    diverge = pipe_diverge._select_optimal_path([dict(PATH_BASE)], {}, {"close": _closes(60)})
    cv = diverge["cross_validation"]
    assert cv["confidence_mult"] == pytest.approx(0.9)
    assert cv["shift_signal"] is True
    assert diverge["optimal_path"] is None, "分歧惩罚后应不通过验证（等价 WAIT）"
    assert diverge["path_scores"][0]["score"] == pytest.approx(0.05 * 0.9, rel=1e-3)
    assert diverge["statistical_validation"]["validated"] is False
    assert diverge["statistical_validation"]["reason"] == "score_below_threshold"


def test_gate_state_accumulates_and_reaches_quality_change(monkeypatch, tmp_path):
    """门禁跨周期累积：连续分歧第 2 次即触达质变（persistence=2）."""
    import dreambuddy_evolution.core.structural_break_detector as sbd

    _patch_cv_side_effects(monkeypatch)
    _patch_contradiction(monkeypatch, dim="technical", strength=0.0)
    _patch_a_dim(monkeypatch, "technical")
    _patch_g_dim(monkeypatch, "fundamental")
    monkeypatch.setattr(
        sbd.StructuralBreakDetector, "detect_all", lambda self, prices: {"market_form_shift": True}
    )

    pipe = _new_pipeline(tmp_path)
    pipe._cv_persistence_threshold = 2
    pipe._cv_structural_break_threshold = 1.0
    md = {"close": _closes(60)}

    first = pipe._select_optimal_path([dict(PATH_BASE)], {}, md)["cross_validation"]
    second = pipe._select_optimal_path([dict(PATH_BASE)], {}, md)["cross_validation"]

    assert first["divergence_count"] == 1
    assert first["quality_change"] is False
    # 质变触发后 divergence_count 会归零，因此以 quality_change / trigger 为准
    assert second["quality_change"] is True
    assert second["granger_reestimate_trigger"] is True


def test_head_multipliers_cross_cycle_into_path_generation(monkeypatch, tmp_path):
    """分歧产生的 head 权重应跨轮传入下一轮路径生成（DeepReasoningEngine）."""
    from dreambuddy_evolution.evolution_pipeline import EvolutionPipeline

    _patch_cv_side_effects(monkeypatch)
    _patch_contradiction(monkeypatch, dim="technical", strength=0.0)
    _patch_a_dim(monkeypatch, "technical")
    _patch_g_dim(monkeypatch, "fundamental")

    calls: list[dict] = []

    class _FakeDR:
        def reason(self, **kwargs):
            calls.append(kwargs)
            return None

    monkeypatch.setattr(EvolutionPipeline, "_get_deep_reasoning", lambda self: _FakeDR())

    pipe = _new_pipeline(tmp_path)
    md = {"close": _closes(60)}
    pipe._select_optimal_path([dict(PATH_BASE)], {}, md)

    hm = pipe._last_head_multipliers
    assert hm is not None and np.any(np.asarray(hm) != 1.0), "分歧轮应产出非中性 head 权重"

    pipe._discover_paths(
        {"R_up": 0.4, "R_down": 0.6, "R_smooth": 0.5, "R_flow": 0.5, "R_reflexivity": 0.5},
        md,
        "BTC",
    )
    sent = [c.get("head_multipliers") for c in calls if "head_multipliers" in c]
    assert sent, "路径生成应收到 head_multipliers 参数"
    assert np.any(np.asarray(sent[0]) != 1.0), "横向 head 权重必须真实进入纵向路径生成"


def test_g_dim_supply_status_is_diagnosable(monkeypatch, tmp_path):
    """G 侧降级应可归因：无 close → no_price_series；短序列 → short_history."""
    _patch_cv_side_effects(monkeypatch)
    _patch_contradiction(monkeypatch, dim="technical", strength=0.0)
    _patch_a_dim(monkeypatch, "technical")
    _patch_g_dim(monkeypatch, None)

    pipe = _new_pipeline(tmp_path)
    empty = pipe._select_optimal_path([dict(PATH_BASE)], {}, {})["cross_validation"]
    assert empty["g_dim_status"] == "no_price_series"

    short = pipe._select_optimal_path([dict(PATH_BASE)], {}, {"close": _closes(40)})[
        "cross_validation"
    ]
    assert short["g_dim_status"] in {"short_history", "no_significant_granger"}
    assert "g_min_p" in short
