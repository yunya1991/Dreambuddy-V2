"""
项目级 pytest 配置 - 统一测试框架入口
支持多子系统测试发现和运行
"""
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).parent

SUBMODULES = [
    "14-V15经典马丁策略",
    "13-通用风控模块",
    "12-三屏趋势系统",
    "11-易经推理系统",
    "19-数据访问层",  # DAL 统一数据访问层（P0 新加入，便于全局 pytest 发现 import dreambuddy_dal）
]

for submodule in SUBMODULES:
    submodule_path = ROOT_DIR / submodule
    if submodule_path.exists():
        lib_path = submodule_path / "lib"
        core_path = submodule_path / "core"
        if lib_path.exists():
            sys.path.insert(0, str(lib_path))
        if core_path.exists():
            sys.path.insert(0, str(core_path))
        sys.path.insert(0, str(submodule_path))


def pytest_configure(config):
    """pytest 配置钩子 - 注册自定义标记"""
    config.addinivalue_line(
        "markers", "slow: marks tests as slow (deselect with '-m \"not slow\"')"
    )
    config.addinivalue_line(
        "markers", "integration: marks tests as integration tests"
    )
    config.addinivalue_line(
        "markers", "e2e: marks tests as end-to-end tests"
    )
    config.addinivalue_line(
        "markers", "stress: marks tests as stress tests"
    )
