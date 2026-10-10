"""RED 测试：集成测试 — 端到端分析 dreambuddy 自身模块。"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from core.python_analyzer import PythonAnalyzer
from core.dependency_graph import DependencyGraph
from core.call_chain_tracer import CallChainTracer
from core.git_history import trace_git_history
from core.algorithm_reducer import reduce_algorithm
from core.dependency_audit import audit_dependencies
from dsh_nodes import S33_rea_analyze, S33_rea_trace, S33_rea_compare

# 用 33-REA 自身做端到端测试目标
REA_DIR = str(Path(__file__).parent.parent)
REA_CORE = str(Path(__file__).parent.parent / "core")
REA_DSH = str(Path(__file__).parent.parent / "dsh_nodes.py")


def test_e2e_python_analyzer_on_self():
    """RED: PythonAnalyzer 应能分析 33-REA 自身的核心模块。"""
    analyzer = PythonAnalyzer()
    result = analyzer.analyze(REA_DSH)
    assert result.summary != ""
    assert len(result.evidence) > 0
    # 应检测到 import 语句
    assert len(result.raw.get("imports", [])) > 0
    # 应检测到函数
    assert len(result.raw.get("functions", [])) > 0


def test_e2e_dependency_graph_on_core():
    """RED: DependencyGraph 应能分析 33-REA/core 目录。"""
    graph = DependencyGraph()
    result = graph.build(REA_CORE)
    assert len(result["nodes"]) > 0
    assert len(result["evidence"]) > 0
    # core 内部应有模块间依赖
    assert len(result["adjacency"]) > 0


def test_e2e_call_chain_tracer_on_core():
    """RED: CallChainTracer 应能追踪 33-REA/core 内部调用链。"""
    tracer = CallChainTracer()
    result = tracer.trace(REA_CORE)
    assert len(result["all_functions"]) > 0
    assert len(result["evidence"]) > 0


def test_e2e_git_history_on_self():
    """RED: Git历史溯源应能分析 33-REA 自身文件。"""
    result = trace_git_history(REA_DIR, REA_DSH)
    assert "evidence" in result
    assert len(result["evidence"]) > 0
    # 应检测到至少一次提交（commit c0cd8c9b8d/9fcb957d6f）
    assert result["change_count"] >= 1


def test_e2e_algorithm_reducer_on_self():
    """RED: 算法还原应能分析 33-REA 自身的函数。"""
    result = reduce_algorithm(REA_DSH)
    assert "functions" in result
    assert len(result["functions"]) > 0


def test_e2e_dependency_audit_on_self():
    """RED: 依赖审计应能分析 33-REA 根目录。"""
    result = audit_dependencies(REA_DIR)
    assert "evidence" in result
    assert len(result["evidence"]) > 0


def test_e2e_dsh_analyze_full_pipeline():
    """RED: S33_rea_analyze 端到端应能分析整个 33-REA 工程。"""
    result = S33_rea_analyze({"target": REA_DIR, "scope": "full"})
    assert result["ok"] is True
    r = result["result"]
    assert "summary" in r
    assert "evidence" in r
    assert len(r["evidence"]) > 0


def test_e2e_dsh_trace_on_real_function():
    """RED: S33_rea_trace 应能追踪 33-REA 中的真实函数。"""
    result = S33_rea_trace({
        "target": REA_CORE,
        "feature": "依赖图构建",
        "entry": "build",
    })
    assert result["ok"] is True
    r = result["result"]
    assert "call_chain" in r or "evidence" in r


def test_e2e_dsh_compare_self_vs_self():
    """RED: S33_rea_compare 应能对比 33-REA/core vs 33-REA/tests。"""
    tests_dir = str(Path(__file__).parent.parent / "tests")
    result = S33_rea_compare({
        "target_a": REA_CORE,
        "target_b": tests_dir,
        "feature": "架构对比",
    })
    assert result["ok"] is True
