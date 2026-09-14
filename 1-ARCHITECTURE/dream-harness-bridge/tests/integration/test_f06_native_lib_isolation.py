#!/usr/bin/env python3
"""F-06: Python 原生库惰性隔离 — 测试

测试目标:
1. lazy_import_heavy("cv2") 不崩溃（成功 import 或返回 None）
2. lazy_import_heavy("不存在的库") 返回 None（FAIL-OPEN）
3. 重原生库不在模块级 import（检查 __all__ 或模块属性）
4. 模块级 import 只有轻量库（json/sys/os/time/uuid/traceback）

来源: SPEC v0.3 七补.1 F-06
调研: 记忆 VM-1789089211280（segfault 源于 cv2/numpy ABI 不兼容）
"""

import json
import os
import subprocess
import sys

import pytest

SERVER_DIR = os.path.join(
    os.path.dirname(__file__), "..", "..", "packages", "python-server"
)
sys.path.insert(0, SERVER_DIR)

from server import lazy_import_heavy  # noqa: E402


# 重原生库白名单（绝不允许出现在模块级 import）
HEAVY_NATIVE_LIBS = ["cv2", "numpy", "causalml", "shap", "torch", "tensorflow"]
# 允许的轻量级模块级 import
LIGHTWEIGHT_LIBS = ["json", "sys", "os", "time", "uuid", "traceback"]


def _run_in_subprocess(script: str) -> subprocess.CompletedProcess:
    """在全新子进程中执行脚本，确保模块级 import 检查不受当前进程污染"""
    env = os.environ.copy()
    env["PYTHONPATH"] = SERVER_DIR + os.pathsep + env.get("PYTHONPATH", "")
    return subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True,
        text=True,
        cwd=SERVER_DIR,
        env=env,
    )


class TestF06LazyImportHeavy:
    """F-06: lazy_import_heavy 惰性导入"""

    def test_lazy_import_cv2_not_crash(self):
        """lazy_import_heavy("cv2") 不崩溃（成功 import 或返回 None）"""
        result = lazy_import_heavy("cv2")
        # FAIL-OPEN: 要么成功 import 返回模块，要么返回 None
        assert result is None or hasattr(result, "__name__")

    def test_lazy_import_nonexistent_lib_returns_none(self):
        """lazy_import_heavy("不存在的库") 返回 None（FAIL-OPEN）"""
        result = lazy_import_heavy("definitely_not_a_real_lib_xyz123")
        assert result is None

    def test_lazy_import_failure_does_not_raise(self):
        """lazy_import_heavy 失败时不抛异常，静默返回 None"""
        # 多次调用不存在的库都不抛异常
        for lib in ["nope_a", "nope_b", "nope_c"]:
            result = lazy_import_heavy(lib)
            assert result is None


class TestF06ModuleLevelIsolation:
    """F-06: 重原生库不在模块级 import"""

    def test_heavy_native_libs_not_in_module_level(self):
        """重原生库（cv2/numpy/causalml/shap）不在模块级 import

        在全新子进程中 import server，检查 sys.modules 不含重原生库。
        """
        script = (
            "import sys, json; "
            "import server; "
            f"heavy = {HEAVY_NATIVE_LIBS!r}; "
            "loaded = [m for m in heavy if m in sys.modules]; "
            "print(json.dumps(loaded))"
        )
        result = _run_in_subprocess(script)
        assert result.returncode == 0, (
            f"子进程 import server 失败: stderr={result.stderr}"
        )
        loaded_heavy = json.loads(result.stdout.strip())
        assert loaded_heavy == [], (
            f"模块级 import 了重原生库: {loaded_heavy}"
        )

    def test_heavy_libs_not_module_attributes(self):
        """重原生库不是 server 模块的属性"""
        import server

        for lib in HEAVY_NATIVE_LIBS:
            assert not hasattr(server, lib), (
                f"server 模块级暴露了重原生库属性: {lib}"
            )

    def test_module_level_imports_only_lightweight(self):
        """模块级 import 只有轻量库（json/sys/os/time/uuid/traceback）"""
        script = (
            "import sys, json; "
            "import server; "
            f"lightweight = {LIGHTWEIGHT_LIBS!r}; "
            "missing = [m for m in lightweight if m not in sys.modules]; "
            "print(json.dumps(missing))"
        )
        result = _run_in_subprocess(script)
        assert result.returncode == 0, (
            f"子进程 import server 失败: stderr={result.stderr}"
        )
        missing_light = json.loads(result.stdout.strip())
        assert missing_light == [], (
            f"轻量库未被 import: {missing_light}"
        )

    def test_no_top_level_heavy_import_in_source(self):
        """server.py 源码模块级不包含重原生库的 import 语句"""
        import inspect
        import server

        source = inspect.getsource(server)
        lines = source.splitlines()
        # 收集模块级（非缩进）的 import 行
        module_level_imports = []
        for line in lines:
            stripped = line.lstrip()
            # 跳过空行、注释、装饰器、函数/类定义后的内容
            if not stripped or stripped.startswith("#"):
                continue
            # 只看顶格（无缩进）的 import 行
            if not line.startswith(" ") and not line.startswith("\t"):
                if stripped.startswith("import ") or stripped.startswith(
                    "from "
                ):
                    module_level_imports.append(stripped)

        for lib in HEAVY_NATIVE_LIBS:
            for imp_line in module_level_imports:
                # 排除在函数内 / 字符串中的情况（已通过缩进过滤）
                # 检查是否直接 import 了重库
                assert not (
                    f"import {lib}" in imp_line or f"from {lib}" in imp_line
                ), (
                    f"server.py 模块级 import 了重原生库: {imp_line}"
                )
