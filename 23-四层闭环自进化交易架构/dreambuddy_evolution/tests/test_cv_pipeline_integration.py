"""TDD-CV-INTEG: CrossValidationGate 集成到 evolution_pipeline 测试."""


def test_cross_validation_gate_switch_exists():
    """agi_config 中应有 enable_cross_validation_gate 开关且已激活."""
    from dreambuddy_evolution.agi_config import AGI_SWITCHES, get_switch

    assert "enable_cross_validation_gate" in AGI_SWITCHES
    # 2026-10-07 已激活 (5框架对比+消融实验验证通过)
    assert get_switch("enable_cross_validation_gate", False) is True


def test_cross_validation_gate_in_select_optimal_path():
    """_select_optimal_path 应包含 CrossValidationGate 调用（开关开启时）."""
    import inspect

    from dreambuddy_evolution.evolution_pipeline import EvolutionPipeline

    src = inspect.getsource(EvolutionPipeline._select_optimal_path)
    # 集成点：CrossValidationGate 应被引用
    assert "CrossValidationGate" in src
    assert "confidence_mult" in src


def test_cross_validation_gate_fail_open_when_disabled():
    """开关关闭时，_select_optimal_path 不调用 CrossValidationGate，confidence_mult=1.0."""
    import inspect

    from dreambuddy_evolution.evolution_pipeline import EvolutionPipeline

    src = inspect.getsource(EvolutionPipeline._select_optimal_path)
    # 应有 FAIL-OPEN 默认值
    assert "1.0" in src  # confidence_mult 默认值
    # 应有开关检查
    assert "enable_cross_validation_gate" in src


def test_select_optimal_path_returns_cv_result():
    """_select_optimal_path 返回值应包含 cross_validation 字段."""
    import inspect

    from dreambuddy_evolution.evolution_pipeline import EvolutionPipeline

    src = inspect.getsource(EvolutionPipeline._select_optimal_path)
    assert "cross_validation" in src


def test_cv_gate_instance_reused_across_cycles(monkeypatch, tmp_path):
    """CrossValidationGate 实例应跨周期复用，divergence_count 才能累积到质变阈值."""
    import dreambuddy_evolution.core.cross_validation_gate as cvg

    created = {"n": 0}
    real_gate = cvg.CrossValidationGate

    class _CountingGate(real_gate):
        def __init__(self, *args, **kwargs):
            created["n"] += 1
            super().__init__(*args, **kwargs)

    monkeypatch.setattr(cvg, "CrossValidationGate", _CountingGate)
    monkeypatch.setenv("ENABLE_DIMENSION_FORCE_V2", "0")

    from dreambuddy_evolution.core.contradiction_identifier import (
        PrimaryContradictionIdentifier,
    )
    from dreambuddy_evolution.evolution_pipeline import EvolutionPipeline

    monkeypatch.setattr(
        PrimaryContradictionIdentifier,
        "identify",
        lambda self, *a, **k: {
            "dimension": "C8",
            "direction": "long",
            "strength": 0.30,
            "timeframe": "medium",
        },
    )

    pipe = EvolutionPipeline(gene_root=tmp_path)
    paths = [
        {
            "path_id": "p1",
            "source": "test",
            "direction": "long",
            "expected_return": 0.02,
            "confidence": 0.60,
            "resistance": 0.20,
        }
    ]
    r_out = {
        "R_up": 0.40,
        "R_down": 0.60,
        "R_smooth": 0.50,
        "R_flow": 0.50,
        "R_reflexivity": 0.50,
        "quality_score": 0.90,
    }

    pipe._select_optimal_path(paths, r_out, {})
    first = getattr(pipe, "_cross_validation_gate", None)
    pipe._select_optimal_path(paths, r_out, {})
    second = getattr(pipe, "_cross_validation_gate", None)

    assert first is not None, "开关开启且主矛盾存在时应建立门禁实例"
    assert second is first, "第二次寻优必须复用同一门禁实例（状态累积）"
    assert created["n"] == 1, f"门禁只应构造一次，实际 {created['n']} 次"
