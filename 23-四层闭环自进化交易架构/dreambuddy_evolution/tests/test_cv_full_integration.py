"""TDD-CV-FULL: Granger + head_multipliers 完整接入测试."""
import inspect


def test_deep_reasoning_reason_supports_head_multipliers():
    """deep_reasoning_engine.reason 应支持 head_multipliers 参数."""
    from dreambuddy_evolution.engines.deep_reasoning_engine import DeepReasoningEngine
    sig = inspect.signature(DeepReasoningEngine.reason)
    assert "head_multipliers" in sig.parameters


def test_pipeline_has_granger_history():
    """evolution_pipeline 应维护 Granger 历史缓冲."""
    from dreambuddy_evolution.evolution_pipeline import EvolutionPipeline
    src = inspect.getsource(EvolutionPipeline._select_optimal_path)
    assert "GrangerPipelineAdapter" in src
    # 应有历史缓冲或价格序列用于 Granger
    assert "close" in src or "price" in src


def test_pipeline_passes_head_multipliers_to_reason():
    """路径发现阶段应将上一轮 head_multipliers 传入 reason."""
    from dreambuddy_evolution.evolution_pipeline import EvolutionPipeline
    src = inspect.getsource(EvolutionPipeline)
    assert "head_multipliers" in src
    assert "_last_head_multipliers" in src


def test_granger_switch_enabled():
    """enable_granger_pipeline 应已开启."""
    from dreambuddy_evolution.agi_config import get_switch
    assert get_switch("enable_granger_pipeline", False) is True


def test_head_multipliers_switch_enabled():
    """enable_head_multipliers_adjustment 应已开启."""
    from dreambuddy_evolution.agi_config import get_switch
    assert get_switch("enable_head_multipliers_adjustment", False) is True
