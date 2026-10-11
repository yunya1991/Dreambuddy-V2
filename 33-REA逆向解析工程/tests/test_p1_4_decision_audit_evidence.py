"""P1-4 RED 测试：prepare_decision/audit_record_params 补 evidence_entries 字段。

SPEC §3.3：33-REA 的每条分析结论直接写入 Evidence Ledger。
P1-L1-3 已为 prepare_record_params 补 evidence_entries（VM-1791722208926）。
P1-4 对 prepare_decision_record_params / prepare_audit_record_params 做同样处理。

RED 契约：
  - 两个 prepare_*_record_params 返回的 dict 必须含 "evidence_entries" 键
  - evidence_entries 为 list[dict]，空 evidence 时为 []（非缺失）
  - 有 evidence 时 evidence_entries 非空
  - 每个 entry 可被 EvidenceEntry(**entry) 构造（字段合法）
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from core.cognitive_integration import (
    prepare_audit_record_params,
    prepare_decision_record_params,
)


# ─────────────────────────── 测试用 Evidence mock ───────────────────────────

def _make_evidence(content="结论", level="observation", provenance="test", confidence=0.8):
    """构造一个类似 33-REA Evidence 的 mock 对象。"""
    return type("E", (), {
        "content": content,
        "level": type("L", (), {"value": level})(),
        "provenance": provenance,
        "source": provenance,
        "confidence": confidence,
    })()


# ─────────────────────────── RED: decision ───────────────────────────

def test_decision_record_params_has_evidence_entries_field():
    """RED: prepare_decision_record_params 返回 evidence_entries 字段。"""
    decision_result = {
        "target": "/mock/proj",
        "decisions": [{"decision": "d1", "context": "c1"}],
        "evidence": [],
    }
    params = prepare_decision_record_params(decision_result)
    assert "evidence_entries" in params, "decision 参数应含 evidence_entries 字段 (P1-4)"


def test_decision_record_params_evidence_entries_empty_when_no_evidence():
    """RED: 无 evidence 时 evidence_entries 为空列表（非 None/缺失）。"""
    decision_result = {
        "target": "/mock/proj",
        "decisions": [],
        "evidence": [],
    }
    params = prepare_decision_record_params(decision_result)
    assert params["evidence_entries"] == [], "无 evidence 时 evidence_entries 应为 []"


def test_decision_record_params_evidence_entries_nonempty_when_evidence_present():
    """RED: 有 evidence 时 evidence_entries 非空。"""
    decision_result = {
        "target": "/mock/proj",
        "decisions": [{"decision": "d1"}],
        "evidence": [
            _make_evidence(content="决策证据1", level="derivation"),
            _make_evidence(content="决策证据2", level="observation"),
        ],
    }
    params = prepare_decision_record_params(decision_result)
    entries = params["evidence_entries"]
    assert isinstance(entries, list)
    assert len(entries) == 2, f"有 2 条 evidence 应产出 2 个 entry, got {len(entries)}"


def test_decision_record_params_evidence_entry_structure_legal():
    """RED: evidence_entries 中每个 entry 可被 EvidenceEntry 构造。"""
    sys.path.insert(0, str(Path(__file__).parent.parent.parent / "4-MEMORY" / "9-工具与接口"))
    from evidence_ledger import EvidenceEntry

    decision_result = {
        "target": "/mock/proj",
        "decisions": [{"decision": "d1"}],
        "evidence": [_make_evidence(content="结构测试", level="observation")],
    }
    params = prepare_decision_record_params(decision_result)
    for entry in params["evidence_entries"]:
        obj = EvidenceEntry(**entry)
        assert obj.subject
        assert obj.object
        assert 0.0 <= obj.confidence <= 1.0


# ─────────────────────────── RED: audit ───────────────────────────

def test_audit_record_params_has_evidence_entries_field():
    """RED: prepare_audit_record_params 返回 evidence_entries 字段。"""
    audit_result = {
        "target": "/mock/ai_output",
        "evidence_chain_score": 0.5,
        "coverage_score": 0.5,
        "complexity_penalty": 0.2,
        "poe_score": 0.5,
        "gate_decision": "review",
        "cognitive_debt": [],
        "evidence": [],
    }
    params = prepare_audit_record_params(audit_result)
    assert "evidence_entries" in params, "audit 参数应含 evidence_entries 字段 (P1-4)"


def test_audit_record_params_evidence_entries_empty_when_no_evidence():
    """RED: 无 evidence 时 evidence_entries 为空列表。"""
    audit_result = {
        "target": "/mock",
        "evidence_chain_score": 0.5,
        "coverage_score": 0.5,
        "complexity_penalty": 0.2,
        "poe_score": 0.5,
        "gate_decision": "review",
        "cognitive_debt": [],
        "evidence": [],
    }
    params = prepare_audit_record_params(audit_result)
    assert params["evidence_entries"] == [], "无 evidence 时 evidence_entries 应为 []"


def test_audit_record_params_evidence_entries_nonempty_when_evidence_present():
    """RED: 有 evidence 时 evidence_entries 非空。"""
    audit_result = {
        "target": "/mock/ai_output",
        "evidence_chain_score": 0.45,
        "coverage_score": 0.3,
        "complexity_penalty": 0.4,
        "poe_score": 0.35,
        "gate_decision": "reject",
        "cognitive_debt": [],
        "evidence": [
            _make_evidence(content="审计证据1", level="observation", confidence=0.9),
        ],
    }
    params = prepare_audit_record_params(audit_result)
    entries = params["evidence_entries"]
    assert isinstance(entries, list)
    assert len(entries) == 1, f"有 1 条 evidence 应产出 1 个 entry, got {len(entries)}"


def test_audit_record_params_evidence_entry_structure_legal():
    """RED: audit evidence_entries 中每个 entry 可被 EvidenceEntry 构造。"""
    sys.path.insert(0, str(Path(__file__).parent.parent.parent / "4-MEMORY" / "9-工具与接口"))
    from evidence_ledger import EvidenceEntry

    audit_result = {
        "target": "/mock/ai_output",
        "evidence_chain_score": 0.5,
        "coverage_score": 0.5,
        "complexity_penalty": 0.2,
        "poe_score": 0.5,
        "gate_decision": "review",
        "cognitive_debt": [],
        "evidence": [_make_evidence(content="审计结构测试", level="derivation")],
    }
    params = prepare_audit_record_params(audit_result)
    for entry in params["evidence_entries"]:
        obj = EvidenceEntry(**entry)
        assert obj.subject
        assert obj.object
        assert 0.0 <= obj.confidence <= 1.0
