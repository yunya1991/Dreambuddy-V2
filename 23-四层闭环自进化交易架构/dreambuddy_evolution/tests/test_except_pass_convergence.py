"""
P1-3 RED: except pass 收敛 safe_call 契约测试
来源: SPEC v0.3 §P1-3 — except pass 合计 ≤ 15 (grep/AST 验证)

验收口径:
- 全包（排除 tests/ scripts/ __pycache__）AST 统计 except-pass 对 ≤ 15
- 两个热点文件 (data_center.py / evolution_pipeline.py) except-pass 归零
- primary_contradiction_detector.py except-pass 归零
"""
from __future__ import annotations

import ast
from pathlib import Path

# 包根目录
_PKG_ROOT = Path(__file__).resolve().parent.parent

# 排除目录
_EXCLUDE_DIRS = {"tests", "__pycache__", ".git", "scripts", "data"}

# 收敛阈值 (SPEC P1-3: except pass 合计 ≤ 15)
_THRESHOLD = 15


def _count_except_pass(path: Path) -> int:
    """AST 统计单文件 except-pass 对数量"""
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except (SyntaxError, UnicodeDecodeError):
        return 0
    count = 0
    for node in ast.walk(tree):
        if isinstance(node, ast.ExceptHandler):
            if len(node.body) == 1 and isinstance(node.body[0], ast.Pass):
                count += 1
    return count


def _iter_pkg_py_files():
    for p in _PKG_ROOT.rglob("*.py"):
        if any(part in _EXCLUDE_DIRS for part in p.parts):
            continue
        yield p


class TestExceptPassConvergence:
    """SPEC P1-3: except pass 收敛验收"""

    def test_total_except_pass_below_threshold(self):
        """全包 except-pass 合计 ≤ 15"""
        total = sum(_count_except_pass(p) for p in _iter_pkg_py_files())
        assert total <= _THRESHOLD, (
            f"except-pass 合计 {total} > 阈值 {_THRESHOLD}，需收敛到 safe_call 或加日志"
        )

    def test_hotspot_data_center_converged(self):
        """热点1: adapters/data_center.py except-pass 归零"""
        f = _PKG_ROOT / "adapters" / "data_center.py"
        count = _count_except_pass(f)
        assert count == 0, f"data_center.py 仍有 {count} 个 except-pass"

    def test_hotspot_evolution_pipeline_converged(self):
        """热点2: evolution_pipeline.py except-pass 归零"""
        f = _PKG_ROOT / "evolution_pipeline.py"
        count = _count_except_pass(f)
        assert count == 0, f"evolution_pipeline.py 仍有 {count} 个 except-pass"

    def test_hotspot_primary_contradiction_converged(self):
        """热点3: engines/primary_contradiction_detector.py except-pass 归零"""
        f = _PKG_ROOT / "engines" / "primary_contradiction_detector.py"
        count = _count_except_pass(f)
        assert count == 0, f"primary_contradiction_detector.py 仍有 {count} 个 except-pass"

    def test_safe_call_importable_and_usable(self):
        """safe_call 可导入且异常时返回 fallback（收敛基础设施就绪）"""
        from dreambuddy_evolution.core.safe_call import safe_call

        def _crash():
            raise RuntimeError("boom")

        assert safe_call(_crash, fallback="safe") == "safe"
        assert safe_call(lambda x: x * 2, fallback=0, x=5) == 10
