"""
RED 测试 — PipelineLoggingContext 组件契约
拆分目标: 从 evolution_pipeline.py _setup_logging(L41-69) 抽出
预期: 模块不存在，测试全部失败(ModuleNotFoundError)
"""
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))


def test_pipeline_logging_context_module_exists():
    """RED: PipelineLoggingContext 模块应可导入"""
    from dreambuddy_evolution.core.pipeline_logging_context import PipelineLoggingContext
    assert PipelineLoggingContext is not None


def test_pipeline_logging_context_configure_signature():
    """RED: configure() 方法签名存在"""
    from dreambuddy_evolution.core.pipeline_logging_context import PipelineLoggingContext
    ctx = PipelineLoggingContext()
    assert hasattr(ctx, "configure")
    assert callable(ctx.configure)


def test_pipeline_logging_context_get_logger_signature():
    """RED: get_logger() 方法签名存在"""
    from dreambuddy_evolution.core.pipeline_logging_context import PipelineLoggingContext
    ctx = PipelineLoggingContext()
    assert hasattr(ctx, "get_logger")
    assert callable(ctx.get_logger)
