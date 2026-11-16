"""A1-2: capability 层 tool_set 唯一副本 + D3 配额交叉校验

对齐 56/contracts/tool_set.schema.json (v1.0):
  - 由 47 registry 生成快照，3.1/52/DreamOS 只读消费
  - 交易工具必须 trade + requires_mandate + human 审批
  - 退役壳工具进 denied_tools，且与活跃工具不重叠
  - D3：分层配额 / max_total_tools / 单壳 / 角色 交叉校验
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
    ToolSetError,
    build_tool_set,
    build_tool_set_from_registry,
    quota_report,
)

TOOL_SET_SCHEMA = REPO_ROOT / "56-L2架构能力聚合层" / "contracts" / "tool_set.schema.json"
NAME_PATTERN = re.compile(r"^l[0-2]\.[a-z0-9_]+\.[a-z0-9_]+$")
SHELL_PATTERN = re.compile(r"^l[0-2]\.[a-z0-9_]+\.mcp$")


def _shell(
    shell_id="l0.demo.mcp",
    layer="L0",
    domain="demo",
    exposure="readonly-observe",
    status="available",
    tools=None,
):
    return {
        "shell_id": shell_id,
        "capability_id": shell_id.rsplit(".mcp", 1)[0],
        "status": status,
        "layer": layer,
        "capability_domain": domain,
        "exposure": exposure,
        "tools": tools
        or [
            {"name": "read_one", "domain": domain, "read_write": "read", "requires_mandate": False},
            {
                "name": "write_one",
                "domain": domain,
                "read_write": "write",
                "requires_mandate": True,
            },
        ],
    }


def _registry(*shells, **enums):
    limits = {"max_tools_per_shell": 15, "max_tools_per_role": 10, "max_total_tools": 80}
    limits.update(enums)
    limits.setdefault("layer_quota", {"L0": 60, "L1": 30, "L2": 30, "total": 120})
    return {"shells": list(shells), "enums": limits, "worker_roles": {}}


# ── 契约形态 ────────────────────────────────────────


def test_real_registry_snapshot_matches_schema():
    snapshot = build_tool_set(run_id="run-a12-test")

    schema = json.loads(TOOL_SET_SCHEMA.read_text(encoding="utf-8"))
    from jsonschema import Draft202012Validator

    errors = list(Draft202012Validator(schema).iter_errors(snapshot))
    assert not errors, [e.message for e in errors]

    assert snapshot["source"] == "47-registry"
    assert snapshot["policy"]["order"] == ["deny", "mode", "allow", "human"]

    names = [t["name"] for t in snapshot["tools"]]
    assert len(names) == len(set(names))
    for tool in snapshot["tools"]:
        assert NAME_PATTERN.match(tool["name"]), tool["name"]
        assert SHELL_PATTERN.match(tool["shell"]), tool["shell"]
        assert tool["name"].startswith(tool["layer"].lower() + ".")


def test_trade_tool_forced_mandate_and_human():
    snapshot = build_tool_set(run_id="run-a12-test")
    trade = {t["name"]: t for t in snapshot["tools"] if t["effect"] == "trade"}

    assert trade, "注册表应至少有一个交易工具"
    for tool in trade.values():
        assert tool["requires_mandate"] is True
        assert tool["approval"] == "human"
        assert tool["visibility"] == "model"


def test_write_requires_mandate_and_read_auto():
    snapshot = build_tool_set(run_id="run-a12-test")
    by_name = {t["name"]: t for t in snapshot["tools"]}

    for tool in snapshot["tools"]:
        if tool["effect"] == "write":
            assert tool["requires_mandate"] is True

    read = by_name["l0.cognition.recall"]
    assert read["effect"] == "read"
    assert read["approval"] == "auto"
    assert read["visibility"] == "both"


def test_run_id_fallback_is_contract_valid():
    snapshot = build_tool_set_from_registry(_registry(_shell()), run_id="x")
    assert re.match(r"^[A-Za-z0-9._:-]{3,64}$", snapshot["run_id"])
    assert snapshot["run_id"] != "x"


def test_retired_shell_duplicate_is_not_denied():
    """退役壳与活跃壳同域重名：以活跃为准，不产生 denied 冲突"""
    registry = _registry(
        _shell(),
        _shell(shell_id="agent.demo.mcp", status="deprecated"),
        _shell(shell_id="l0.old.mcp", domain="old", status="deprecated"),
    )
    snapshot = build_tool_set_from_registry(registry)

    assert "l0.old.read_one" in snapshot["denied_tools"]
    assert "l0.demo.read_one" not in snapshot["denied_tools"]
    assert not set(snapshot["denied_tools"]) & {t["name"] for t in snapshot["tools"]}


def test_not_exposed_shell_excluded():
    registry = _registry(_shell(exposure="not-exposed"))
    snapshot = build_tool_set_from_registry(registry)
    assert snapshot["tools"] == []


def test_invalid_mode_and_shell_id_rejected():
    with pytest.raises(ToolSetError):
        build_tool_set_from_registry(_registry(_shell()), mode="yolo")
    with pytest.raises(ToolSetError):
        build_tool_set_from_registry(_registry(_shell(shell_id="demo.mcp")))


# ── D3 配额交叉校验 ─────────────────────────────────


def test_quota_ok_on_real_registry_with_gap18_warning():
    import yaml

    registry = yaml.safe_load(
        (REPO_ROOT / "47-MCP管理系统" / "registry" / "mcp_capabilities.yaml").read_text(
            encoding="utf-8"
        )
    )
    report = quota_report(registry)

    assert report["ok"] is True
    assert report["violations"] == []
    assert report["active_total"] == sum(report["active_by_layer"].values())
    # GAP-18：max_total_tools(80) 与 layer_quota.total(120) 口径不一致，必须显式暴露
    assert any(w["code"] == "E-TOTAL-CAP-MISMATCH" for w in report["warnings"])


def test_quota_detects_layer_shell_and_role_overflow():
    registry = _registry(
        _shell(tools=[{"name": f"t{i}", "domain": "demo", "read_write": "read"} for i in range(4)]),
        max_tools_per_shell=3,
        layer_quota={"L0": 5, "L1": 30, "L2": 30, "total": 10},
    )
    registry["worker_roles"] = {"worker": {"tools": list(range(11))}}
    report = quota_report(registry)

    codes = {v["code"] for v in report["violations"]}
    # L0 只有 4 个工具未超 5；总量 4 未超；但单壳 4 > 3、角色 11 > 10
    assert codes == {"E-SHELL-EXCEEDED", "E-ROLE-EXCEEDED"}
    assert report["ok"] is False
