"""P1-L1-2b: PoE 信任机制 enforcement 补全

SPEC §2.3.4：无 receipt 的产出不被信任。
SPEC-工程实践复现器 §NFR-0：无证明链的 AI 产出，禁止合入。

之前只实现了"标记"（poe_trust=False），但没有 enforcement。
本测试补全 PoE 的三个 enforcement 行为：

1. receipt 完整性验证 — _check_poe_trust 不只查存在性，还验 Merkle 树
2. verify enforcement — 无 receipt 时质量升级上限为 B（不能到 A/S）
3. recall 降权 — 无 receipt 的记忆在 recall 时 score *= poe_penalty
4. enforcement 模式可配置 — strict/soft/off（默认 soft=FAIL-OPEN）
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

_SCRIPT_DIR = Path(__file__).parent
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))


# ─────────────────────────────── 1. receipt 完整性验证 ───────────────────────────────

def test_check_poe_trust_verifies_merkle_integrity(tmp_path):
    """RED: _check_poe_trust 在 Ledger 被篡改后返回 False。

    不仅查条目存在性，还调 verify_integrity() 验 Merkle 树。
    篡改后即使条目存在，poe_trust 也应为 False。
    """
    from cognitive_loop_entry import CognitiveLoopEntry
    cle = CognitiveLoopEntry(storage_path=str(tmp_path / "test.db"))
    try:
        memory_id = cle.record(
            content="测试 Merkle 完整性",
            quality_level="C",
            source="test_poe",
        )
        # 正常情况：poe_trust=True
        trust, receipt = cle._check_poe_trust(memory_id)
        assert trust is True
        assert receipt

        # 篡改 Ledger
        cle.evidence_ledger._tamper_for_test(0, subject="HACKED")
        # 篡改后：poe_trust 应为 False（完整性验证失败）
        trust2, receipt2 = cle._check_poe_trust(memory_id)
        assert trust2 is False
    finally:
        cle.close()


# ─────────────────────────────── 2. verify enforcement ───────────────────────────────

def test_verify_no_receipt_caps_quality_at_b(tmp_path):
    """RED: 无 receipt 的记忆 verify 时质量升级上限为 B（不能到 A/S）。

    PoE soft 模式：无 receipt 不阻塞 verify，但限制质量等级上限。
    """
    from cognitive_loop_entry import CognitiveLoopEntry
    cle = CognitiveLoopEntry(storage_path=str(tmp_path / "test.db"))
    try:
        # 使用一个不在 Ledger 中的 fake memory_id
        # 先手动写一条记忆到 SQLite（绕过 record，无 receipt）
        from vector_memory_interface import VectorMemoryInterface
        # 直接用 fake_id verify
        fake_id = "VM-9999999999-poe-test01"
        result = cle.verify(fake_id, success=True)
        # FAIL-OPEN: verify 仍成功
        assert result["success"] is True
        # PoE enforcement: poe_trust=False
        assert result["poe_trust"] is False
        # 质量上限为 B（不能到 A/S）
        # 由于记忆不存在，new_quality 是 "C"（FAIL-OPEN 兜底），这符合上限
        # 关键是返回结果中有 poe_quality_cap 字段
        assert "poe_quality_cap" in result
        assert result["poe_quality_cap"] == "B"
    finally:
        cle.close()


def test_verify_with_receipt_no_cap(tmp_path):
    """RED: 有 receipt 的记忆 verify 时无质量上限限制（poe_quality_cap=None）。"""
    from cognitive_loop_entry import CognitiveLoopEntry
    cle = CognitiveLoopEntry(storage_path=str(tmp_path / "test.db"))
    try:
        memory_id = cle.record(
            content="测试有 receipt 无上限",
            quality_level="C",
            source="test_poe",
        )
        result = cle.verify(memory_id, success=True)
        assert result["poe_trust"] is True
        assert result.get("poe_quality_cap") is None
    finally:
        cle.close()


# ─────────────────────────────── 3. recall 降权 ───────────────────────────────

def test_recall_penalizes_no_receipt_memories(tmp_path):
    """RED: recall 时无 receipt 的记忆 score 被降权。

    PoE soft 模式：无 receipt 的记忆 score *= poe_penalty（默认 0.5）。
    有 receipt 的记忆不受影响。
    """
    from cognitive_loop_entry import CognitiveLoopEntry
    cle = CognitiveLoopEntry(storage_path=str(tmp_path / "test.db"))
    try:
        # record 一条（有 receipt）
        mid_with_receipt = cle.record(
            content="有 receipt 的记忆",
            quality_level="C",
            tags=["test", "poe"],
            source="test_poe",
        )
        # 手动写一条无 receipt 的记忆（绕过 record）
        # 通过 _vm.add 直接写
        mid_no_receipt = cle._vm.add(
            content="无 receipt 的记忆",
            quality_level="C",
            confidence=0.3,
            tags=["test", "poe"],
            source="test_poe",
        )
        # recall
        results = cle.recall("记忆", top_k=5, min_quality="C")
        # 两条都应返回
        ids = [r.get("id", "") for r in results]
        assert mid_with_receipt in ids
        assert mid_no_receipt in ids
        # 无 receipt 的记忆应被标记 poe_penalized
        for r in results:
            if r.get("id") == mid_no_receipt:
                assert r.get("poe_penalized") is True
                # score 应被降权
                assert r.get("score", 1.0) < 1.0
    finally:
        cle.close()


# ─────────────────────────────── 4. enforcement 模式可配置 ───────────────────────────────

def test_poe_enforcement_mode_off(tmp_path):
    """RED: poe_enforcement='off' 时不做任何 PoE 检查。

    record 不写 receipt，verify 不检查 poe_trust，recall 不降权。
    """
    from cognitive_loop_entry import CognitiveLoopEntry
    cle = CognitiveLoopEntry(
        storage_path=str(tmp_path / "test.db"),
        poe_enforcement="off",
    )
    try:
        # enforcement=off 时，evidence_ledger 仍存在但 record 不写 receipt
        # 但为了兼容，record 仍写 receipt，只是 verify 不做 enforcement
        memory_id = cle.record(
            content="enforcement off 测试",
            quality_level="C",
            source="test_poe",
        )
        result = cle.verify(memory_id, success=True)
        # enforcement=off: poe_trust 不在结果中（或为 None）
        assert result.get("poe_quality_cap") is None
    finally:
        cle.close()


def test_poe_enforcement_mode_strict(tmp_path):
    """RED: poe_enforcement='strict' 时无 receipt 的 verify 直接失败。

    strict 模式：无 receipt → success=False（硬阻塞）。
    """
    from cognitive_loop_entry import CognitiveLoopEntry
    cle = CognitiveLoopEntry(
        storage_path=str(tmp_path / "test.db"),
        poe_enforcement="strict",
    )
    try:
        fake_id = "VM-9999999999-strict-test"
        result = cle.verify(fake_id, success=True)
        # strict 模式：无 receipt → success=False
        assert result["success"] is False
        assert result["poe_trust"] is False
        assert "poe_blocked" in result
        assert result["poe_blocked"] is True
    finally:
        cle.close()


def test_poe_enforcement_default_soft(tmp_path):
    """RED: 默认 poe_enforcement='soft'（FAIL-OPEN + 限制上限）。"""
    from cognitive_loop_entry import CognitiveLoopEntry
    cle = CognitiveLoopEntry(storage_path=str(tmp_path / "test.db"))
    try:
        # 默认应为 soft
        assert cle.poe_enforcement == "soft"
        fake_id = "VM-9999999999-soft-default"
        result = cle.verify(fake_id, success=True)
        # soft: success=True（FAIL-OPEN），但有质量上限
        assert result["success"] is True
        assert result["poe_trust"] is False
        assert result["poe_quality_cap"] == "B"
    finally:
        cle.close()
