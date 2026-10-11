"""RED 测试：DSH 新节点接入 — Task 7 PoE 节点扩展。

依据：TASKS-工程实践复现器.md TR-7.1 / TR-7.2 / TR-7.3
"""
import os
import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from dsh_nodes import (
    DSH_NODE_REGISTRY,
    S33_rea_audit,
    S33_rea_narrative,
    S33_rea_recover_decisions,
    dispatch,
)


UNCOMMENTED_CODE = "def fn():\n    x = 142\n    return x * 3.14\n"


# ---------- 测试用例 ----------


def test_s33_rea_audit_returns_valid_json():
    """TR-7.1: IPC 调用 S33_rea_audit 返回合法 JSON，含 target/evidence/known_gaps 字段。"""
    with tempfile.TemporaryDirectory() as d:
        Path(d, "ai_output.py").write_text(UNCOMMENTED_CODE)
        result = S33_rea_audit({"target": d})

        assert isinstance(result, dict)
        assert result["ok"] is True
        r = result["result"]
        assert "target" in r, "应含 target 字段 (TR-7.1)"
        assert "evidence" in r, "应含 evidence 字段 (TR-7.1)"
        assert "known_gaps" in r, "应含 known_gaps 字段 (TR-7.1)"
        # PoE 核心字段
        assert "poe_score" in r
        assert "gate_decision" in r


def test_s33_rea_recover_decisions_returns_valid_json():
    """S33_rea_recover_decisions 节点可调用。"""
    with tempfile.TemporaryDirectory() as d:
        os.makedirs(os.path.join(d, "models"))
        os.makedirs(os.path.join(d, "views"))
        os.makedirs(os.path.join(d, "controllers"))
        Path(d, "models", "__init__.py").write_text("")
        Path(d, "views", "__init__.py").write_text("")
        Path(d, "controllers", "__init__.py").write_text("")
        Path(d, "models", "user.py").write_text("class User:\n    pass\n")
        Path(d, "views", "v.py").write_text("class V:\n    pass\n")
        Path(d, "controllers", "c.py").write_text("class C:\n    pass\n")

        result = S33_rea_recover_decisions({"target": d})
        assert isinstance(result, dict)
        assert result["ok"] is True
        r = result["result"]
        assert "target" in r
        assert "decisions" in r
        assert len(r["decisions"]) >= 1


def test_s33_rea_narrative_returns_valid_json():
    """S33_rea_narrative 节点可调用。"""
    with tempfile.TemporaryDirectory() as d:
        # 非 git 仓库 → FAIL-OPEN 返回 unknown Evidence
        Path(d, "script.py").write_text("print('hello')\n")
        result = S33_rea_narrative({"target": d})
        assert isinstance(result, dict)
        assert result["ok"] is True
        r = result["result"]
        assert "target" in r
        assert "turning_points" in r
        assert "evidence" in r


def test_dsh_node_registry_contains_new_nodes():
    """TR-7.2: 3 个新节点均注册到 DSH 节点注册表。"""
    assert "s33_rea_audit" in DSH_NODE_REGISTRY, "应注册 s33_rea_audit (TR-7.2)"
    assert "s33_rea_recover_decisions" in DSH_NODE_REGISTRY, "应注册 s33_rea_recover_decisions"
    assert "s33_rea_narrative" in DSH_NODE_REGISTRY, "应注册 s33_rea_narrative"


def test_dispatch_can_route_new_nodes():
    """TR-7.2 附加: dispatch 可路由新节点。"""
    with tempfile.TemporaryDirectory() as d:
        Path(d, "ai.py").write_text(UNCOMMENTED_CODE)
        result = dispatch("s33_rea_audit", {"target": d})
        assert result["ok"] is True


def test_s33_rea_audit_failopen_on_error():
    """TR-7.3: 节点失败时返回含 level=unknown Evidence 的部分结果，不中断。"""
    result = S33_rea_audit({"target": "/nonexistent/path/xyz"})
    assert result["ok"] is True  # FAIL-OPEN: 返回 ok=True 但 result 含降级 Evidence
    r = result["result"]
    evidence_list = r.get("evidence", [])
    # 应含 level=unknown 的 Evidence
    has_unknown = False
    for e in evidence_list:
        level = e.get("level") if isinstance(e, dict) else getattr(e.level, "value", str(e.level))
        if level == "unknown":
            has_unknown = True
            break
    assert has_unknown, "失败时应含 level=unknown Evidence (TR-7.3)"


def test_s33_rea_audit_missing_target_returns_error():
    """无 target 参数应返回错误（不抛异常）。"""
    result = S33_rea_audit({})
    assert isinstance(result, dict)
    assert result["ok"] is False
    assert "error" in result


def test_s33_rea_audit_includes_known_gaps():
    """S33_rea_audit 结果应含 known_gaps 字段。"""
    with tempfile.TemporaryDirectory() as d:
        Path(d, "ai.py").write_text(UNCOMMENTED_CODE)
        result = S33_rea_audit({"target": d})
        assert result["ok"] is True
        assert "known_gaps" in result["result"]
        assert isinstance(result["result"]["known_gaps"], list)
