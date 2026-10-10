"""RED 测试：S33_rea_investigate DSH 节点 — 工作流节点扩展。"""
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from dsh_nodes import (
    S33_rea_investigate,
    DSH_NODE_REGISTRY,
    dispatch,
)


SAMPLE_PROJECT = '''
def main():
    """入口函数。"""
    data = load_data()
    result = process(data)
    return result

def load_data():
    return [1, 2, 3]

def process(data):
    total = 0
    for x in data:
        total += x
    return total
'''


def test_s33_investigate_registered_in_registry():
    """RED: S33_rea_investigate 应注册在 DSH_NODE_REGISTRY。"""
    assert "s33_rea_investigate" in DSH_NODE_REGISTRY
    assert DSH_NODE_REGISTRY["s33_rea_investigate"] is S33_rea_investigate


def test_s33_investigate_basic():
    """RED: 应执行完整逆向调查工作流。"""
    with tempfile.TemporaryDirectory() as d:
        Path(os.path.join(d, "main.py")).write_text(SAMPLE_PROJECT.strip())
        result = S33_rea_investigate({"target": d})

    assert result["ok"] is True
    assert "summary" in result["result"]
    assert "evidence" in result["result"]


def test_s33_investigate_returns_phases():
    """RED: 结果应包含四阶段。"""
    with tempfile.TemporaryDirectory() as d:
        Path(os.path.join(d, "main.py")).write_text(SAMPLE_PROJECT.strip())
        result = S33_rea_investigate({"target": d})

    phases = result["result"].get("phases", {})
    assert "locate" in phases
    assert "trace" in phases
    assert "reduce" in phases
    assert "annotate" in phases


def test_s33_investigate_with_feature_and_entry():
    """RED: 支持 feature + entry 参数。"""
    with tempfile.TemporaryDirectory() as d:
        Path(os.path.join(d, "main.py")).write_text(SAMPLE_PROJECT.strip())
        result = S33_rea_investigate({
            "target": d,
            "feature": "数据处理",
            "entry": "main",
        })

    assert result["ok"] is True
    assert result["result"].get("feature") == "数据处理"


def test_s33_investigate_missing_target():
    """RED: 缺少 target 应返回错误。"""
    result = S33_rea_investigate({})
    assert result["ok"] is False
    assert "missing_target" in result.get("error", "") or "target" in result.get("error", "").lower()


def test_s33_investigate_invalid_target():
    """RED: 无效目标应降级返回。"""
    result = S33_rea_investigate({"target": "/nonexistent/path/xyz"})
    assert result["ok"] is False or (
        result["ok"] is True and len(result["result"].get("evidence", [])) > 0
    )


def test_s33_investigate_trace_id():
    """RED: 应支持 trace_id 参数。"""
    with tempfile.TemporaryDirectory() as d:
        Path(os.path.join(d, "main.py")).write_text("def main():\n    return 1\n")
        result = S33_rea_investigate({
            "target": d,
            "trace_id": "test_trace_001",
        })

    assert result["trace_id"] == "test_trace_001"


def test_s33_investigate_dispatch():
    """RED: dispatch 应路由到 S33_rea_investigate。"""
    with tempfile.TemporaryDirectory() as d:
        Path(os.path.join(d, "main.py")).write_text("def main():\n    return 1\n")
        result = dispatch("s33_rea_investigate", {"target": d})

    assert result["node"] == "S33_rea_investigate"


def test_s33_investigate_returns_cognitive_params():
    """RED: 结果应包含认知记忆 record 参数。"""
    with tempfile.TemporaryDirectory() as d:
        Path(os.path.join(d, "main.py")).write_text(SAMPLE_PROJECT.strip())
        result = S33_rea_investigate({"target": d})

    assert "cognitive_record" in result["result"]
    cr = result["result"]["cognitive_record"]
    assert "content" in cr
    assert "quality_level" in cr
    assert "tags" in cr


def test_s33_investigate_single_file():
    """RED: 应支持单文件分析。"""
    with tempfile.TemporaryDirectory() as d:
        f = os.path.join(d, "single.py")
        Path(f).write_text("def main():\n    return 42\n")
        result = S33_rea_investigate({"target": f})

    assert result["ok"] is True
