"""W5 Wire-up RED 测试 — PollingTrader 主流程接入验证.

Spec: docs/superpowers/specs/2026-09-21-washout-detector-design.md §9.5 (W5)

目标: 验证 PollingTrader 将 WashoutDetector / WashoutSLGuard / P3EarlyExit(注入) /
      WashoutHoldStrategy / is_trial 子池调用 / SLTP 调节 真正接入主流程.

RED 条件 (当前 polling_trader.py):
  - 未 import WashoutDetector / WashoutSLGuard / WashoutHoldStrategy
  - 无 ENABLE_WASHOUT_DETECTOR 类属性
  - 无 _init_washout_detector 方法
  - P3EarlyExitStrategy 实例化未注入 washout_detector
  - ExitManager.strategies 列表无 WashoutHoldStrategy
  - SLTP 决策未调用 WashoutSLGuard.adjust_sl()
  - _open_position is_trial 分支未调用 washout_detector.run()

GREEN 条件 (实现接入后):
  - 所有上述缺口补齐, ENABLE_WASHOUT_DETECTOR=False 时降级为 None / pass,
    链路字节等价 (HC-22).
"""
from __future__ import annotations

import ast
import sys
from pathlib import Path

import pytest

# ============================================================
# sys.path 设置 (与 test_washout_w5.py 一致)
# ============================================================
_THIS_DIR = Path(__file__).resolve().parent
_BCRM2_SCRIPTS_ROOT = _THIS_DIR.parent.parent  # .../11-易经推理系统/scripts
_PROJECT_ROOT = _BCRM2_SCRIPTS_ROOT.parent.parent  # dreambuddy-v2
_ARCH_ROOT = _PROJECT_ROOT / "1-ARCHITECTURE"

for _p in (_BCRM2_SCRIPTS_ROOT, _ARCH_ROOT):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))


# ============================================================
# 静态解析 polling_trader.py
# ============================================================
_POLLING_TRADER_PATH = (
    _BCRM2_SCRIPTS_ROOT / "memory_l4" / "polling_trader.py"
)


def _parse_polling_trader():
    """解析 polling_trader.py 源代码 + AST.

    Returns:
        (source_str, ast_tree)
    """
    source = _POLLING_TRADER_PATH.read_text(encoding="utf-8")
    tree = ast.parse(source)
    return source, tree


def _collect_imports(tree: ast.AST):
    """收集所有 import 语句中的名字."""
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            for alias in node.names:
                names.add(alias.name)
        elif isinstance(node, ast.Import):
            for alias in node.names:
                names.add(alias.name)
    return names


def _collect_class_attrs(tree: ast.AST, class_name: str = "PollingTrader"):
    """收集指定类的类属性赋值 (AnnAssign / Assign)."""
    attrs = set()
    methods = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == class_name:
            for stmt in node.body:
                if isinstance(stmt, ast.AnnAssign) and isinstance(stmt.target, ast.Name):
                    attrs.add(stmt.target.id)
                elif isinstance(stmt, ast.Assign):
                    for tgt in stmt.targets:
                        if isinstance(tgt, ast.Name):
                            attrs.add(tgt.id)
                if isinstance(stmt, ast.FunctionDef):
                    methods.add(stmt.name)
    return attrs, methods


def _find_call_with_kwarg(source: str, func_name: str, kwarg_name: str) -> bool:
    """源代码中是否存在 `func_name(... kwarg_name=...)` 调用."""
    # 简化: 查找 `func_name(` 出现后附近是否有 `kwarg_name=`
    # 用 ast 更可靠
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            func = node.func
            func_id = None
            if isinstance(func, ast.Name):
                func_id = func.id
            elif isinstance(func, ast.Attribute):
                func_id = func.attr
            if func_id == func_name:
                for kw in node.keywords:
                    if kw.arg == kwarg_name:
                        return True
    return False


# ============================================================
# RED 测试: Import 接入
# ============================================================
class TestWashoutWireupImports:
    """验证 polling_trader.py 导入了 W5 组件."""

    def test_imports_washout_detector(self):
        """WashoutDetector 应被导入."""
        _, tree = _parse_polling_trader()
        imports = _collect_imports(tree)
        assert "WashoutDetector" in imports, (
            "polling_trader.py 未导入 WashoutDetector — W5 主流程接入缺失"
        )

    def test_imports_washout_sl_guard(self):
        """WashoutSLGuard 应被导入."""
        _, tree = _parse_polling_trader()
        imports = _collect_imports(tree)
        assert "WashoutSLGuard" in imports, (
            "polling_trader.py 未导入 WashoutSLGuard — Layer 1 SLTP 调节器未接入"
        )

    def test_imports_washout_hold_strategy(self):
        """WashoutHoldStrategy 应被导入 (从 exit_strategies)."""
        _, tree = _parse_polling_trader()
        imports = _collect_imports(tree)
        assert "WashoutHoldStrategy" in imports, (
            "polling_trader.py 未导入 WashoutHoldStrategy — Layer 3 持有策略未注册"
        )


# ============================================================
# RED 测试: 类属性 + 方法
# ============================================================
class TestWashoutWireupClassAttrs:
    """验证 PollingTrader 类有 W5 相关属性和方法."""

    def test_has_enable_washout_detector_attr(self):
        """PollingTrader 应有 ENABLE_WASHOUT_DETECTOR 类属性 (默认 False)."""
        _, tree = _parse_polling_trader()
        attrs, _ = _collect_class_attrs(tree)
        assert "ENABLE_WASHOUT_DETECTOR" in attrs, (
            "PollingTrader 缺少 ENABLE_WASHOUT_DETECTOR 类属性 — 开关架构未落地"
        )

    def test_has_init_washout_detector_method(self):
        """PollingTrader 应有 _init_washout_detector 方法."""
        _, tree = _parse_polling_trader()
        _, methods = _collect_class_attrs(tree)
        assert "_init_washout_detector" in methods, (
            "PollingTrader 缺少 _init_washout_detector 方法 — 实例化入口未实现"
        )

    def test_has_washout_sl_guard_method(self):
        """PollingTrader 应有 _apply_washout_sl_guard 方法 (SLTP 调节入口)."""
        _, tree = _parse_polling_trader()
        _, methods = _collect_class_attrs(tree)
        # 方法名候选: _apply_washout_sl_guard / _init_washout_sl_guard
        assert (
            "_apply_washout_sl_guard" in methods
            or "_init_washout_sl_guard" in methods
        ), (
            "PollingTrader 缺少 _apply_washout_sl_guard / _init_washout_sl_guard 方法"
        )


# ============================================================
# RED 测试: P3EarlyExit 注入 washout_detector
# ============================================================
class TestWashoutWireupP3EarlyExit:
    """验证 P3EarlyExitStrategy 实例化时注入 washout_detector."""

    def test_p3_early_exit_injected_washout_detector(self):
        """P3EarlyExitStrategy(...) 调用应包含 washout_detector= 参数."""
        source, _ = _parse_polling_trader()
        assert _find_call_with_kwarg(source, "P3EarlyExitStrategy", "washout_detector"), (
            "P3EarlyExitStrategy 实例化未传入 washout_detector= — Layer 2 洗盘感知未注入"
        )


# ============================================================
# RED 测试: WashoutHoldStrategy 注册到 ExitManager
# ============================================================
class TestWashoutWireupHoldStrategy:
    """验证 WashoutHoldStrategy 出现在 ExitManager strategies 列表."""

    def test_washout_hold_strategy_in_exit_manager(self):
        """ExitManager strategies 列表应包含 WashoutHoldStrategy 实例化."""
        source, _ = _parse_polling_trader()
        # 查找 `WashoutHoldStrategy(` 调用 (实例化)
        assert "WashoutHoldStrategy(" in source, (
            "ExitManager.strategies 列表未包含 WashoutHoldStrategy(...) — Layer 3 未注册"
        )


# ============================================================
# RED 测试: SLTP 决策附近调用 WashoutSLGuard.adjust_sl()
# ============================================================
class TestWashoutWireupSLTPGuard:
    """验证 SLTP 检查附近调用 WashoutSLGuard.adjust_sl()."""

    def test_adjust_sl_called_in_sltp_flow(self):
        """_adjust_sl_tp 或 SLTP 决策附近应调用 .adjust_sl()."""
        source, _ = _parse_polling_trader()
        # 查找 self._washout_sl_guard.adjust_sl( 或 _sl_guard.adjust_sl( 等
        # 至少有 `adjust_sl(` 调用, 且上下文与 washout 相关
        assert "adjust_sl(" in source, (
            "SLTP 流程未调用 WashoutSLGuard.adjust_sl() — Layer 1 SLTP 调节未接入"
        )


# ============================================================
# RED 测试: is_trial 分支调用 washout_detector.run()
# ============================================================
class TestWashoutWireupTrialRun:
    """验证 _open_position is_trial=True 分支调用 washout_detector.run()."""

    def test_washout_detector_run_called_in_open_position(self):
        """_open_position 方法内应调用 self._washout_detector.run(...)."""
        source, tree = _parse_polling_trader()
        # 在 PollingTrader 类的 _open_position 方法源代码中查找
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef) and node.name == "PollingTrader":
                for stmt in node.body:
                    if isinstance(stmt, ast.FunctionDef) and stmt.name == "_open_position":
                        method_src = ast.get_source_segment(source, stmt) or ""
                        assert "_washout_detector" in method_src, (
                            "_open_position 方法未引用 _washout_detector — is_trial 分支未接入洗盘判定"
                        )
                        return
        pytest.fail("未找到 PollingTrader._open_position 方法")


# ============================================================
# GREEN 烟雾测试: ENABLE_WASHOUT_DETECTOR=False 时降级
# ============================================================
class TestWashoutWireupDefaultDisabled:
    """验证默认开关关闭时, 实例化不抛异常且属性为 None."""

    def test_init_washout_detector_returns_none_when_disabled(self):
        """_init_washout_detector(ENABLE_WASHOUT_DETECTOR=False) → self._washout_detector is None."""
        # 用 __new__ 绕过 __init__, 仅测试 _init_washout_detector 方法
        from scripts.memory_l4.polling_trader import PollingTrader
        trader = PollingTrader.__new__(PollingTrader)
        # 默认类属性
        assert PollingTrader.ENABLE_WASHOUT_DETECTOR is False
        # 调用 _init_washout_detector 方法
        if hasattr(PollingTrader, "_init_washout_detector"):
            trader._init_washout_detector()
            assert getattr(trader, "_washout_detector", None) is None
            assert getattr(trader, "_washout_sl_guard", None) is None
