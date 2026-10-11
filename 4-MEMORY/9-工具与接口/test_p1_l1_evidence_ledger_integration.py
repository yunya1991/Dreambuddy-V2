"""P1-L1 Evidence Ledger 接入 record/verify + PoE 信任机制 + 33-REA 闭环

SPEC: SPEC-CognitiveSystem-Evolution.md §2.3.4 P0-3 + §3.3 + §2.3.4 PoE 增强

三个子任务：
  P1-L1-1: Evidence Ledger 接入 record/verify（写 receipt）
  P1-L1-2: PoE 信任机制（无 receipt 不信任，FAIL-OPEN 默认）
  P1-L1-3: 33-REA → Ledger → record 闭环验证

RED 契约：
  - record() 后 Ledger 中有对应 EvidenceEntry（subject="record", object=memory_id）
  - _handle_record 返回结果含 receipt_hash 字段
  - verify() 返回结果含 poe_trust: bool（有 receipt=True，无 receipt=False）
  - 无 receipt 的 verify 仍成功（FAIL-OPEN）
  - prepare_record_params() 返回 evidence_entries 字段
  - 每个 evidence_entry 可被 evidence_ledger.append() 接受
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

# 添加同目录到路径
_SCRIPT_DIR = Path(__file__).parent
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))

# 添加 33-REA core 目录到路径（cognitive_integration 模块）
_REA_CORE_DIR = _SCRIPT_DIR.parents[0].parent / "33-REA逆向解析工程" / "core"
if str(_REA_CORE_DIR) not in sys.path:
    sys.path.insert(0, str(_REA_CORE_DIR))


# ─────────────────────────────── P1-L1-1: record 接入 Evidence Ledger ───────────────────────────────

def test_record_appends_to_evidence_ledger(tmp_path):
    """RED: record() 后 Evidence Ledger 中有对应条目。

    契约：
      - EvidenceEntry.subject = "record"
      - EvidenceEntry.object = memory_id（被 record 的记忆 ID）
      - EvidenceEntry.source 含 "cognitive_loop_entry.record"
      - receipt_hash 非空（Merkle 叶子哈希）
    """
    from cognitive_loop_entry import CognitiveLoopEntry
    cle = CognitiveLoopEntry(storage_path=str(tmp_path / "test.db"))
    try:
        memory_id = cle.record(
            content="测试 Evidence Ledger 接入",
            quality_level="C",
            tags=["test", "evidence-ledger"],
            source="test_p1_l1",
        )
        # 查询 Ledger 中是否有对应条目
        entries = cle.evidence_ledger.query(subject="record")
        assert len(entries) >= 1
        # 找到 object == memory_id 的条目
        matched = [e for e in entries if e.object == memory_id]
        assert len(matched) >= 1
        entry = matched[0]
        assert entry.receipt_hash  # 非空
        assert "record" in entry.source
    finally:
        cle.close()


def test_handle_record_returns_receipt_hash(tmp_path):
    """RED: _handle_record 返回结果含 receipt_hash 字段。"""
    from cognitive_mcp_server import _handle_record, _reset_cle
    from cognitive_loop_entry import CognitiveLoopEntry
    _reset_cle()
    cle = CognitiveLoopEntry(storage_path=str(tmp_path / "test.db"))
    with patch("cognitive_mcp_server._get_cle", return_value=cle):
        try:
            result = _handle_record({
                "content": "测试 _handle_record receipt",
                "quality_level": "C",
                "tags": "test,evidence-ledger",
            })
            data = json.loads(result)
            assert "receipt_hash" in data
            assert data["receipt_hash"]  # 非空
        finally:
            cle.close()


# ─────────────────────────────── P1-L1-2: PoE 信任机制 ───────────────────────────────

def test_verify_poe_trust_true_with_receipt(tmp_path):
    """RED: verify() 对有 receipt 的 memory_id 返回 poe_trust=True。"""
    from cognitive_loop_entry import CognitiveLoopEntry
    cle = CognitiveLoopEntry(storage_path=str(tmp_path / "test.db"))
    try:
        memory_id = cle.record(
            content="测试 PoE trust true",
            quality_level="C",
            tags=["test", "poe"],
            source="test_p1_l1",
        )
        result = cle.verify(memory_id, success=True)
        assert "poe_trust" in result
        assert result["poe_trust"] is True
        assert "receipt_hash" in result
    finally:
        cle.close()


def test_verify_poe_trust_false_without_receipt(tmp_path):
    """RED: verify() 对无 receipt 的 memory_id（伪造）返回 poe_trust=False。

    FAIL-OPEN：即使 poe_trust=False，verify 仍成功（success=True）。
    """
    from cognitive_loop_entry import CognitiveLoopEntry
    cle = CognitiveLoopEntry(storage_path=str(tmp_path / "test.db"))
    try:
        # 使用一个不存在于 Ledger 中的 memory_id
        # 先 record 一条（产生 receipt），再 verify 一个不同的 memory_id
        cle.record(
            content="测试 PoE trust false 占位",
            quality_level="C",
            source="test_p1_l1",
        )
        # 用一个不存在的 memory_id（格式正确但不在系统中）
        fake_id = "VM-9999999999-fake0001"
        result = cle.verify(fake_id, success=True)
        assert "poe_trust" in result
        assert result["poe_trust"] is False
        # FAIL-OPEN：verify 仍成功
        assert result["success"] is True
    finally:
        cle.close()


def test_poe_enforcement_mode_optional(tmp_path):
    """RED: PoE enforcement 默认 FAIL-OPEN（不阻塞 verify）。

    即使 memory_id 无 receipt，verify 仍返回 success=True。
    PoE 是标记机制，不是硬阻塞——硬阻塞留给上层调用方判断。
    """
    from cognitive_loop_entry import CognitiveLoopEntry
    cle = CognitiveLoopEntry(storage_path=str(tmp_path / "test.db"))
    try:
        fake_id = "VM-9999999999-fake0002"
        result = cle.verify(fake_id, success=True)
        # FAIL-OPEN：success 仍为 True
        assert result["success"] is True
        assert result["poe_trust"] is False
    finally:
        cle.close()


# ─────────────────────────────── P1-L1-3: 33-REA → Ledger → record 闭环 ───────────────────────────────

def test_prepare_record_params_includes_evidence_entries():
    """RED: prepare_record_params() 返回 evidence_entries 字段。

    33-REA 的每条分析结论应转换为 EvidenceEntry 供 Agent 一并写入 Ledger。
    """
    from cognitive_integration import prepare_record_params
    # 构造一个模拟的 investigation 结果
    investigation = {
        "target": "test_target",
        "feature": "test_feature",
        "summary": "测试 33-REA 闭环",
        "phases": {
            "locate": {
                "language": "python",
                "target_type": "module",
                "valid": True,
                "modules": ["mod_a"],
                "entry_points": ["func_a"],
            },
            "trace": {
                "all_functions": ["func_a", "func_b"],
                "callers": {"func_a": ["func_b"]},
            },
            "reduce": {
                "functions": [{"name": "func_a"}],
                "patterns": [{"type": "conditional_branch"}],
            },
        },
        "evidence": [
            _make_mock_evidence("func_a 调用了 func_b", "derivation", 0.85,
                                 "33-REA:python_analyzer.py:42"),
            _make_mock_evidence("func_b 是入口点", "observation", 0.90,
                                 "33-REA:python_analyzer.py:15"),
        ],
        "known_gaps": ["无法确定 func_b 返回值类型"],
    }
    params = prepare_record_params(investigation)
    assert "evidence_entries" in params
    assert isinstance(params["evidence_entries"], list)
    assert len(params["evidence_entries"]) == 2
    # 每个 entry 应可构造 EvidenceEntry
    from evidence_ledger import EvidenceEntry
    for entry_dict in params["evidence_entries"]:
        entry = EvidenceEntry(**entry_dict)
        assert entry.subject
        assert entry.relation
        assert entry.object


def test_evidence_entries_appendable_to_ledger(tmp_path):
    """RED: prepare_record_params() 返回的 evidence_entries 可被 append 到 Ledger。"""
    from cognitive_integration import prepare_record_params
    from evidence_ledger import EvidenceLedger, EvidenceEntry
    investigation = {
        "target": "test_target",
        "feature": "test_feature",
        "summary": "测试闭环 appendable",
        "phases": {
            "locate": {"language": "python", "target_type": "module", "valid": True},
            "trace": {"all_functions": [], "callers": {}},
            "reduce": {"functions": [], "patterns": []},
        },
        "evidence": [
            _make_mock_evidence("结论1", "derivation", 0.85,
                                 "33-REA:trace.py:10"),
        ],
        "known_gaps": [],
    }
    params = prepare_record_params(investigation)
    ledger = EvidenceLedger(db_path=tmp_path / "test_33rea_ledger.db")
    try:
        receipts = []
        for entry_dict in params["evidence_entries"]:
            entry = EvidenceEntry(**entry_dict)
            receipt = ledger.append(entry)
            assert receipt  # 非空
            receipts.append(receipt)
        # 验证 Merkle 根非空
        assert ledger.get_merkle_root() != "0" * 64
        # 验证完整性
        assert ledger.verify_integrity() is True
        # 验证条目数
        all_entries = ledger.query_all()
        assert len(all_entries) == len(receipts)
    finally:
        ledger.close()


def test_33rea_record_ledger_closed_loop(tmp_path):
    """RED: 33-REA → prepare_record_params → record + ledger.append 闭环。

    模拟 Agent 的工作流：
      1. investigation → prepare_record_params()
      2. params["content"] → cle.record() → 生成 memory_id + receipt
      3. params["evidence_entries"] → ledger.append() → 生成 receipts
      4. cle.verify(memory_id) → poe_trust=True（有 receipt）
    """
    from cognitive_integration import prepare_record_params
    from cognitive_loop_entry import CognitiveLoopEntry
    from evidence_ledger import EvidenceEntry
    investigation = {
        "target": "closed_loop_target",
        "feature": "closed_loop_feature",
        "summary": "测试 33-REA 闭环",
        "phases": {
            "locate": {"language": "python", "target_type": "module", "valid": True},
            "trace": {"all_functions": ["f1"], "callers": {}},
            "reduce": {"functions": [], "patterns": []},
        },
        "evidence": [
            _make_mock_evidence("闭环结论", "derivation", 0.88,
                                 "33-REA:trace.py:1"),
        ],
        "known_gaps": ["闭环测试 gap"],
    }
    params = prepare_record_params(investigation)
    cle = CognitiveLoopEntry(storage_path=str(tmp_path / "closed_loop.db"))
    try:
        # Step 2: record → memory_id + receipt
        memory_id = cle.record(
            content=params["content"],
            quality_level=params["quality_level"],
            tags=params["tags"].split(","),
            source="33-REA",
            level="derivation",
        )
        # Step 3: evidence_entries → ledger.append
        for entry_dict in params["evidence_entries"]:
            entry = EvidenceEntry(**entry_dict)
            # 覆盖 source 关联到 memory_id
            entry.source = f"memory_id={memory_id};" + entry.source
            cle.evidence_ledger.append(entry)
        # Step 4: verify → poe_trust=True
        result = cle.verify(memory_id, success=True)
        assert result["poe_trust"] is True
        assert result["receipt_hash"]
        # 验证 Ledger 中有 33-REA 的条目
        rea_entries = cle.evidence_ledger.query(subject="33-REA")
        assert len(rea_entries) >= 1
    finally:
        cle.close()


# ─────────────────────────────── 辅助函数 ───────────────────────────────

def _make_mock_evidence(content, level, confidence, source):
    """构造一个模拟的 33-REA Evidence 对象。"""
    from enum import Enum

    class MockLevel(Enum):
        OBSERVATION = "observation"
        DERIVATION = "derivation"
        INFERENCE = "inference"
        UNKNOWN = "unknown"

    class MockEvidence:
        def __init__(self, content, level_str, confidence, source):
            self.content = content
            self.level = MockLevel(level_str) if isinstance(level_str, str) else level_str
            self.confidence = confidence
            self.source = source
            self.provenance = source

    return MockEvidence(content, level, confidence, source)
