"""RED 测试：DSH S33 节点 — S33_rea_analyze / S33_rea_trace / S33_rea_compare。"""
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from dsh_nodes import S33_rea_analyze, S33_rea_trace, S33_rea_compare, DSH_NODE_REGISTRY, dispatch


SAMPLE_PY = '''
import os
from pathlib import Path

class UserService:
    """用户服务。"""
    def login(self, username: str) -> bool:
        return True

    def logout(self) -> None:
        pass

def main():
    svc = UserService()
    svc.login("admin")
    return svc

if __name__ == "__main__":
    main()
'''


def _make_sample_project(tmpdir: str) -> str:
    """创建测试用 Python 项目目录。"""
    f = os.path.join(tmpdir, "app.py")
    Path(f).write_text(SAMPLE_PY)
    return tmpdir


def test_s33_rea_analyze_returns_structure():
    """RED: S33_rea_analyze 应返回 SubagentOutput 结构。"""
    with tempfile.TemporaryDirectory() as d:
        _make_sample_project(d)
        result = S33_rea_analyze({"target": d, "scope": "architecture"})
        assert "node" in result
        assert "ok" in result
        assert "result" in result
        assert "ts" in result


def test_s33_rea_analyze_ok_has_evidence():
    """RED: 成功分析应包含 evidence 和 summary。"""
    with tempfile.TemporaryDirectory() as d:
        _make_sample_project(d)
        result = S33_rea_analyze({"target": d, "scope": "architecture"})
        assert result["ok"] is True
        r = result["result"]
        assert "summary" in r
        assert "evidence" in r
        assert len(r["evidence"]) > 0


def test_s33_rea_analyze_missing_target():
    """RED: 缺少 target 参数应返回 ok=False。"""
    result = S33_rea_analyze({})
    assert result["ok"] is False
    assert "error" in result


def test_s33_rea_trace_returns_call_chain():
    """RED: S33_rea_trace 应返回调用链结构。"""
    with tempfile.TemporaryDirectory() as d:
        _make_sample_project(d)
        result = S33_rea_trace({"target": d, "feature": "用户登录"})
        assert "node" in result
        assert result["ok"] is True
        r = result["result"]
        assert "feature" in r
        assert "call_chain" in r or "evidence" in r


def test_s33_rea_trace_with_entry():
    """RED: 指定 entry 应追踪该函数调用链。"""
    with tempfile.TemporaryDirectory() as d:
        _make_sample_project(d)
        result = S33_rea_trace({"target": d, "feature": "主流程", "entry": "main"})
        assert result["ok"] is True
        r = result["result"]
        assert "call_chain" in r or "evidence" in r


def test_s33_rea_trace_missing_target():
    """RED: 缺少 target 应返回 ok=False。"""
    result = S33_rea_trace({"feature": "test"})
    assert result["ok"] is False
    assert "error" in result


def test_s33_rea_compare_returns_structure():
    """RED: S33_rea_compare 应返回对比结构。"""
    with tempfile.TemporaryDirectory() as d1, tempfile.TemporaryDirectory() as d2:
        _make_sample_project(d1)
        Path(os.path.join(d2, "app.py")).write_text("print('hello')\n")
        result = S33_rea_compare({"target_a": d1, "target_b": d2, "feature": "架构"})
        assert "node" in result
        assert result["ok"] is True
        r = result["result"]
        assert "common" in r or "differences" in r or "evidence_a" in r


def test_s33_rea_compare_missing_targets():
    """RED: 缺少 target 参数应返回 ok=False。"""
    result = S33_rea_compare({"target_a": "/tmp/a"})
    assert result["ok"] is False
    assert "error" in result


def test_dsh_node_registry_contains_three_nodes():
    """RED: DSH_NODE_REGISTRY 应包含三个 S33 节点。"""
    assert "s33_rea_analyze" in DSH_NODE_REGISTRY
    assert "s33_rea_trace" in DSH_NODE_REGISTRY
    assert "s33_rea_compare" in DSH_NODE_REGISTRY


def test_dispatch_routes_s33_methods():
    """RED: dispatch 应正确路由 s33_* 方法。"""
    with tempfile.TemporaryDirectory() as d:
        _make_sample_project(d)
        result = dispatch("s33_rea_analyze", {"target": d, "scope": "architecture"})
        assert result["ok"] is True


def test_dispatch_unknown_method():
    """RED: dispatch 未知方法应返回 ok=False。"""
    result = dispatch("s33_unknown", {})
    assert result["ok"] is False
    assert "unknown_method" in result.get("error", "")
