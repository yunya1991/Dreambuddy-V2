"""SPEC-33-E T-E5：adapt_plan 契约与门禁（只出方案，不改代码）。

硬约束（§2.6）：
  - 缺 evidence_ref / rollback / acceptance 的方案直接丢弃并计 known_gaps。
  - 只采纳 hypothesis gate=pass 的方案（§2.7 + T-E10）。

RED 基线：`core.adapt_plan` 尚不存在 → ImportError；壳无 submit_rea_adapt_plan → KeyError。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

_REA_ROOT = Path(__file__).resolve().parents[1]
_REPO_ROOT = _REA_ROOT.parent
for _p in (_REA_ROOT, _REPO_ROOT):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import dsh_nodes  # noqa: E402
from core.adapt_plan import build_adapt_plans, validate_plan  # noqa: E402

from mcp_shells.l0_rea import server as rea_server  # noqa: E402

VALID_PLAN = {
    "plan_id": "A-001",
    "hypothesis_id": "H-001",
    "target_module": "3.1-FRONTEND/src/stores",
    "change": "将 12 个 store 合并为 5 个 slice",
    "evidence_ref": [{"source": "replay_pool:tree-1", "node": "n12", "confidence": 0.82}],
    "risk": ["跨 store 循环依赖"],
    "rollback": "git revert <commit>；store 边界恢复原 12 文件",
    "acceptance": ["pnpm tsc --noEmit", "pnpm test stores"],
    "priority": "P1",
}


def test_valid_plan_kept_and_normalized():
    result = build_adapt_plans([dict(VALID_PLAN)], gates={"H-001": "pass"})
    assert len(result["plans"]) == 1
    plan = result["plans"][0]
    assert plan["plan_id"] == "A-001"
    assert plan["target_module"] == VALID_PLAN["target_module"]
    assert plan["rollback"] and plan["acceptance"]
    assert plan["priority"] == "P1"
    assert result["dropped"] == []
    assert result["known_gaps"] == []


def test_missing_rollback_dropped_and_counted():
    broken = {k: v for k, v in VALID_PLAN.items() if k != "rollback"}
    assert any("rollback" in e for e in validate_plan(broken))
    result = build_adapt_plans([broken], gates={"H-001": "pass"})
    assert result["plans"] == []
    assert result["dropped"][0]["plan_id"] == "A-001"
    assert "rollback" in result["dropped"][0]["reason"]
    assert any("rollback" in gap for gap in result["known_gaps"])


def test_missing_acceptance_or_evidence_ref_dropped():
    no_acceptance = {k: v for k, v in VALID_PLAN.items() if k != "acceptance"}
    no_evidence = {k: v for k, v in VALID_PLAN.items() if k != "evidence_ref"}
    result = build_adapt_plans([no_acceptance, no_evidence], gates={"H-001": "pass"})
    assert result["plans"] == []
    reasons = " ".join(item["reason"] for item in result["dropped"])
    assert "acceptance" in reasons and "evidence_ref" in reasons
    assert len(result["known_gaps"]) == 2


def test_non_pass_gate_not_adopted():
    result = build_adapt_plans([dict(VALID_PLAN)], gates={"H-001": "review"})
    assert result["plans"] == []
    assert "gate" in result["dropped"][0]["reason"]
    assert set(result["passed_hypotheses"]) == set()


def test_unknown_gate_kept_but_flagged():
    """无门禁信息时不伪造 pass：方案保留，但 cognitive_hint 只标 skip。"""
    result = build_adapt_plans([dict(VALID_PLAN)])
    assert len(result["plans"]) == 1
    assert result["plans"][0]["gate"] == "unknown"
    assert result["cognitive_hint"]["write"] == []


def test_node_returns_plans_and_gaps():
    out = dsh_nodes.S33_rea_adapt_plan({"plans": [dict(VALID_PLAN)]})
    assert out["ok"] is True
    body = out["result"]
    assert body["mode"] == "adapt_plan"
    assert body["stats"]["plans"] == 1
    assert body["stats"]["dropped"] == 0
    assert body["evidence"][0]["level"] == "derivation"
    assert body["known_gaps"] == []

    broken = dsh_nodes.S33_rea_adapt_plan(
        {"plans": [{k: v for k, v in VALID_PLAN.items() if k != "rollback"}]}
    )
    assert broken["ok"] is True
    assert broken["result"]["plans"] == []
    assert broken["result"]["known_gaps"]


def test_node_rejects_empty_plans():
    out = dsh_nodes.S33_rea_adapt_plan({"plans": []})
    assert out["ok"] is False
    assert out["error"] == "missing_plans"


def test_shell_exposes_submit_poll_cancel():
    for name in (
        "submit_rea_adapt_plan",
        "poll_rea_adapt_plan",
        "cancel_rea_adapt_plan",
    ):
        assert name in rea_server.TOOL_DEFS
        assert name in rea_server.TOOL_HANDLERS
    schema = rea_server.TOOL_DEFS["submit_rea_adapt_plan"]["inputSchema"]
    assert schema["required"] == ["plans"]
    assert "deadline_ms" in schema["properties"]

    body = json.loads(
        rea_server.TOOL_HANDLERS["submit_rea_adapt_plan"]({"plans": [dict(VALID_PLAN)]})
    )
    assert body["ok"] is True
    assert body["meta"]["job_id"]


def test_engineer_whitelist_unchanged():
    """engineer 角色白名单仍为 10，不因新增 adapt_plan 工具而扩张。"""
    text = (_REPO_ROOT / "47-MCP管理系统" / "registry" / "mcp_capabilities.yaml").read_text(
        encoding="utf-8"
    )
    engineer_block = text.split("\n  engineer:", 1)[1].split("\n  data_reader:", 1)[0]
    assert "adapt_plan" not in engineer_block
