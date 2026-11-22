"""
RED 测试 — PipelineLoggingContext 组件契约
拆分目标: 从 evolution_pipeline.py _setup_logging(L41-69) 抽出
预期: 模块不存在，测试全部失败(ModuleNotFoundError)
"""

import sys  # noqa: I001
from pathlib import Path

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


def _reset_pkg_handlers():
    import logging

    for h in list(logging.getLogger("dreambuddy_evolution").handlers):
        logging.getLogger("dreambuddy_evolution").removeHandler(h)
        try:
            h.close()
        except Exception:  # noqa: BLE001
            pass


def test_external_rotate_uses_plain_file_handler(tmp_path, monkeypatch):
    """EVOLUTION_LOG_ROTATE=external → 交给 logrotate，进程内不再 RotatingFileHandler。"""
    import logging
    from logging.handlers import RotatingFileHandler

    from dreambuddy_evolution.core.pipeline_logging_context import PipelineLoggingContext

    monkeypatch.setenv("EVOLUTION_LOG_ROTATE", "external")
    _reset_pkg_handlers()
    try:
        PipelineLoggingContext(log_dir=tmp_path).configure()
        handlers = logging.getLogger("dreambuddy_evolution").handlers
        assert handlers and not any(isinstance(h, RotatingFileHandler) for h in handlers)
    finally:
        _reset_pkg_handlers()


def test_default_rotate_uses_rotating_handler(tmp_path, monkeypatch):
    """未设置外部轮转时保持进程内 10MB 轮转。"""
    import logging
    from logging.handlers import RotatingFileHandler

    from dreambuddy_evolution.core.pipeline_logging_context import PipelineLoggingContext

    monkeypatch.delenv("EVOLUTION_LOG_ROTATE", raising=False)
    _reset_pkg_handlers()
    try:
        PipelineLoggingContext(log_dir=tmp_path).configure()
        handlers = logging.getLogger("dreambuddy_evolution").handlers
        assert any(isinstance(h, RotatingFileHandler) for h in handlers)
    finally:
        _reset_pkg_handlers()
