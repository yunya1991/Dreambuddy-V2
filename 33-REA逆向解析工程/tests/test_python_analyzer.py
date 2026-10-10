"""RED 测试：PythonAnalyzer — Python AST 分析器。"""
import sys
import tempfile
import os
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from core.python_analyzer import PythonAnalyzer


SAMPLE_PY = '''
import os
from pathlib import Path
import json as js

CONST = 42

class MyClass:
    """示例类。"""
    def method_a(self, x: int) -> str:
        return str(x)

    @staticmethod
    def method_b():
        pass

def func_a(a, b=1):
    """函数A。"""
    return a + b

def func_b():
    result = func_a(1, 2)
    return result
'''


def test_python_analyzer_extracts_modules_classes_functions():
    """RED: 应提取模块导入、类、函数。"""
    with tempfile.TemporaryDirectory() as d:
        f = os.path.join(d, "sample.py")
        Path(f).write_text(SAMPLE_PY)

        analyzer = PythonAnalyzer()
        result = analyzer.analyze(f)

        raw = result.raw
        # 导入
        imports = raw.get("imports", [])
        assert any(i["module"] == "os" for i in imports)
        assert any(i["module"] == "pathlib" and "Path" in i.get("names", []) for i in imports)
        # 类
        classes = raw.get("classes", [])
        assert any(c["name"] == "MyClass" for c in classes)
        # 函数
        functions = raw.get("functions", [])
        func_names = [fn["name"] for fn in functions]
        assert "func_a" in func_names
        assert "func_b" in func_names


def test_python_analyzer_returns_evidence():
    """RED: 分析结果应包含 evidence（provenance + confidence + known_gaps）。"""
    with tempfile.TemporaryDirectory() as d:
        f = os.path.join(d, "sample.py")
        Path(f).write_text(SAMPLE_PY)

        analyzer = PythonAnalyzer()
        result = analyzer.analyze(f)

        assert len(result.evidence) > 0
        e0 = result.evidence[0]
        assert e0.provenance is not None
        assert 0.0 <= e0.confidence <= 1.0
        assert isinstance(e0.known_gaps, list)


def test_python_analyzer_known_gaps_for_dynamic_calls():
    """RED: known_gaps 应标注动态调用无法静态解析的局限。"""
    with tempfile.TemporaryDirectory() as d:
        f = os.path.join(d, "sample.py")
        Path(f).write_text(SAMPLE_PY)

        analyzer = PythonAnalyzer()
        result = analyzer.analyze(f)

        all_gaps = []
        for e in result.evidence:
            all_gaps.extend(e.known_gaps)
        # 应有关于动态调用的局限说明
        assert any("动态" in g or "dynamic" in g.lower() for g in all_gaps)
