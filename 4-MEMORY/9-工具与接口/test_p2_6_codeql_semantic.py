"""P2-6 CodeQL 语义分析 TDD RED 测试

借鉴 CodeQL（跨过程数据流 + 污点追踪），将 33-REA 的 AST 分析
升级到语义级：
  1. 变量定义-使用链（data flow）
  2. 未定义变量使用检测
  3. 污点追踪（source → sink）
  4. 调用图构建

RED 契约:
  1. codeql_semantic 模块不存在 → ImportError
  2. CodeQLSemanticAnalyzer 类不存在
  3. analyze() 不存在
  4. track_data_flow() 不存在
  5. find_undefined_usage() 不存在
  6. trace_taint() 不存在
  7. CognitiveLoopEntry 无 codeql 属性

参考: SPEC-CognitiveSystem-Evolution.md §4.3 P2-6
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_SCRIPT_DIR = Path(__file__).resolve().parent
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))


SAMPLE_SOURCE = """
import os

def process_data(data):
    result = data.upper()
    return result

def main():
    raw = os.getenv("INPUT")
    processed = process_data(raw)
    print(processed)
"""

UNDEFINED_SOURCE = """
def foo():
    x = 1
    return y  # y 未定义
"""


class TestCodeQLSemanticCore:
    """CodeQL 语义分析核心能力。"""

    def test_import_codeql(self):
        """RED: codeql_semantic 模块可导入。"""
        from codeql_semantic import CodeQLSemanticAnalyzer  # noqa: F401

    def test_analyze_parses_source(self):
        """RED: analyze() 解析源码并返回语义模型。"""
        from codeql_semantic import CodeQLSemanticAnalyzer

        analyzer = CodeQLSemanticAnalyzer()
        model = analyzer.analyze(SAMPLE_SOURCE)

        assert model is not None
        assert "functions" in model
        assert "imports" in model

    def test_track_data_flow(self):
        """RED: track_data_flow() 返回变量定义-使用链。"""
        from codeql_semantic import CodeQLSemanticAnalyzer

        analyzer = CodeQLSemanticAnalyzer()
        analyzer.analyze(SAMPLE_SOURCE)
        flow = analyzer.track_data_flow()

        assert isinstance(flow, dict)
        # 应有变量定义
        assert len(flow) > 0

    def test_find_undefined_usage(self):
        """RED: find_undefined_usage() 检测未定义变量使用。"""
        from codeql_semantic import CodeQLSemanticAnalyzer

        analyzer = CodeQLSemanticAnalyzer()
        analyzer.analyze(UNDEFINED_SOURCE)
        undefined = analyzer.find_undefined_usage()

        # y 在 foo 中未定义
        names = [u["name"] for u in undefined]
        assert "y" in names

    def test_trace_taint(self):
        """RED: trace_taint() 追踪从 source 到 sink 的数据流。"""
        from codeql_semantic import CodeQLSemanticAnalyzer

        analyzer = CodeQLSemanticAnalyzer()
        analyzer.analyze(SAMPLE_SOURCE)
        # source: os.getenv, sink: print
        taint = analyzer.trace_taint(source="os.getenv", sink="print")

        assert isinstance(taint, dict)
        assert "reachable" in taint

    def test_get_call_graph(self):
        """RED: get_call_graph() 返回函数调用图。"""
        from codeql_semantic import CodeQLSemanticAnalyzer

        analyzer = CodeQLSemanticAnalyzer()
        analyzer.analyze(SAMPLE_SOURCE)
        graph = analyzer.get_call_graph()

        assert isinstance(graph, dict)
        # main 应调用 process_data
        assert "main" in graph
        callees = graph["main"]
        assert "process_data" in callees or any("process_data" in c for c in callees)

    def test_failopen_invalid_syntax(self):
        """RED: 无效语法 → FAIL-OPEN 不抛异常。"""
        from codeql_semantic import CodeQLSemanticAnalyzer

        analyzer = CodeQLSemanticAnalyzer()
        model = analyzer.analyze("def broken(:")  # 无效语法
        assert model is not None

    def test_failopen_empty_source(self):
        """RED: 空源码 → FAIL-OPEN。"""
        from codeql_semantic import CodeQLSemanticAnalyzer

        analyzer = CodeQLSemanticAnalyzer()
        model = analyzer.analyze("")
        assert model is not None

    def test_analyze_returns_functions(self):
        """RED: analyze() 返回的 functions 包含函数名。"""
        from codeql_semantic import CodeQLSemanticAnalyzer

        analyzer = CodeQLSemanticAnalyzer()
        model = analyzer.analyze(SAMPLE_SOURCE)

        func_names = [f["name"] for f in model["functions"]]
        assert "process_data" in func_names
        assert "main" in func_names


class TestCognitiveLoopEntryCodeQL:
    """CognitiveLoopEntry P2-6 集成点。"""

    def test_codeql_attribute_exists(self):
        """RED: CognitiveLoopEntry 应有 codeql 属性。"""
        from cognitive_loop_entry import CognitiveLoopEntry

        import inspect

        src = inspect.getsource(CognitiveLoopEntry.__init__)
        assert "codeql" in src
        assert "CodeQLSemanticAnalyzer" in src
