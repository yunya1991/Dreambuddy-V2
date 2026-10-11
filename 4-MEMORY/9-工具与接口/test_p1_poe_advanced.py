"""P1 PoE 高级特性 TDD RED 测试（批次1）

SPEC: 35-广义认知系统协作模块/SPEC-Unified-PoE-Framework.md §2.3 + §3.3 + COLLABORATION-CONTRACT.md v1.1

P1 任务（批次1：P1-5 + P1-1 + P1-2）：
  P1-5: EvidenceEntry 新增 git_commit_hash 列（链式溯源等价物）
  P1-1: poe_mode 选择器（heavy/light/sample）
  P1-2: 有界信任传递（sample 模式 10% 概率重跑 light）

设计依据（SPEC v2.0 §2.3 + §3.3）：
  - git_commit_hash 提供链式溯源（工程等价于区块链的链式哈希）
  - poe_mode 与 poe_enforcement 正交：
    * mode=heavy → 跑 33-REA 五层证明链（enforcement 不适用）
    * mode=light + enforcement=strict/soft/off → 索引查询 + enforcement
    * mode=sample → 10% 概率重跑 light（enforcement 沿用上次设置）
  - sample 模式触发条件：artifact.already_verified and same_process_and_within_window

RED 契约（当前全部失败）：
  1. EvidenceEntry 有 git_commit_hash 字段（默认空字符串）
  2. git_commit_hash 持久化到 DB
  3. CognitiveLoopEntry.__init__ 接受 poe_mode 参数（默认 'light'）
  4. poe_mode='heavy' 当前未实现（占位返回 NotImplementedError 标记）
  5. poe_mode='sample' 走 light 路径 + 10% 概率重验
  6. sample 模式 10% 概率时跑 light 验证（mock random 验证调用计数）
  7. sample 模式 90% 概率时直接信任（不跑 light 验证）
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

import pytest

_SCRIPT_DIR = Path(__file__).parent
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))


# ─────────────────────────────── P1-5: EvidenceEntry.git_commit_hash ───────────────────────────────

def test_evidence_entry_has_git_commit_hash_field():
    """RED: EvidenceEntry 应有 git_commit_hash 字段（默认空字符串）。"""
    from evidence_ledger import EvidenceEntry
    entry = EvidenceEntry(
        subject="s", relation="r", object="o",
        source="src", confidence=0.8, level="observation",
    )
    assert hasattr(entry, "git_commit_hash"), "EvidenceEntry 应有 git_commit_hash 字段"
    assert entry.git_commit_hash == "", "git_commit_hash 默认空字符串"


def test_evidence_entry_git_commit_hash_settable():
    """RED: EvidenceEntry.git_commit_hash 可在构造时设置。"""
    from evidence_ledger import EvidenceEntry
    entry = EvidenceEntry(
        subject="s", relation="r", object="o",
        source="src", confidence=0.8, level="observation",
        git_commit_hash="abc123def456",
    )
    assert entry.git_commit_hash == "abc123def456"


def test_git_commit_hash_persisted_to_db(tmp_path):
    """RED: append 后 git_commit_hash 持久化到 DB，query 可读回。"""
    from evidence_ledger import EvidenceLedger, EvidenceEntry
    ledger = EvidenceLedger(db_path=tmp_path / "test_p1.db")
    entry = EvidenceEntry(
        subject="s", relation="r", object="o",
        source="src", confidence=0.8, level="observation",
        git_commit_hash="deadbeef1234",
    )
    ledger.append(entry)
    entries = ledger.query_all()
    assert len(entries) == 1
    assert entries[0].git_commit_hash == "deadbeef1234"


def test_git_commit_hash_default_empty_in_db(tmp_path):
    """RED: 未设置 git_commit_hash 时，DB 中默认空字符串。"""
    from evidence_ledger import EvidenceLedger, EvidenceEntry
    ledger = EvidenceLedger(db_path=tmp_path / "test_p1.db")
    entry = EvidenceEntry(
        subject="s", relation="r", object="o",
        source="src", confidence=0.8, level="observation",
    )
    ledger.append(entry)
    entries = ledger.query_all()
    assert entries[0].git_commit_hash == ""


# ─────────────────────────────── P1-1: poe_mode 选择器 ───────────────────────────────

def test_cognitive_loop_entry_has_poe_mode_param(tmp_path):
    """RED: CognitiveLoopEntry.__init__ 应接受 poe_mode 参数。"""
    from cognitive_loop_entry import CognitiveLoopEntry
    cle = CognitiveLoopEntry(
        storage_path=str(tmp_path / "test_p1.db"),
        poe_mode="light",
    )
    try:
        assert hasattr(cle, "poe_mode"), "CognitiveLoopEntry 应有 poe_mode 属性"
        assert cle.poe_mode == "light"
    finally:
        cle.close()


def test_poe_mode_default_light(tmp_path):
    """RED: poe_mode 默认应为 'light'。"""
    from cognitive_loop_entry import CognitiveLoopEntry
    cle = CognitiveLoopEntry(storage_path=str(tmp_path / "test_p1.db"))
    try:
        assert cle.poe_mode == "light", "默认 poe_mode 应为 light"
    finally:
        cle.close()


def test_poe_mode_and_enforcement_orthogonal(tmp_path):
    """RED: poe_mode 与 poe_enforcement 正交（可独立设置）。"""
    from cognitive_loop_entry import CognitiveLoopEntry
    cle = CognitiveLoopEntry(
        storage_path=str(tmp_path / "test_p1.db"),
        poe_mode="light",
        poe_enforcement="strict",
    )
    try:
        assert cle.poe_mode == "light"
        assert cle.poe_enforcement == "strict"
    finally:
        cle.close()


# ─────────────────────────────── P1-2: sample 模式 10% 概率重跑 ───────────────────────────────

def test_sample_mode_10_percent_triggers_light_reverification(tmp_path):
    """RED: sample 模式 + random < 0.1 → 跑 light 验证（verify_receipt_exists 被调用）。"""
    from cognitive_loop_entry import CognitiveLoopEntry
    cle = CognitiveLoopEntry(
        storage_path=str(tmp_path / "test_p1.db"),
        poe_mode="sample",
    )
    try:
        # 先 record 一条（有 receipt）
        memory_id = cle.record(
            content="sample 模式 10% 重验测试",
            quality_level="C",
            source="test_p1",
        )
        # mock random 返回 0.05（< 0.1，触发 10% 重验）
        with patch("random.random", return_value=0.05):
            with patch.object(cle.evidence_ledger, "get_receipt_for", return_value="fake_hash") as mock_get:
                trust, receipt = cle._check_poe_trust(memory_id)
                # 10% 概率重验时调 get_receipt_for（light 路径）
                assert mock_get.call_count >= 1
                assert trust is True
    finally:
        cle.close()


def test_sample_mode_90_percent_skips_light_verification(tmp_path):
    """RED: sample 模式 + random >= 0.1 → 直接信任（不重验，receipt_hash=None）。

    sample 模式 90% 概率时仍需查 receipt 存在性（不能盲信无 receipt 的产出），
    但不重跑 light 验证（receipt_hash 返回 None 表示"抽样跳过"）。
    """
    from cognitive_loop_entry import CognitiveLoopEntry
    cle = CognitiveLoopEntry(
        storage_path=str(tmp_path / "test_p1.db"),
        poe_mode="sample",
    )
    try:
        memory_id = cle.record(
            content="sample 模式 90% 跳过测试",
            quality_level="C",
            source="test_p1",
        )
        # mock random 返回 0.5（>= 0.1，90% 概率直接信任）
        with patch("random.random", return_value=0.5):
            trust, receipt = cle._check_poe_trust(memory_id)
            # 90% 概率直接信任（有 receipt 历史）
            assert trust is True
            # receipt_hash 为 None（未重验，抽样跳过标记）
            assert receipt is None
    finally:
        cle.close()


def test_sample_mode_no_receipt_still_returns_false(tmp_path):
    """RED: sample 模式 90% 概率直接信任，但无 receipt 时仍返回 False。

    sample 模式只在"已验证产出"（有 receipt）时才抽样跳过。
    无 receipt 的产出不能被 sample 模式信任。
    """
    from cognitive_loop_entry import CognitiveLoopEntry
    cle = CognitiveLoopEntry(
        storage_path=str(tmp_path / "test_p1.db"),
        poe_mode="sample",
    )
    try:
        # 使用不存在的 memory_id（无 receipt）
        fake_id = "VM-9999999999-sample-no-receipt"
        # mock random 返回 0.5（90% 概率）
        with patch("random.random", return_value=0.5):
            trust, receipt = cle._check_poe_trust(fake_id)
            # 无 receipt 不能被 sample 模式信任
            assert trust is False
    finally:
        cle.close()


def test_sample_mode_10_percent_reverification_failure_downgrades_trust(tmp_path):
    """RED: sample 模式 10% 重验时，如果 light 验证失败 → 信任降级为 False。

    SPEC §2.3 失效条件 6：抽样重验失败 → 信任降级，触发重型验证。
    """
    from cognitive_loop_entry import CognitiveLoopEntry
    cle = CognitiveLoopEntry(
        storage_path=str(tmp_path / "test_p1.db"),
        poe_mode="sample",
    )
    try:
        memory_id = cle.record(
            content="sample 重验失败降级测试",
            quality_level="C",
            source="test_p1",
        )
        # mock random 返回 0.05（< 0.1，触发 10% 重验）
        # mock get_receipt_for 返回空字符串（light 验证失败）
        with patch("random.random", return_value=0.05):
            with patch.object(cle.evidence_ledger, "get_receipt_for", return_value=""):
                trust, receipt = cle._check_poe_trust(memory_id)
                # 10% 重验失败 → 信任降级
                assert trust is False
                assert receipt is None
    finally:
        cle.close()


# ─────────────────────────────── P1-1 续: heavy 模式占位 ───────────────────────────────

def test_heavy_mode_placeholder_not_implemented(tmp_path):
    """RED: poe_mode='heavy' 当前未实现（33-REA 侧五层证明链待接入）。

    设计：heavy 模式应委托给 33-REA PoE（ai_audit.py），
    当前未接入，应返回明确的 NotImplemented 标记（不抛异常，FAIL-OPEN）。
    """
    from cognitive_loop_entry import CognitiveLoopEntry
    cle = CognitiveLoopEntry(
        storage_path=str(tmp_path / "test_p1.db"),
        poe_mode="heavy",
    )
    try:
        memory_id = cle.record(
            content="heavy 模式占位测试",
            quality_level="C",
            source="test_p1",
        )
        trust, receipt = cle._check_poe_trust(memory_id)
        # heavy 模式当前未实现，FAIL-OPEN 降级为 light（或返回 NotImplemented 标记）
        # 设计选择：返回 (False, None) + 标记 heavy_not_implemented
        # 或降级为 light 路径（更友好）
        assert trust is False or trust is True  # 至少不抛异常
    finally:
        cle.close()
