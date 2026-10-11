"""P0-3 Evidence Ledger 骨架 TDD RED 测试

验证 evidence_ledger.py 提供集中化决策审计 trail，使用 Merkle 树保证不可篡改。

RED 契约：
  - EvidenceEntry dataclass 含 subject/relation/object/timestamp/source/confidence/receipt_hash
  - EvidenceLedger.append() 返回 receipt_hash
  - append 后 merkle_root 改变
  - verify_entry 对有效条目返回 True
  - 篡改后 verify_integrity 返回 False
  - query_by_subject / query_by_source 支持查询
  - 链式哈希：prev_hash 指向前一条目

参考：SPEC-CognitiveSystem-Evolution.md §2.3.4 P0-3 + §3.5 M3（Merkle树）
"""
from __future__ import annotations

import time
from pathlib import Path

import pytest


# ─────────────────────────────── RED: EvidenceEntry ───────────────────────────────

def test_evidence_entry_creation():
    """RED: EvidenceEntry 能正确创建，含所有必需字段。"""
    from evidence_ledger import EvidenceEntry
    entry = EvidenceEntry(
        subject="record_hook",
        relation="调用了",
        object="skill_indexer.record_hook",
        source="cognitive_mcp_server.py:412",
        confidence=0.85,
        level="observation",
    )
    assert entry.subject == "record_hook"
    assert entry.relation == "调用了"
    assert entry.object == "skill_indexer.record_hook"
    assert entry.source == "cognitive_mcp_server.py:412"
    assert entry.confidence == 0.85
    assert entry.level == "observation"
    assert entry.entry_id  # 非空
    assert entry.timestamp > 0  # ns 级时间戳


# ─────────────────────────────── RED: EvidenceLedger append ───────────────────────────────

def test_ledger_append_returns_receipt(tmp_path):
    """RED: append() 返回 receipt_hash（Merkle 叶子哈希）。"""
    from evidence_ledger import EvidenceLedger, EvidenceEntry
    ledger = EvidenceLedger(db_path=tmp_path / "test_ledger.db")
    entry = EvidenceEntry(
        subject="test",
        relation="执行了",
        object="action",
        source="test_source",
        confidence=0.9,
        level="observation",
    )
    receipt = ledger.append(entry)
    assert receipt  # 非空字符串
    assert isinstance(receipt, str)


def test_ledger_merkle_root_changes_on_append(tmp_path):
    """RED: append 后 merkle_root 改变。"""
    from evidence_ledger import EvidenceLedger, EvidenceEntry
    ledger = EvidenceLedger(db_path=tmp_path / "test_ledger.db")
    root_before = ledger.get_merkle_root()
    entry = EvidenceEntry(
        subject="test",
        relation="执行了",
        object="action",
        source="test_source",
        confidence=0.9,
        level="observation",
    )
    ledger.append(entry)
    root_after = ledger.get_merkle_root()
    assert root_before != root_after


# ─────────────────────────────── RED: 完整性验证 ───────────────────────────────

def test_ledger_verify_integrity_valid(tmp_path):
    """RED: 未篡改的 ledger verify_integrity 返回 True。"""
    from evidence_ledger import EvidenceLedger, EvidenceEntry
    ledger = EvidenceLedger(db_path=tmp_path / "test_ledger.db")
    for i in range(3):
        ledger.append(EvidenceEntry(
            subject=f"subj_{i}", relation="rel", object=f"obj_{i}",
            source=f"src_{i}", confidence=0.8, level="observation",
        ))
    assert ledger.verify_integrity() is True


def test_ledger_verify_integrity_tampered(tmp_path):
    """RED: 篡改条目后 verify_integrity 返回 False。"""
    from evidence_ledger import EvidenceLedger, EvidenceEntry
    db_path = tmp_path / "test_ledger.db"
    ledger = EvidenceLedger(db_path=db_path)
    for i in range(3):
        ledger.append(EvidenceEntry(
            subject=f"subj_{i}", relation="rel", object=f"obj_{i}",
            source=f"src_{i}", confidence=0.8, level="observation",
        ))
    # 篡改：直接修改数据库中的条目
    ledger._tamper_for_test(0, subject="HACKED")
    assert ledger.verify_integrity() is False


# ─────────────────────────────── RED: 查询 ───────────────────────────────

def test_ledger_query_by_subject(tmp_path):
    """RED: 按 subject 查询返回匹配条目。"""
    from evidence_ledger import EvidenceLedger, EvidenceEntry
    ledger = EvidenceLedger(db_path=tmp_path / "test_ledger.db")
    ledger.append(EvidenceEntry(
        subject="record_hook", relation="调用", object="func_a",
        source="src1", confidence=0.8, level="observation",
    ))
    ledger.append(EvidenceEntry(
        subject="verify_hook", relation="调用", object="func_b",
        source="src2", confidence=0.7, level="derivation",
    ))
    ledger.append(EvidenceEntry(
        subject="record_hook", relation="调用", object="func_c",
        source="src3", confidence=0.9, level="observation",
    ))
    results = ledger.query(subject="record_hook")
    assert len(results) == 2
    assert all(r.subject == "record_hook" for r in results)


def test_ledger_query_by_source(tmp_path):
    """RED: 按 source 查询返回匹配条目。"""
    from evidence_ledger import EvidenceLedger, EvidenceEntry
    ledger = EvidenceLedger(db_path=tmp_path / "test_ledger.db")
    ledger.append(EvidenceEntry(
        subject="s1", relation="r", object="o1",
        source="VM-12345", confidence=0.8, level="observation",
    ))
    ledger.append(EvidenceEntry(
        subject="s2", relation="r", object="o2",
        source="VM-67890", confidence=0.7, level="derivation",
    ))
    results = ledger.query(source="VM-12345")
    assert len(results) == 1
    assert results[0].source == "VM-12345"


# ─────────────────────────────── RED: 链式哈希 ───────────────────────────────

def test_ledger_chained_hash(tmp_path):
    """RED: 第二条目的 prev_hash 指向第一条目的 receipt_hash。"""
    from evidence_ledger import EvidenceLedger, EvidenceEntry
    ledger = EvidenceLedger(db_path=tmp_path / "test_ledger.db")
    receipt1 = ledger.append(EvidenceEntry(
        subject="s1", relation="r", object="o1",
        source="src1", confidence=0.8, level="observation",
    ))
    receipt2 = ledger.append(EvidenceEntry(
        subject="s2", relation="r", object="o2",
        source="src2", confidence=0.7, level="derivation",
    ))
    entries = ledger.query_all()
    assert len(entries) == 2
    assert entries[1].prev_hash == receipt1


# ─────────────────────────────── RED: FAIL-OPEN ───────────────────────────────

def test_ledger_fail_open_on_storage_error(tmp_path):
    """FAIL-OPEN: 存储失败时 append 不抛异常，返回空字符串。"""
    from evidence_ledger import EvidenceLedger, EvidenceEntry
    ledger = EvidenceLedger(db_path=Path("/nonexistent/path/ledger.db"))
    entry = EvidenceEntry(
        subject="test", relation="r", object="o",
        source="src", confidence=0.8, level="observation",
    )
    receipt = ledger.append(entry)  # 不应抛异常
    assert receipt == ""  # FAIL-OPEN 返回空


def test_ledger_persistence_across_instances(tmp_path):
    """RED: 新实例能加载之前的条目（持久化）。"""
    from evidence_ledger import EvidenceLedger, EvidenceEntry
    db_path = tmp_path / "test_ledger.db"
    ledger1 = EvidenceLedger(db_path=db_path)
    ledger1.append(EvidenceEntry(
        subject="persist_test", relation="r", object="o",
        source="src", confidence=0.8, level="observation",
    ))
    # 新实例加载同一数据库
    ledger2 = EvidenceLedger(db_path=db_path)
    entries = ledger2.query_all()
    assert len(entries) == 1
    assert entries[0].subject == "persist_test"
