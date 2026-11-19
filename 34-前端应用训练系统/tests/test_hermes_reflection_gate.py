# -*- coding: utf-8 -*-
"""D3D+: Hermes 反思门禁 / 广义认知注入契约。"""

import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from core.hermes_reflection_gate import (  # noqa: E402
    ReflectionInbox,
    ReflectionInsight,
    ReflectionProposal,
    evaluate_reflection,
    reflection_gate_enabled,
)

NOW = 1_700_000_000.0


def proposal(**overrides):
    data = {
        "reflection_id": "RF-1",
        "trace_id": "tr-1",
        "task_id": "TK-1",
        "summary": "本次验收发现测试覆盖不足",
        "insights": (
            ReflectionInsight(
                claim="缺少边界用例",
                evidence_refs=("test:coverage",),
                confidence=0.8,
            ),
        ),
        "evidence_refs": ("test:coverage",),
        "confidence": 0.8,
    }
    data.update(overrides)
    return ReflectionProposal(**data)


def test_valid_reflection_is_candidate_only():
    result = evaluate_reflection(proposal(), now=NOW)
    assert result.allowed
    artifact = result.artifact
    assert artifact["injection"]["mode"] == "candidate_only"
    assert artifact["injection"]["requires_review"] is True
    assert artifact["provenance"]["gate"] == "hermes_reflection_gate"
    assert artifact["content_hash"].startswith("sha256:")
    assert "reasoning" not in artifact


def test_missing_trace_and_evidence_are_rejected():
    result = evaluate_reflection(proposal(trace_id="", evidence_refs=()), now=NOW)
    assert not result.allowed
    assert "trace_id_required" in result.reasons
    assert "evidence_refs_required" in result.reasons


def test_every_insight_requires_evidence():
    result = evaluate_reflection(
        proposal(insights=(ReflectionInsight(claim="裸 claim", evidence_refs=()),)),
        now=NOW,
    )
    assert not result.allowed
    assert "insight[0].evidence_required" in result.reasons


def test_write_actions_are_forbidden_but_readonly_actions_allowed():
    write = evaluate_reflection(proposal(proposed_actions=("memory_write",)), now=NOW)
    assert not write.allowed
    assert any(reason.startswith("write_action_forbidden") for reason in write.reasons)

    readonly = evaluate_reflection(proposal(proposed_actions=("recall",)), now=NOW)
    assert readonly.allowed


def test_secret_and_raw_cot_are_rejected():
    secret = evaluate_reflection(
        proposal(summary="发现 sk-abcdefghijklmnop123456 泄漏"), now=NOW  # secret-scan: allow
    )
    assert not secret.allowed
    assert "secret_detected" in secret.reasons

    cot = evaluate_reflection(proposal(metadata={"reasoning": "step 1..."}), now=NOW)
    assert not cot.allowed
    assert any(reason.startswith("raw_cot_forbidden") for reason in cot.reasons)


def test_low_confidence_is_rejected():
    result = evaluate_reflection(proposal(confidence=0.2), now=NOW)
    assert not result.allowed
    assert "confidence_below_min" in result.reasons


def test_oversize_artifact_is_rejected():
    huge = tuple(
        ReflectionInsight(claim="x" * 3000, evidence_refs=("e:%d" % index,), confidence=0.9)
        for index in range(10)
    )
    result = evaluate_reflection(proposal(insights=huge), now=NOW)
    assert not result.allowed
    assert "artifact_too_large" in result.reasons


def test_duplicate_reflection_is_rejected():
    first = evaluate_reflection(proposal(), now=NOW)
    second = evaluate_reflection(
        proposal(), now=NOW + 1, seen_keys={first.artifact["reflection_id"]}
    )
    assert not second.allowed
    assert "duplicate_reflection" in second.reasons


def test_inbox_is_idempotent_across_restart(tmp_path):
    path = str(tmp_path / "reflection_inbox.jsonl")
    inbox = ReflectionInbox(path, enabled=True)

    first = inbox.evaluate_and_enqueue(proposal(), now=NOW)
    assert first.allowed

    second = inbox.evaluate_and_enqueue(proposal(), now=NOW + 10)
    assert not second.allowed
    assert "duplicate_reflection" in second.reasons

    # 重启：从文件重载去重键
    restarted = ReflectionInbox(path, enabled=True)
    third = restarted.evaluate_and_enqueue(proposal(), now=NOW + 20)
    assert not third.allowed

    lines = [json.loads(line) for line in open(path, encoding="utf-8") if line.strip()]
    assert len(lines) == 1
    assert lines[0]["injection"]["mode"] == "candidate_only"


def test_inbox_rejects_non_candidate_artifact(tmp_path):
    inbox = ReflectionInbox(str(tmp_path / "inbox.jsonl"), enabled=True)
    assert inbox.enqueue({"reflection_id": "RF-X", "content_hash": "sha256:x"}) is False
    assert (
        inbox.enqueue(
            {
                "reflection_id": "RF-Y",
                "content_hash": "sha256:y",
                "injection": {"mode": "direct_write"},
            }
        )
        is False
    )


# ── 默认关闭：认知系统走原路径 ──────────────────────────────────────────
def test_gate_is_disabled_by_default(tmp_path, monkeypatch):
    monkeypatch.delenv("enable_hermes_reflection_gate", raising=False)
    monkeypatch.delenv("ENABLE_HERMES_REFLECTION_GATE", raising=False)

    assert reflection_gate_enabled() is False
    inbox = ReflectionInbox(str(tmp_path / "inbox.jsonl"))
    assert inbox.enabled is False

    result = inbox.evaluate_and_enqueue(proposal(), now=NOW)
    assert not result.allowed
    assert result.reasons == ("gate_disabled",)
    assert not (tmp_path / "inbox.jsonl").exists()
    assert inbox.enqueue(evaluate_reflection(proposal(), now=NOW).artifact) is False


def test_gate_can_be_enabled_explicitly_or_by_env(tmp_path, monkeypatch):
    monkeypatch.delenv("enable_hermes_reflection_gate", raising=False)
    monkeypatch.delenv("ENABLE_HERMES_REFLECTION_GATE", raising=False)

    explicit = ReflectionInbox(str(tmp_path / "a.jsonl"), enabled=True)
    assert explicit.evaluate_and_enqueue(proposal(), now=NOW).allowed

    monkeypatch.setenv("enable_hermes_reflection_gate", "1")
    assert reflection_gate_enabled() is True
    by_env = ReflectionInbox(str(tmp_path / "b.jsonl"))
    assert by_env.enabled is True
    assert by_env.evaluate_and_enqueue(proposal(), now=NOW).allowed
