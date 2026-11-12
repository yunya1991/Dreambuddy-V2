"""T-G17 测量与审计契约 — RED 测试

SPEC-33-G §2.11.9：
  1. 单一事实源 `ledger/events.jsonl`；引用 + 摘要，禁止复制完整正文
  2. outcome 幂等键 (change_id, run_id, outcome_seq)，重复覆盖不追加
  3. change_id 贯穿 proposal→branch→merge→deploy→metric→outcome，链路缺失不计证据
  4. 事件带 schema_version
  5. prev_hash 哈希链；断链即冻结 auto
  6. evaluator_version 冻结；切换需历史回归一致率达标
  9. 同观察窗 >1 变更需 BH-FDR(q≤0.1)，未校正只能 hold
  10. 同 section 禁止并行 L2；无法隔离走 switchback

RED 契约：core.evolution.event_ledger 不存在。
"""

from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest
from core.evolution.event_ledger import (
    EVALUATOR_MIN_AGREEMENT,
    SCHEMA_VERSION,
    EventLedger,
    EventLedgerError,
)

BASE = datetime(2026, 11, 1, 12, 0, tzinfo=timezone.utc)


def _ledger(tmp_path):
    return EventLedger(tmp_path / "ledger", clock=lambda: BASE)


def _full_chain(ledger, change_id="CH-1"):
    ledger.append(kind="proposal", change_id=change_id, payload={"proposal_id": "PP-1"})
    ledger.append(kind="branch", change_id=change_id, payload={"branch": f"evo/{change_id}"})
    ledger.append(kind="merge", change_id=change_id, payload={"commit": "abc1234"})
    ledger.append(kind="deploy", change_id=change_id, payload={"env": "staging"})
    ledger.append(kind="metric", change_id=change_id, payload={"section": "analyze"})
    ledger.record_outcome(
        change_id=change_id,
        run_id="RUN-1",
        outcome_seq=1,
        payload={"accepted": True, "tests_pass": True, "reverted": False},
    )


class FakeBreaker:
    def __init__(self):
        self.reasons = []

    def open_breaker(self, *, reason, actor="operator", trigger_policy=""):
        self.reasons.append(reason)
        return {"open": True, "reason": reason}


# ---------------------------------------------------------------- 账本基础


def test_append_stamps_schema_version_and_hash_chain(tmp_path):
    ledger = _ledger(tmp_path)
    first = ledger.append(kind="proposal", change_id="CH-1", payload={"proposal_id": "PP-1"})
    second = ledger.append(kind="merge", change_id="CH-1", payload={"commit": "abc"})

    assert first["schema_version"] == SCHEMA_VERSION
    assert second["schema_version"] == SCHEMA_VERSION
    assert second["prev_hash"] == first["receipt_hash"]
    assert first["prev_hash"] == "0" * 64

    report = ledger.verify_chain()
    assert report["ok"] is True
    assert report["events"] == 2
    assert report["head"] == second["receipt_hash"]


def test_payload_is_summary_only_not_full_body(tmp_path):
    ledger = _ledger(tmp_path)
    with pytest.raises(EventLedgerError, match="摘要"):
        ledger.append(kind="proposal", change_id="CH-1", payload={"body": "x" * 4096})

    ok = ledger.append(
        kind="case",
        change_id="CH-1",
        payload={"case_id": "C-1", "summary": "引用 + 摘要"},
    )
    assert ok["payload"]["case_id"] == "C-1"


def test_outcome_idempotent_overwrite_not_append(tmp_path):
    ledger = _ledger(tmp_path)
    ledger.record_outcome(
        change_id="CH-1",
        run_id="RUN-1",
        outcome_seq=1,
        payload={"accepted": False, "tests_pass": False, "reverted": False},
    )
    ledger.record_outcome(
        change_id="CH-1",
        run_id="RUN-1",
        outcome_seq=1,
        payload={"accepted": True, "tests_pass": True, "reverted": False},
    )

    outcomes = ledger.outcomes(change_id="CH-1")
    assert len(outcomes) == 1
    assert outcomes[0]["payload"]["accepted"] is True
    assert ledger.verify_chain()["ok"] is True


def test_change_id_trace_completeness_gates_evidence(tmp_path):
    ledger = _ledger(tmp_path)
    _full_chain(ledger)

    trace = ledger.trace("CH-1")
    assert trace["complete"] is True
    assert trace["missing"] == []
    assert ledger.counts_as_evidence("CH-1") is True

    ledger2 = _ledger(tmp_path / "partial")
    ledger2.append(kind="proposal", change_id="CH-9", payload={"proposal_id": "PP-9"})
    ledger2.append(kind="merge", change_id="CH-9", payload={"commit": "def"})
    partial = ledger2.trace("CH-9")
    assert partial["complete"] is False
    assert set(partial["missing"]) == {"branch", "deploy", "metric", "outcome"}
    assert ledger2.counts_as_evidence("CH-9") is False


# ---------------------------------------------------------------- 审计链


def test_chain_tamper_detected_and_freezes_auto(tmp_path):
    ledger = _ledger(tmp_path)
    _full_chain(ledger)

    path = ledger.path
    rows = [
        json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()
    ]
    rows[0]["payload"]["proposal_id"] = "PP-TAMPERED"
    path.write_text(
        "\n".join(json.dumps(row, ensure_ascii=False, sort_keys=True) for row in rows) + "\n",
        encoding="utf-8",
    )

    report = ledger.verify_chain()
    assert report["ok"] is False
    assert report["broken_at"] == 0

    breaker = FakeBreaker()
    enforced = ledger.enforce_chain(breaker)
    assert enforced["ok"] is False
    assert enforced["auto_frozen"] is True
    assert breaker.reasons and "链" in breaker.reasons[0]


def test_clean_chain_does_not_touch_breaker(tmp_path):
    ledger = _ledger(tmp_path)
    _full_chain(ledger)
    breaker = FakeBreaker()

    enforced = ledger.enforce_chain(breaker)
    assert enforced["ok"] is True
    assert enforced["auto_frozen"] is False
    assert breaker.reasons == []


# ---------------------------------------------------------------- 评估器冻结


def test_evaluator_frozen_and_switch_needs_regression(tmp_path):
    ledger = _ledger(tmp_path)
    ledger.freeze_evaluator("eval-v1")
    assert ledger.evaluator_version() == "eval-v1"

    with pytest.raises(EventLedgerError, match="冻结"):
        ledger.freeze_evaluator("eval-v2")

    assert ledger.request_evaluator_switch("eval-v2", agreement=0.7)["allowed"] is False
    assert ledger.evaluator_version() == "eval-v1"

    applied = ledger.request_evaluator_switch("eval-v2", agreement=EVALUATOR_MIN_AGREEMENT + 0.05)
    assert applied["allowed"] is True
    assert ledger.evaluator_version() == "eval-v2"


# ---------------------------------------------------------------- 多重比较


def test_bh_fdr_required_only_for_multiple_changes(tmp_path):
    ledger = _ledger(tmp_path)

    assert ledger.requires_bh_fdr(1) is False
    assert ledger.requires_bh_fdr(2) is True

    result = ledger.bh_fdr({"a": 0.01, "b": 0.04, "c": 0.03, "d": 0.5}, q=0.1)
    assert result["method"] == "bh"
    assert result["rejected"] == ["a", "b", "c"]
    assert result["hold"] == ["d"]


# ---------------------------------------------------------------- 归因隔离


def test_section_exclusive_lock_and_switchback(tmp_path):
    ledger = _ledger(tmp_path)

    assert ledger.acquire_section("analyze", change_id="CH-1")["mode"] == "exclusive"
    with pytest.raises(EventLedgerError, match="并行"):
        ledger.acquire_section("analyze", change_id="CH-2")

    switch = ledger.acquire_section("analyze", change_id="CH-2", mode="switchback")
    assert switch["mode"] == "switchback"
    assert switch["holder"] == "CH-1"

    with pytest.raises(EventLedgerError, match="锁"):
        ledger.release_section("analyze", change_id="CH-404")

    ledger.release_section("analyze", change_id="CH-2")
    assert ledger.release_section("analyze", change_id="CH-1")["released"] is True
    assert ledger.acquire_section("analyze", change_id="CH-3")["mode"] == "exclusive"
