"""RED → GREEN: Python 3.9 兼容性修复（PEP 604 `X | Y` + `zip(strict=)`）。

Bug 重现（v15_20260901.log）:
  - TypeError: unsupported operand type(s) for |: 'type' and 'NoneType'
    → 每币种【开仓异常】【加仓异常】吃掉HYPE/MSTR/ETH/SOL/BNB/OKB/…所有信号
  - TypeError: zip() takes no keyword arguments
    → 调用期strict=True/False只在Python 3.10+生效，3.9抛错

修复验证：
  1. capital_manager._resolve_v15_budget_pool 的注解 float | None 引发的 import-time TypeError 消失
  2. 所有交易代码路径中 zip(..., strict=False) 被改为 zip(...)（strict kwarg 移除）
  3. 运行get_type_hints对实盘关键函数不再触发 | TypeError
"""
import importlib
import os
import sys
import typing
from pathlib import Path

V15_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(V15_ROOT))

TRADING_CORE_FILES = [
    "lib/capital_manager.py",
    "lib/strategy_params.py",
    "core/v15_trader.py",
    "lib/okx_client.py",
    "core/ai_boundary_scaler.py",
    "lib/phase_d_gateway.py",
]


def _count_kwarg_in_file(rel: str, kw: str) -> int:
    """统计某文件中 `zip(...)` 调用里指定关键字参数的数量。"""
    p = V15_ROOT / rel
    if not p.exists():
        return 0
    import ast
    tree = ast.parse(p.read_text())
    count = 0
    for node in ast.walk(tree):
        if (isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id == "zip"):
            if any(k.arg == kw for k in node.keywords):
                count += 1
    return count


# ── RED 1 ─────────────────────────────────────────────
def test_capital_manager_budget_pool_import_and_type_hints_ok():
    """capital_manager._resolve_v15_budget_pool 函数签名的类型注解在 3.9 下
    不会再触发 'unsupported operand |: type and NoneType'。"""
    mod = importlib.import_module("lib.capital_manager")
    importlib.reload(mod)
    fn = getattr(mod, "_resolve_v15_budget_pool", None)
    assert fn is not None, "_resolve_v15_budget_pool 缺失"
    # 以下在3.9 里若签名仍为 float | None 会抛 TypeError
    hints = typing.get_type_hints(fn)
    assert "v15_used_usd" in hints
    # Union/Optional 解析后会是 (float, NoneType) 或单类型
    annotation = hints["v15_used_usd"]
    origin = getattr(annotation, "__origin__", None)
    args = getattr(annotation, "__args__", ())
    assert origin is typing.Union or type(None) in args or annotation is float, \
        f"期望 Union/Optional/float，实际={annotation!r}"


# ── RED 2 ─────────────────────────────────────────────
def test_trading_core_has_no_zip_strict_kwarg():
    """实盘核心6文件中不得含有 zip(..., strict=...) 调用（3.9不支持strict karg）。"""
    offenders = []
    for rel in TRADING_CORE_FILES:
        c = _count_kwarg_in_file(rel, "strict")
        if c:
            offenders.append(f"{rel}:{c}处")
    assert not offenders, f"实盘核心文件里仍存在zip(..., strict=): {offenders}"


# ── RED 3 ─────────────────────────────────────────────
def test_ai_boundary_scaler_init_type_hints_ok():
    """core/ai_boundary_scaler BoundaryStateStore.__init__ 的注解在 3.9 安全解析。"""
    mod = importlib.import_module("core.ai_boundary_scaler")
    importlib.reload(mod)
    hints = typing.get_type_hints(mod.BoundaryStateStore.__init__)
    assert "state_file" in hints
    sf = hints["state_file"]
    origin = getattr(sf, "__origin__", None)
    # 期望 Union[str, os.PathLike] / Optional[...] 等3.9原生形式，不是 PEP 604
    assert origin is typing.Union or sf is str, f"state_file注解={sf!r}"


# ── RED 4 ─────────────────────────────────────────────
def test_offline_scripts_also_no_zip_strict_kwarg():
    """v15_backtest/bayesian_optimize_timing也移除 strict kwarg，避免离线跑3.9崩。"""
    offline = [
        "core/v15_backtest.py",
        "bayesian_optimize_timing.py",
        "phase_d_dataset_generator.py",
    ]
    offenders = []
    for rel in offline:
        c = _count_kwarg_in_file(rel, "strict")
        if c:
            offenders.append(f"{rel}:{c}处")
    assert not offenders, f"离线脚本zip(strict=)未清理: {offenders}"


# ── RED 5 ─────────────────────────────────────────────
def test_dataset_generator_and_test_files_union_not_pep604():
    """离线脚本/测试里的 str | Path / dict | None 也改为 typing.Union/Optional，
    保证import不崩。"""
    import ast
    risky = []
    for rel in [
        "phase_d_dataset_generator.py",
        "tests/v15_stress_test.py",
        "tests/test_v15_budget_pool_dynamic.py",
    ]:
        p = V15_ROOT / rel
        if not p.exists():
            continue
        for node in ast.walk(ast.parse(p.read_text())):
            # 扫描函数参数注解 / 返回注解里的 BinOp(bit_or)
            ann = None
            if isinstance(node, ast.arg):
                ann = node.annotation
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                ann = node.returns
            if isinstance(ann, ast.BinOp) and isinstance(ann.op, ast.BitOr):
                risky.append(f"{rel}:{getattr(ann, 'lineno', '?')} 发现PEP604注解")
    assert not risky, f"仍有PEP604 '|' 注解: {risky}"
