# -*- coding: utf-8 -*-
"""P3-4 27 审批适配器 + P3-3 L0 沉淀门禁适配器测试。"""

from __future__ import annotations

import json

from core.enforcement import Enforcer
from core.gate import Gate
from integrations.approvals import ApprovalChecker
from integrations.l0_gate import build_settle_gate
from storage.repo import InMemoryRepo

NOW_MS = 1_760_000_000_000
DAY_MS = 86400_000


def write_log(tmp_path, rows: list[dict]) -> str:
    path = tmp_path / "approvals.jsonl"
    path.write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n", encoding="utf-8"
    )
    return str(path)


def test_fresh_approval_passes(tmp_path):
    checker = ApprovalChecker(
        path=write_log(tmp_path, [{"id": "AP-1", "decision": "approve", "ts": NOW_MS}]),
        now_ms=lambda: NOW_MS + 1000,
    )
    assert checker.is_approved("AP-1") is True


def test_stale_approval_rejected(tmp_path):
    checker = ApprovalChecker(
        path=write_log(tmp_path, [{"id": "AP-1", "decision": "approve", "ts": NOW_MS}]),
        now_ms=lambda: NOW_MS + DAY_MS + 1,
    )
    assert checker.is_approved("AP-1") is False


def test_rejected_decision_rejected(tmp_path):
    checker = ApprovalChecker(
        path=write_log(tmp_path, [{"id": "AP-1", "decision": "reject", "ts": NOW_MS}]),
        now_ms=lambda: NOW_MS,
    )
    assert checker.is_approved("AP-1") is False


def test_unknown_id_rejected(tmp_path):
    checker = ApprovalChecker(
        path=write_log(tmp_path, [{"id": "AP-1", "decision": "approve", "ts": NOW_MS}]),
        now_ms=lambda: NOW_MS,
    )
    assert checker.is_approved("AP-2") is False


def test_missing_log_is_fail_closed(tmp_path):
    checker = ApprovalChecker(path=str(tmp_path / "nope.jsonl"))
    assert checker.is_approved("AP-1") is False


def test_latest_record_wins(tmp_path):
    checker = ApprovalChecker(
        path=write_log(
            tmp_path,
            [
                {"id": "AP-1", "decision": "approve", "ts": NOW_MS},
                {"id": "AP-1", "decision": "reject", "ts": NOW_MS + 10},
            ],
        ),
        now_ms=lambda: NOW_MS + 20,
    )
    assert checker.is_approved("AP-1") is False


def test_l0_gate_live_without_eval_id_blocks():
    enforcer = Enforcer(gate=Gate(repo=InMemoryRepo()), shadow=False)
    allowed, info = build_settle_gate(enforcer)({"intent": "data_query"})

    assert allowed is False
    assert info["decision"] == "BLOCK"
    assert any("unknown_eval_id" in r for r in info["reasons"])


def test_l0_gate_shadow_observes():
    enforcer = Enforcer(gate=Gate(repo=InMemoryRepo()), shadow=True)
    allowed, info = build_settle_gate(enforcer)({"eval_id": "EV-unknown"})

    assert allowed is True
    assert info["decision"] == "SHADOW_WOULD_BLOCK"


# -------- 台账健壮性（fail-closed 的各个缺口） --------


def test_path_property_and_env_default(tmp_path, monkeypatch):
    checker = ApprovalChecker(path=str(tmp_path / "a.jsonl"))
    assert checker.path == tmp_path / "a.jsonl"

    monkeypatch.delenv("EVAL_APPROVALS_LOG", raising=False)
    assert ApprovalChecker().path is None

    monkeypatch.setenv("EVAL_APPROVALS_LOG", str(tmp_path / "b.jsonl"))
    assert ApprovalChecker().path == tmp_path / "b.jsonl"


def test_callable_delegates(tmp_path):
    checker = ApprovalChecker(
        path=write_log(tmp_path, [{"id": "AP-1", "decision": "approved", "ts": NOW_MS}]),
        now_ms=lambda: NOW_MS,
    )
    assert checker("AP-1") is True


def test_blank_and_broken_lines_are_skipped(tmp_path):
    path = tmp_path / "approvals.jsonl"
    path.write_text(
        "\n".join(
            [
                json.dumps({"id": "AP-1", "decision": "approve", "ts": NOW_MS}),
                "not-json",
                "",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    checker = ApprovalChecker(path=str(path), now_ms=lambda: NOW_MS)
    assert checker.is_approved("AP-1") is True


def test_bad_ts_type_rejected(tmp_path):
    checker = ApprovalChecker(
        path=write_log(tmp_path, [{"id": "AP-1", "decision": "approve", "ts": "abc"}]),
        now_ms=lambda: NOW_MS,
    )
    assert checker.is_approved("AP-1") is False


def test_non_positive_ts_rejected(tmp_path):
    checker = ApprovalChecker(
        path=write_log(tmp_path, [{"id": "AP-1", "decision": "approve", "ts": 0}]),
        now_ms=lambda: NOW_MS,
    )
    assert checker.is_approved("AP-1") is False


def test_read_error_is_fail_closed(tmp_path, monkeypatch):
    path = tmp_path / "approvals.jsonl"
    path.write_text("\n", encoding="utf-8")
    checker = ApprovalChecker(path=str(path), now_ms=lambda: NOW_MS)

    def _boom(*_a, **_k):
        raise OSError("disk on fire")

    monkeypatch.setattr("pathlib.Path.read_text", _boom)
    assert checker.is_approved("AP-1") is False


def test_default_clock_accepts_fresh_approval(tmp_path):
    import time

    checker = ApprovalChecker(
        path=write_log(
            tmp_path, [{"id": "AP-1", "decision": "approve", "ts": int(time.time() * 1000)}]
        )
    )
    assert checker.is_approved("AP-1") is True
