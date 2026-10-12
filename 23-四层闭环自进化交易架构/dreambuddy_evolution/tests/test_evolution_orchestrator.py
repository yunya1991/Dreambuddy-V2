"""
RED 测试 — EvolutionOrchestrator 组件契约
拆分目标: 从 evolution_pipeline.py run_symbol 主流程抽出
预期: 模块不存在，测试全部失败(ModuleNotFoundError)
"""
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))


def test_evolution_orchestrator_module_exists():
    """RED: EvolutionOrchestrator 模块应可导入"""
    from dreambuddy_evolution.core.evolution_orchestrator import EvolutionOrchestrator
    assert EvolutionOrchestrator is not None


def test_evolution_orchestrator_run_symbol_signature():
    """RED: run_symbol() 方法签名存在"""
    from dreambuddy_evolution.core.evolution_orchestrator import EvolutionOrchestrator
    orch = EvolutionOrchestrator()
    assert hasattr(orch, "run_symbol")
    assert callable(orch.run_symbol)


def test_evolution_orchestrator_get_feedback_signature():
    """RED: get_feedback() 方法签名存在"""
    from dreambuddy_evolution.core.evolution_orchestrator import EvolutionOrchestrator
    orch = EvolutionOrchestrator()
    assert hasattr(orch, "get_feedback")
    assert callable(orch.get_feedback)
