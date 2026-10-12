"""
RED 测试 — PathDiscoveryService 组件契约
拆分目标: 从 evolution_pipeline.py _discover_paths/_select_optimal_path/_apply_high_order_factors 抽出
预期: 模块不存在，测试全部失败(ModuleNotFoundError)
"""
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))


def test_path_discovery_service_module_exists():
    """RED: PathDiscoveryService 模块应可导入"""
    from dreambuddy_evolution.core.path_discovery_service import PathDiscoveryService
    assert PathDiscoveryService is not None


def test_path_discovery_service_discover_paths_signature():
    """RED: discover_paths() 方法签名存在"""
    from dreambuddy_evolution.core.path_discovery_service import PathDiscoveryService
    pds = PathDiscoveryService()
    assert hasattr(pds, "discover_paths")
    assert callable(pds.discover_paths)


def test_path_discovery_service_select_optimal_path_signature():
    """RED: select_optimal_path() 方法签名存在"""
    from dreambuddy_evolution.core.path_discovery_service import PathDiscoveryService
    pds = PathDiscoveryService()
    assert hasattr(pds, "select_optimal_path")
    assert callable(pds.select_optimal_path)


def test_path_discovery_service_apply_high_order_factors_signature():
    """RED: apply_high_order_factors() 方法签名存在"""
    from dreambuddy_evolution.core.path_discovery_service import PathDiscoveryService
    pds = PathDiscoveryService()
    assert hasattr(pds, "apply_high_order_factors")
    assert callable(pds.apply_high_order_factors)
