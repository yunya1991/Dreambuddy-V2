"""H2: tool_set 影子 sidecar（hcp-1.0）— hash / version / diff / 审批绑定

对齐 56/SPEC-56-H v0.3 §4.2（P1 前影子阶段）:
  - v1.0 `tool_set.schema.json` 不动，旁路写 `tool_set.hcp.json`
  - hash 对排序后的 tools canonical JSON 计算，同会话同 mode 稳定
  - 变更才出新 version + diff；无变更沿用原 version
  - 审批必须引用同一 tool_set_hash，且签发时间晚于 generated_at
  - len(tools) ≤ 15（max_tools_per_shell）
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import pytest

BASE = Path(__file__).parent.parent.parent  # 1-ARCHITECTURE/
REPO_ROOT = BASE.parent
sys.path.insert(0, str(BASE))

from dreamos.core.capability.tool_set import (  # noqa: E402
    HCP_TOOL_LIMIT,
    ToolSetError,
    build_hcp_sidecar,
    compute_tool_set_hash,
    diff_tools,
    validate_tool_set_approval,
    write_hcp_sidecar,
)

HASH_PATTERN = re.compile(r"^sha256:[0-9a-f]{64}$")
GENERATED_AT = "2026-11-17T10:00:00+00:00"


def _tool(name: str, effect: str = "read") -> dict:
    return {
        "name": name,
        "shell": "l2.dreamos.mcp",
        "layer": "L2",
        "exposure": "read",
        "effect": effect,
        "requires_mandate": effect in ("write", "trade"),
        "visibility": "both" if effect == "read" else "model",
        "approval": "auto",
    }


def _snapshot(tools, *, run_id="run-h2-test", mode="default"):
    return {
        "schema_version": "1.0",
        "run_id": run_id,
        "generated_at": GENERATED_AT,
        "source": "47-registry",
        "policy": {"order": ["deny", "mode", "allow", "human"], "mode": mode},
        "tools": list(tools),
    }


# ── hash ────────────────────────────────────────────


def test_hash_is_stable_and_order_insensitive():
    a = [_tool("l2.dreamos.poll_run"), _tool("l2.dreamos.submit_run", "write")]
    b = list(reversed(a))

    first = compute_tool_set_hash(a)
    assert HASH_PATTERN.match(first)
    assert first == compute_tool_set_hash(a)
    assert first == compute_tool_set_hash(b)


def test_hash_changes_when_tool_content_changes():
    before = [_tool("l2.dreamos.poll_run")]
    after = [_tool("l2.dreamos.poll_run", "write")]
    assert compute_tool_set_hash(before) != compute_tool_set_hash(after)


# ── diff ────────────────────────────────────────────


def test_diff_detects_add_remove_change():
    prev = [_tool("l2.a.read"), _tool("l2.a.write", "write")]
    curr = [_tool("l2.a.write", "trade"), _tool("l2.a.new")]

    diff = diff_tools(prev, curr)
    assert diff == {
        "added": ["l2.a.new"],
        "removed": ["l2.a.read"],
        "changed": ["l2.a.write"],
    }


def test_diff_empty_when_identical_regardless_of_order():
    tools = [_tool("l2.a.read"), _tool("l2.a.write", "write")]
    assert diff_tools(tools, list(reversed(tools))) == {
        "added": [],
        "removed": [],
        "changed": [],
    }


# ── sidecar ─────────────────────────────────────────


def test_first_sidecar_shape():
    snapshot = _snapshot([_tool("l2.a.read")])
    sidecar = build_hcp_sidecar(
        snapshot,
        session_id="sess-001",
        tool_set_id="ts-001",
    )

    assert sidecar["schema_version"] == "hcp-1.0"
    assert sidecar["tool_set_id"] == "ts-001"
    assert sidecar["run_id"] == snapshot["run_id"]
    assert sidecar["session_id"] == "sess-001"
    assert sidecar["mode"] == "default"
    assert sidecar["version"] == 1
    assert sidecar["hash"] == compute_tool_set_hash(snapshot["tools"])
    assert sidecar["diff"] == {"added": [], "removed": [], "changed": []}
    assert sidecar["approval_ref"] is None
    # v1.0 快照本体不得被改写
    assert "session_id" not in snapshot


def test_sidecar_versions_and_diff_on_change():
    first_snapshot = _snapshot([_tool("l2.a.read")])
    first = build_hcp_sidecar(first_snapshot, session_id="sess-001")

    second_snapshot = _snapshot([_tool("l2.a.read"), _tool("l2.a.new")])
    second = build_hcp_sidecar(
        second_snapshot,
        session_id="sess-001",
        previous={"version": first["version"], "snapshot": first_snapshot},
    )

    assert second["version"] == 2
    assert second["diff"]["added"] == ["l2.a.new"]
    assert second["diff"]["removed"] == []
    assert second["hash"] != first["hash"]


def test_sidecar_without_change_keeps_version_and_empty_diff():
    snapshot = _snapshot([_tool("l2.a.read")])
    first = build_hcp_sidecar(snapshot, session_id="sess-001")
    again = build_hcp_sidecar(
        snapshot,
        session_id="sess-001",
        previous={"version": first["version"], "snapshot": snapshot},
    )

    assert again["version"] == first["version"]
    assert again["diff"] == {"added": [], "removed": [], "changed": []}


def test_sidecar_rejects_more_tools_than_limit():
    tools = [_tool(f"l2.a.t{i}") for i in range(HCP_TOOL_LIMIT + 1)]
    with pytest.raises(ToolSetError):
        build_hcp_sidecar(_snapshot(tools), session_id="sess-001")


def test_sidecar_rejects_missing_session_id():
    with pytest.raises(ToolSetError):
        build_hcp_sidecar(_snapshot([_tool("l2.a.read")]), session_id="  ")


# ── 审批绑定 ────────────────────────────────────────


def _sidecar_with_approval():
    snapshot = _snapshot([_tool("l2.a.read")])
    sidecar = build_hcp_sidecar(snapshot, session_id="sess-001")
    sidecar["approval_ref"] = {
        "tool_set_hash": sidecar["hash"],
        "mandate_id": "mandate-001",
    }
    return sidecar


def test_approval_hash_mismatch_rejected():
    sidecar = _sidecar_with_approval()
    mandate = {
        "mandate_id": "mandate-001",
        "tool_set_hash": "sha256:" + "0" * 64,
        "issued_at": "2026-11-17T10:00:01+00:00",
    }
    with pytest.raises(ToolSetError):
        validate_tool_set_approval(sidecar, mandate, generated_at=GENERATED_AT)


def test_approval_issued_before_snapshot_rejected():
    sidecar = _sidecar_with_approval()
    mandate = {
        "mandate_id": "mandate-001",
        "tool_set_hash": sidecar["hash"],
        "issued_at": "2026-11-17T09:59:59+00:00",
    }
    with pytest.raises(ToolSetError):
        validate_tool_set_approval(sidecar, mandate, generated_at=GENERATED_AT)


def test_approval_after_snapshot_accepted():
    sidecar = _sidecar_with_approval()
    mandate = {
        "mandate_id": "mandate-001",
        "tool_set_hash": sidecar["hash"],
        "issued_at": "2026-11-17T10:00:01+00:00",
    }
    assert validate_tool_set_approval(sidecar, mandate, generated_at=GENERATED_AT) is None


# ── 落盘 ────────────────────────────────────────────


def test_write_sidecar_json(tmp_path):
    snapshot = _snapshot([_tool("l2.a.read")])
    sidecar = build_hcp_sidecar(snapshot, session_id="sess-001")
    target = tmp_path / "tool_set.hcp.json"

    write_hcp_sidecar(sidecar, target)

    loaded = json.loads(target.read_text(encoding="utf-8"))
    assert loaded == sidecar
