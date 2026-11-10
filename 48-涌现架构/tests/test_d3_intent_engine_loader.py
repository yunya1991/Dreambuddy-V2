"""D3 IntentEngine 轻量导入器测试（P1-3）。

验证：
  - load_intent_engine() 返回 IntentEngine 实例
  - recognize() 可调用并返回非空 intent_type（B1 规则基线，无需 LLM）
  - flask 缺失时抛出带安装指引的 ImportError
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

BASELINES = Path(__file__).resolve().parents[1] / "baselines"


def _load_loader():
    spec = importlib.util.spec_from_file_location(
        "d3_intent_engine_loader", BASELINES / "d3_intent_engine_loader.py"
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


loader = _load_loader()


def test_load_intent_engine_returns_instance():
    engine = loader.load_intent_engine(use_llm_based=False)
    assert engine is not None
    assert engine.__class__.__name__ == "IntentEngine"


def test_recognize_returns_intent_type():
    engine = loader.load_intent_engine(use_llm_based=False)
    result = engine.recognize(user_message="分析BTC趋势")
    assert result.intent_type
    assert isinstance(result.confidence, (int, float))


def test_smoke_passes():
    assert loader.smoke() is True


def test_flask_missing_raises_clear_error():
    """flask 未装时应抛出带安装指引的 ImportError。"""
    real_flask = sys.modules.pop("flask", None)
    sys.modules["flask"] = None  # 模拟 flask 不可用
    try:
        with pytest.raises(ImportError, match="flask"):
            loader._check_flask()
    finally:
        if real_flask is not None:
            sys.modules["flask"] = real_flask
        else:
            sys.modules.pop("flask", None)
