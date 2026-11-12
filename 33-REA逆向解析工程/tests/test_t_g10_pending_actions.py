"""T-G10 无 LLM 降级通道（pending_actions + section=evolution）— RED 测试

SPEC-33-G §2.9：
  1. 触发照常计算，proposal 落 `policy/proposals/pending/`
  2. analyze / trace / rea_audit 信封带 `pending_actions[]`
  3. get_rea_snapshot(section=evolution) 返回待办（含 diff 与回滚点）
  4. TRAE workflow 启动即读，非空则提示
  5. 飞书告警（manual 必发；auto 仅通知）

§1 G-G10：MCP 返回 pending_actions；TRAE 启动即感知。

RED 契约：core.evolution.pending_actions 不存在；dsh_nodes 信封无 pending_actions。
"""

from __future__ import annotations

import json

import dsh_nodes
import pytest
from core.evolution.pending_actions import PendingActionError, PendingActionStore


def _proposal(proposal_id="PP-1", level="L1"):
    return {
        "proposal_id": proposal_id,
        "level": level,
        "trigger": "repeat_failure",
        "claim": "同类失败连续 3 次，需调整规则阈值",
        "falsifier": "调整后同类失败率不降",
        "expected_effect": "失败率下降 20%",
        "proposer_model": "model-a",
    }


def _store(tmp_path):
    store = PendingActionStore(tmp_path / "policy")
    store.enqueue(
        _proposal(),
        diff="- threshold: 3\n+ threshold: 2\n",
        rollback_point="tag-policy-PP-1-pre",
    )
    return store


def _project(tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    (project / "main.py").write_text("def main():\n    return 1\n", encoding="utf-8")
    return project


# ---------------------------------------------------------------- 账本


def test_enqueue_requires_contract_fields(tmp_path):
    store = PendingActionStore(tmp_path / "policy")

    with pytest.raises(PendingActionError, match="proposal_id"):
        store.enqueue({"level": "L1", "rollback_point": "tag"}, rollback_point="tag")
    with pytest.raises(PendingActionError, match="level"):
        store.enqueue(_proposal(level="L9"), rollback_point="tag")
    with pytest.raises(PendingActionError, match="falsifier"):
        store.enqueue({**_proposal(), "falsifier": ""}, diff="d", rollback_point="tag")
    with pytest.raises(PendingActionError, match="rollback"):
        store.enqueue(_proposal(), diff="d", rollback_point="")


def test_enqueue_writes_pending_file_and_action(tmp_path):
    store = _store(tmp_path)
    path = tmp_path / "policy" / "proposals" / "pending" / "PP-1.json"
    assert path.is_file()

    record = json.loads(path.read_text(encoding="utf-8"))
    assert record["status"] == "pending"
    assert record["rollback_point"] == "tag-policy-PP-1-pre"

    actions = store.actions()
    assert len(actions) == 1
    action = actions[0]
    assert action["proposal_id"] == "PP-1"
    assert action["state"] == "pending"
    assert "threshold: 2" in action["diff"]
    assert action["rollback_point"] == "tag-policy-PP-1-pre"
    assert action["approve"].startswith("approve_policy.py --id")


def test_actions_sorted_and_limited(tmp_path):
    store = _store(tmp_path)
    store.enqueue(_proposal("PP-2"), diff="d2", rollback_point="tag-2")

    actions = store.actions(limit=1)
    assert len(actions) == 1
    latest = actions[0]["proposal_id"]
    assert latest in ("PP-1", "PP-2")
    assert store.count() == 2


# ---------------------------------------------------------------- MCP 信封


def test_analyze_envelope_carries_pending_actions(tmp_path, monkeypatch):
    _store(tmp_path)
    monkeypatch.setenv("REA_EVOLUTION_POLICY_ROOT", str(tmp_path / "policy"))

    output = dsh_nodes.S33_rea_analyze({"target": str(_project(tmp_path))})
    assert output["ok"] is True
    actions = output.get("pending_actions") or []
    assert len(actions) == 1
    assert actions[0]["proposal_id"] == "PP-1"
    assert actions[0]["rollback_point"]


def test_trace_and_audit_envelopes_carry_pending_actions(tmp_path, monkeypatch):
    _store(tmp_path)
    monkeypatch.setenv("REA_EVOLUTION_POLICY_ROOT", str(tmp_path / "policy"))
    project = _project(tmp_path)

    trace_out = dsh_nodes.S33_rea_trace({"target": str(project), "feature": "main"})
    assert trace_out["ok"] is True
    assert [a["proposal_id"] for a in trace_out.get("pending_actions") or []] == ["PP-1"]

    audit_out = dsh_nodes.S33_rea_audit({"target": str(project / "main.py")})
    assert [a["proposal_id"] for a in audit_out.get("pending_actions") or []] == ["PP-1"]


def test_envelope_has_no_pending_key_when_queue_empty(tmp_path, monkeypatch):
    monkeypatch.setenv("REA_EVOLUTION_POLICY_ROOT", str(tmp_path / "empty"))

    output = dsh_nodes.S33_rea_analyze({"target": str(_project(tmp_path))})
    assert output["ok"] is True
    assert not output.get("pending_actions")


# ---------------------------------------------------------------- snapshot


def test_snapshot_section_evolution_returns_pending_actions(tmp_path, monkeypatch):
    _store(tmp_path)
    monkeypatch.setenv("REA_EVOLUTION_POLICY_ROOT", str(tmp_path / "policy"))

    output = dsh_nodes.get_rea_snapshot({"section": "evolution"})
    assert output["ok"] is True
    items = output["result"]["items"]
    assert len(items) == 1
    assert items[0]["proposal_id"] == "PP-1"
    assert "threshold: 2" in items[0]["diff"]
    assert items[0]["rollback_point"] == "tag-policy-PP-1-pre"
    assert output["result"]["total"] == 1


def test_snapshot_evolution_paginates_and_rejects_unknown_section(tmp_path, monkeypatch):
    store = _store(tmp_path)
    store.enqueue(_proposal("PP-2"), diff="d2", rollback_point="tag-2")
    monkeypatch.setenv("REA_EVOLUTION_POLICY_ROOT", str(tmp_path / "policy"))

    page = dsh_nodes.get_rea_snapshot({"section": "evolution", "limit": 1})
    assert page["ok"] is True
    assert page["result"]["total"] == 2
    assert page["result"]["next_cursor"] == 1

    bad = dsh_nodes.get_rea_snapshot({"section": "nope"})
    assert bad["ok"] is False
    assert bad["error"] == "invalid_section"
