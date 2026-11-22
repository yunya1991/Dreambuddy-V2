#!/usr/bin/env python3
"""运行 59 副本的手机组件测试：mra.py 使用主仓实现，其余模块使用副本。

59 侧 `skill/scripts/mra.py` 是代理壳（只做子进程转发），而 `tests/` 是从主仓
同步来的、针对主仓单体 mra 实现编写的。为避免把实现复制回副本，本运行器在
主仓存在时预加载主仓 mra.py 为模块 `mra`，其余依赖模块仍从副本
`skill/scripts` 解析，从而让副本测试校验副本代码 + 主仓 mra。

主仓缺失时显式 SKIP（退出 0），与 `sync_mobile.py --check` 的降级口径一致。
"""

from __future__ import annotations

import importlib
import importlib.util
import os
import sys
import unittest
from pathlib import Path

MODULE_ROOT = Path(__file__).resolve().parents[1]
COMPONENT = MODULE_ROOT / "components" / "mobile-reservation-assist"
SCRIPTS = COMPONENT / "skill" / "scripts"
TESTS = COMPONENT / "tests"
DEFAULT_SOURCE = Path.home() / "Documents" / "顺风车业务"
CANONICAL_ROOT = Path("mobile-reservation-assist")
CANONICAL_MRA_REL = CANONICAL_ROOT / "skill" / "scripts" / "mra.py"
# 主仓 mra 依赖的兄弟模块：先从副本加载，确保测试校验的是副本实现
SIBLING_MODULES = (
    "brain",
    "cloud_data",
    "content_guard",
    "explore",
    "gateway",
    "ingest",
    "knowledge",
    "phone_driver",
    "phone_console",
    "phone_monitor",
    "regression",
    "registry",
    "security",
    "store",
    "twitter",
)


def source_root() -> Path:
    return Path(os.environ.get("SHUNFENGCHE_REPO", str(DEFAULT_SOURCE)))


def canonical_mra() -> Path:
    return source_root() / CANONICAL_MRA_REL


def load_copy_siblings() -> None:
    if str(SCRIPTS) not in sys.path:
        sys.path.insert(0, str(SCRIPTS))
    for name in SIBLING_MODULES:
        importlib.import_module(name)


def preload_canonical_mra() -> bool:
    path = canonical_mra()
    if not path.is_file():
        return False
    load_copy_siblings()
    spec = importlib.util.spec_from_file_location("mra", path)
    if spec is None or spec.loader is None:
        return False
    module = importlib.util.module_from_spec(spec)
    sys.modules["mra"] = module
    spec.loader.exec_module(module)
    # 主仓 mra 会把自身 scripts 目录插到 sys.path 首位；移除它并复位副本目录，
    # 保证测试后续导入的其余模块仍来自副本。
    canonical_scripts = path.parent.resolve()
    sys.path[:] = [item for item in sys.path if Path(item or ".").resolve() != canonical_scripts]
    while str(SCRIPTS) in sys.path:
        sys.path.remove(str(SCRIPTS))
    sys.path.insert(0, str(SCRIPTS))
    return True


def main() -> int:
    if not TESTS.is_dir():
        print("E_TESTS：未找到测试目录 {}".format(TESTS), file=sys.stderr)
        return 2
    if not preload_canonical_mra():
        print(
            "SKIP：未找到主仓 {}（可设置 SHUNFENGCHE_REPO），跳过手机组件测试".format(
                canonical_mra()
            ),
            file=sys.stderr,
        )
        return 0
    if str(TESTS) not in sys.path:
        sys.path.insert(0, str(TESTS))
    suite = unittest.TestLoader().discover(str(TESTS), pattern="test_*.py")
    result = unittest.TextTestRunner(verbosity=1).run(suite)
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    raise SystemExit(main())
