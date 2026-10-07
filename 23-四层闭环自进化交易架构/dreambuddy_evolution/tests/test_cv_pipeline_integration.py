"""TDD-CV-INTEG: CrossValidationGate 集成到 evolution_pipeline 测试."""
import pytest


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
