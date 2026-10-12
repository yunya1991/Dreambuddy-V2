"""
RED 测试 — WeightStore 组件契约
拆分目标: 从 evolution_pipeline.py _load_weight_factors/_save_weight_factors/_get_wf_for_dim 抽出
预期: 模块不存在，测试全部失败(ModuleNotFoundError)
"""
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))


def test_weight_store_module_exists():
    """RED: WeightStore 模块应可导入"""
    from dreambuddy_evolution.core.weight_store import WeightStore
    assert WeightStore is not None


def test_weight_store_load_signature():
    """RED: load() 方法签名存在"""
    from dreambuddy_evolution.core.weight_store import WeightStore
    ws = WeightStore()
    assert hasattr(ws, "load")
    assert callable(ws.load)


def test_weight_store_save_signature():
    """RED: save() 方法签名存在"""
    from dreambuddy_evolution.core.weight_store import WeightStore
    ws = WeightStore()
    assert hasattr(ws, "save")
    assert callable(ws.save)


def test_weight_store_atomic_update_signature():
    """RED: atomic_update() 方法签名存在"""
    from dreambuddy_evolution.core.weight_store import WeightStore
    ws = WeightStore()
    assert hasattr(ws, "atomic_update")
    assert callable(ws.atomic_update)
