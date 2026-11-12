"""T-G1 outcome 回传契约 — RED 测试

SPEC-33-G §1 G-G1 / §3 T-G1 / §2.11.9：
  - outcome 必须包含 accepted / tests_pass / reverted 三个布尔字段
  - 每次假设可关联 outcome，verify 只接受带 outcome 的调用
  - outcome 写入键 = (change_id, run_id, outcome_seq)，重复回传覆盖不追加
  - 事件带 prev_hash 形成哈希链

RED 契约（实现前应全部失败）：
  - outcome_ledger 模块不存在
  - _handle_verify 未校验 outcome
"""

from __future__ import annotations

import json
from unittest.mock import patch

import pytest
from outcome_ledger import OutcomeLedger, validate_outcome


def _data(result):
    """兼容统一信封：业务字段在 result['data'] 内。"""
    return result.get("data", result)


VALID = {"accepted": True, "tests_pass": True, "reverted": False}


# ─────────────────────────── validate_outcome ───────────────────────────


def test_validate_outcome_accepts_valid_payload():
    ok, reason = validate_outcome(VALID)
    assert ok, reason


@pytest.mark.parametrize("missing", ["accepted", "tests_pass", "reverted"])
def test_validate_outcome_rejects_missing_required_field(missing):
    payload = dict(VALID)
    payload.pop(missing)
    ok, reason = validate_outcome(payload)
    assert not ok
    assert missing in reason


def test_validate_outcome_rejects_non_bool():
    ok, reason = validate_outcome({**VALID, "accepted": "true"})
    assert not ok
    assert "accepted" in reason


def test_validate_outcome_requires_full_idempotency_triplet():
    ok, reason = validate_outcome({**VALID, "change_id": "chg-1"})
    assert not ok
    assert "run_id" in reason and "outcome_seq" in reason


def test_validate_outcome_accepts_full_idempotency_triplet():
    ok, reason = validate_outcome(
        {**VALID, "change_id": "chg-1", "run_id": "run-1", "outcome_seq": 0}
    )
    assert ok, reason


# ─────────────────────────── OutcomeLedger ───────────────────────────


def test_ledger_appends_and_chains_prev_hash(tmp_path):
    ledger = OutcomeLedger(tmp_path / "events.jsonl")
    first = ledger.record(VALID)
    second = ledger.record({**VALID, "change_id": "chg-2", "run_id": "r", "outcome_seq": 1})

    assert first["receipt_hash"]
    assert second["prev_hash"] == first["receipt_hash"]
    assert ledger.verify_chain()


def test_ledger_idempotent_by_change_id_run_id_outcome_seq(tmp_path):
    ledger = OutcomeLedger(tmp_path / "events.jsonl")
    key = {"change_id": "chg-1", "run_id": "run-1", "outcome_seq": 0}
    ledger.record({**VALID, **key})
    ledger.record({**VALID, "accepted": False, **key})

    events = ledger.events()
    assert len(events) == 1, "重复回传应覆盖，不追加"
    assert events[0]["accepted"] is False
    assert ledger.verify_chain()


def test_ledger_chain_detects_tampering(tmp_path):
    path = tmp_path / "events.jsonl"
    ledger = OutcomeLedger(path)
    ledger.record(VALID)

    lines = path.read_text(encoding="utf-8").splitlines()
    payload = json.loads(lines[0])
    payload["accepted"] = False
    path.write_text(json.dumps(payload, ensure_ascii=False) + "\n", encoding="utf-8")

    assert not ledger.verify_chain()


# ─────────────────────────── _handle_verify 门禁 ───────────────────────────


def test_handle_verify_rejects_missing_outcome(tmp_path, monkeypatch):
    """verify 只接受带 outcome 的调用：缺失即拒绝，且不调用 CLE.verify。"""
    monkeypatch.setenv("COGNITIVE_OUTCOME_LEDGER_PATH", str(tmp_path / "events.jsonl"))
    from cognitive_mcp_server import _handle_verify

    with patch("cognitive_mcp_server._get_cle") as mock_cle:
        result = json.loads(_handle_verify({"memory_id": "VM-TEST-VERIFY", "success": True}))

    assert result.get("data") is None
    assert result.get("error_code") == "outcome_required"
    mock_cle.return_value.verify.assert_not_called()


def test_handle_verify_records_outcome_when_valid(tmp_path, monkeypatch):
    path = tmp_path / "events.jsonl"
    monkeypatch.setenv("COGNITIVE_OUTCOME_LEDGER_PATH", str(path))
    from cognitive_mcp_server import _handle_verify

    with (
        patch("cognitive_mcp_server._get_cle") as mock_cle,
        patch("cognitive_mcp_server._load_skill_indexer", return_value=None),
    ):
        mock_cle.return_value.verify.return_value = {"ok": True, "confidence": 0.7}
        result = json.loads(
            _handle_verify(
                {
                    "memory_id": "VM-TEST-VERIFY",
                    "success": True,
                    "outcome": {
                        **VALID,
                        "change_id": "chg-1",
                        "run_id": "run-1",
                        "outcome_seq": 0,
                        "section": "evolution",
                    },
                }
            )
        )

    data = _data(result)
    assert data["outcome_id"], "响应应返回 outcome_id"
    events = OutcomeLedger(path).events()
    assert len(events) == 1
    assert events[0]["memory_id"] == "VM-TEST-VERIFY"
    assert events[0]["change_id"] == "chg-1"
    assert events[0]["section"] == "evolution"


def test_handle_verify_shadow_mode_allows_missing_outcome(tmp_path, monkeypatch):
    """回滚开关：COGNITIVE_VERIFY_OUTCOME_MODE=shadow 时仅告警不阻断。"""
    monkeypatch.setenv("COGNITIVE_VERIFY_OUTCOME_MODE", "shadow")
    monkeypatch.setenv("COGNITIVE_OUTCOME_LEDGER_PATH", str(tmp_path / "events.jsonl"))
    from cognitive_mcp_server import _handle_verify

    with (
        patch("cognitive_mcp_server._get_cle") as mock_cle,
        patch("cognitive_mcp_server._load_skill_indexer", return_value=None),
    ):
        mock_cle.return_value.verify.return_value = {"ok": True}
        result = json.loads(_handle_verify({"memory_id": "VM-LEGACY", "success": True}))

    data = _data(result)
    assert data.get("ok") is True
    assert data.get("outcome_warning") == "outcome_required"
