# -*- coding: utf-8 -*-
"""H4：paused Ticket 可选 checkpoint（不改现有 Ticket 状态机/事件续跑）。

对齐 56/SPEC-56-H v0.3 §4.4 与 contracts/checkpoint.schema.json v1.0。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from core.ticket_checkpoint import (
    RESUME_MAX_AGE_S,
    CheckpointError,
    bind_ticket,
    build_checkpoint,
    read_checkpoint,
    validate_resume,
    write_checkpoint,
)

SCHEMA = (
    Path(__file__).parent.parent.parent
    / "56-L2架构能力聚合层"
    / "contracts"
    / "checkpoint.schema.json"
)

HASH = "sha256:" + "a" * 64


def _checkpoint(**overrides):
    params = {
        "session_id": "sess-001",
        "ticket_id": "ticket-001",
        "content_hash": HASH,
        "git": {"repo": "dreambuddy-v2", "commit": "abc123", "dirty": False},
        "artifacts": [],
        "created_at": "2026-11-17T10:00:00+00:00",
        "checkpoint_id": "ckpt-001",
    }
    params.update(overrides)
    return build_checkpoint(**params)


def test_checkpoint_matches_contract():
    checkpoint = _checkpoint()

    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    from jsonschema import Draft202012Validator

    errors = list(Draft202012Validator(schema).iter_errors(checkpoint))
    assert not errors, [e.message for e in errors]

    assert checkpoint["state"] == "paused"
    assert checkpoint["resume_guard"] == {"requires_same_hash": True, "max_age_s": RESUME_MAX_AGE_S}


def test_dirty_requires_artifacts():
    with pytest.raises(CheckpointError):
        _checkpoint(git={"repo": "r", "commit": "c", "dirty": True})

    ok = _checkpoint(
        git={"repo": "r", "commit": "c", "dirty": True},
        artifacts=[{"path": "x.py", "hash": HASH}],
    )
    assert ok["artifacts"][0]["path"] == "x.py"


def test_bind_ticket_only_for_paused_and_no_mutation():
    checkpoint = _checkpoint()
    ticket = {"ticket_id": "ticket-001", "state": "paused", "paused_reason": "waiting_job"}

    bound = bind_ticket(ticket, checkpoint)
    assert bound["checkpoint_id"] == "ckpt-001"
    assert "checkpoint_id" not in ticket  # 不原地修改

    with pytest.raises(CheckpointError):
        bind_ticket({"ticket_id": "ticket-001", "state": "live"}, checkpoint)
    with pytest.raises(CheckpointError):
        bind_ticket({"ticket_id": "other", "state": "paused"}, checkpoint)


def test_validate_resume_ok():
    verdict = validate_resume(
        _checkpoint(),
        current_content_hash=HASH,
        now="2026-11-17T12:00:00+00:00",
    )
    assert verdict["ok"] is True
    assert verdict["status"] == "resume"


def test_validate_resume_hash_mismatch_needs_review():
    verdict = validate_resume(
        _checkpoint(),
        current_content_hash="sha256:" + "b" * 64,
        now="2026-11-17T12:00:00+00:00",
    )
    assert verdict["ok"] is False
    assert verdict["status"] == "needs_review"
    assert verdict["reason"] == "checkpoint_hash_mismatch"


def test_validate_resume_expired_needs_review():
    verdict = validate_resume(
        _checkpoint(),
        current_content_hash=HASH,
        now="2026-11-25T10:00:00+00:00",  # 8 天后
    )
    assert verdict["ok"] is False
    assert verdict["reason"] == "checkpoint_expired"


def test_write_and_read_checkpoint(tmp_path):
    checkpoint = _checkpoint()
    target = write_checkpoint(checkpoint, tmp_path / "ckpt.json")
    assert read_checkpoint(target) == checkpoint
