"""RED 测试：AlgorithmReducer — 关键算法还原（AST模式匹配）。"""
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from core.algorithm_reducer import reduce_algorithm


RECURSION_SAMPLE = '''
def factorial(n):
    if n <= 1:
        return 1
    return n * factorial(n - 1)

def fibonacci(n):
    if n <= 1:
        return n
    return fibonacci(n - 1) + fibonacci(n - 2)
'''

ITERATION_SAMPLE = '''
def sum_list(items):
    total = 0
    for item in items:
        total += item
    return total

def find_max(items):
    result = items[0]
    for item in items:
        if item > result:
            result = item
    return result
'''


def test_reduce_algorithm_recursion_detected():
    """RED: 应检测到递归模式。"""
    with tempfile.TemporaryDirectory() as d:
        f = os.path.join(d, "recursion.py")
        Path(f).write_text(RECURSION_SAMPLE)
        result = reduce_algorithm(f, "factorial")
        assert "patterns" in result
        assert any("递归" in p.get("type", "") or "recursion" in p.get("type", "").lower()
                    for p in result["patterns"])


def test_reduce_algorithm_iteration_detected():
    """RED: 应检测到迭代模式。"""
    with tempfile.TemporaryDirectory() as d:
        f = os.path.join(d, "iteration.py")
        Path(f).write_text(ITERATION_SAMPLE)
        result = reduce_algorithm(f, "sum_list")
        assert "patterns" in result
        assert any("迭代" in p.get("type", "") or "iteration" in p.get("type", "").lower()
                    for p in result["patterns"])


def test_reduce_algorithm_returns_pseudo_code():
    """RED: 应返回伪代码描述。"""
    with tempfile.TemporaryDirectory() as d:
        f = os.path.join(d, "recursion.py")
        Path(f).write_text(RECURSION_SAMPLE)
        result = reduce_algorithm(f, "factorial")
        assert "pseudo_code" in result
        assert len(result["pseudo_code"]) > 0


def test_reduce_algorithm_returns_evidence():
    """RED: 应返回 Evidence 列表。"""
    with tempfile.TemporaryDirectory() as d:
        f = os.path.join(d, "recursion.py")
        Path(f).write_text(RECURSION_SAMPLE)
        result = reduce_algorithm(f, "factorial")
        assert "evidence" in result
        assert len(result["evidence"]) > 0
        e = result["evidence"][0]
        assert e.provenance is not None
        assert isinstance(e.known_gaps, list)


def test_reduce_algorithm_all_functions():
    """RED: 不指定 function_name 时分析全部函数。"""
    with tempfile.TemporaryDirectory() as d:
        f = os.path.join(d, "recursion.py")
        Path(f).write_text(RECURSION_SAMPLE)
        result = reduce_algorithm(f)
        assert "functions" in result
        assert len(result["functions"]) >= 2  # factorial + fibonacci


def test_reduce_algorithm_nonexistent_file():
    """RED: 文件不存在应降级返回 + Evidence。"""
    result = reduce_algorithm("/nonexistent/file.py", "func")
    assert "evidence" in result
    assert len(result["evidence"]) > 0


def test_reduce_algorithm_accumulator_pattern():
    """RED: 应检测到累加器模式（total += item）。"""
    with tempfile.TemporaryDirectory() as d:
        f = os.path.join(d, "iteration.py")
        Path(f).write_text(ITERATION_SAMPLE)
        result = reduce_algorithm(f, "sum_list")
        assert "patterns" in result
        # 累加器或迭代模式
        assert len(result["patterns"]) > 0
