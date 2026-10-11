"""P0 PoE 性能优化 TDD RED 测试

SPEC: 35-广义认知系统协作模块/SPEC-Unified-PoE-Framework.md §3.2 + §3.4 + §2.3

P0 任务（落地优先级最高，性能瓶颈修复）：
  P0-1: _check_poe_trust() 改索引查询（移除每次全量 verify_integrity）
  P0-2: evidence_ledger 新增 verify_receipt_exists(entry_id) O(1) 查询
  P0-5: SQLite WAL 模式 + 计数器落库（并发安全前置）
  P0-6: 启动时跑一次全量验证（健康检查）

设计依据（SPEC v2.0 §3.2）：
  - 不再每次跑全量完整性验证，改为：
    * 启动时跑一次全量验证（健康检查）
    * 日常只验 receipt 是否在 Index 中（O(1) 查询）
  - SQLite 开启 WAL 模式（PRAGMA journal_mode=WAL），支持多进程并发读写
  - 计数器落库（新增 counter 表 + atomic UPDATE），跨进程共享
  - 不用文件 flock（引入新故障面）

RED 契约（当前全部失败）：
  1. EvidenceLedger.verify_receipt_exists(entry_id) 方法存在 + 返回正确 bool
  2. SQLite journal_mode == 'wal'
  3. ledger_counters 表存在
  4. _check_poe_trust 调用时不触发 verify_integrity（mock 验证 call_count=0）
  5. __init__ 末尾跑一次 verify_integrity（mock 验证 call_count>=1）
  6. 启动健康检查结果记录在 self._startup_integrity_passed
  7. 篡改 Ledger 后再初始化，_startup_integrity_passed=False（FAIL-OPEN 不抛异常）
  8. 计数器原子更新：increment_counter(name) 返回新值
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

import pytest

_SCRIPT_DIR = Path(__file__).parent
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))


# ─────────────────────────────── P0-2: verify_receipt_exists ───────────────────────────────

def test_evidence_ledger_has_verify_receipt_exists(tmp_path):
    """RED: EvidenceLedger 应有 verify_receipt_exists(entry_id) 方法。"""
    from evidence_ledger import EvidenceLedger
    ledger = EvidenceLedger(db_path=tmp_path / "test_p0.db")
    assert hasattr(ledger, "verify_receipt_exists"), \
        "EvidenceLedger 应提供 verify_receipt_exists(entry_id) O(1) 查询"


def test_verify_receipt_exists_returns_true_for_existing(tmp_path):
    """RED: 已存在的 entry_id → True。"""
    from evidence_ledger import EvidenceLedger, EvidenceEntry
    ledger = EvidenceLedger(db_path=tmp_path / "test_p0.db")
    entry = EvidenceEntry(
        subject="s", relation="r", object="o",
        source="src", confidence=0.8, level="observation",
    )
    ledger.append(entry)
    assert ledger.verify_receipt_exists(entry.entry_id) is True


def test_verify_receipt_exists_returns_false_for_nonexistent(tmp_path):
    """RED: 不存在的 entry_id → False。"""
    from evidence_ledger import EvidenceLedger
    ledger = EvidenceLedger(db_path=tmp_path / "test_p0.db")
    assert ledger.verify_receipt_exists("el_nonexistent_12345") is False


def test_verify_receipt_exists_empty_db_returns_false(tmp_path):
    """RED: 空数据库 → False（FAIL-OPEN 不抛异常）。"""
    from evidence_ledger import EvidenceLedger
    ledger = EvidenceLedger(db_path=tmp_path / "test_p0.db")
    assert ledger.verify_receipt_exists("any_id") is False


# ─────────────────────────────── P0-5: SQLite WAL + 计数器表 ───────────────────────────────

def test_wal_mode_enabled(tmp_path):
    """RED: SQLite journal_mode 应为 'wal'。"""
    from evidence_ledger import EvidenceLedger
    ledger = EvidenceLedger(db_path=tmp_path / "test_p0.db")
    assert ledger._conn is not None, "FAIL-OPEN 失败导致 _conn=None"
    mode = ledger._conn.execute("PRAGMA journal_mode").fetchone()[0]
    assert mode.lower() == "wal", f"journal_mode 应为 wal，实际为 {mode}"


def test_counter_table_exists(tmp_path):
    """RED: 应有 ledger_counters 表（跨进程共享计数器）。"""
    from evidence_ledger import EvidenceLedger
    ledger = EvidenceLedger(db_path=tmp_path / "test_p0.db")
    cursor = ledger._conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='ledger_counters'"
    )
    assert cursor.fetchone() is not None, "ledger_counters 表不存在"


def test_increment_counter_atomic(tmp_path):
    """RED: increment_counter(name) 原子自增并返回新值。"""
    from evidence_ledger import EvidenceLedger
    ledger = EvidenceLedger(db_path=tmp_path / "test_p0.db")
    # 首次自增：1
    v1 = ledger.increment_counter("integrity_check_count")
    assert v1 == 1
    # 第二次：2
    v2 = ledger.increment_counter("integrity_check_count")
    assert v2 == 2


def test_get_counter_returns_persisted_value(tmp_path):
    """RED: get_counter 跨实例读取持久化值。"""
    from evidence_ledger import EvidenceLedger
    db_path = tmp_path / "test_p0.db"
    ledger1 = EvidenceLedger(db_path=db_path)
    ledger1.increment_counter("ops_count")
    ledger1.increment_counter("ops_count")
    ledger1.close()
    # 新实例读同一 DB
    ledger2 = EvidenceLedger(db_path=db_path)
    assert ledger2.get_counter("ops_count") == 2


# ─────────────────────────────── P0-1: _check_poe_trust 不跑全量 ───────────────────────────────

def test_check_poe_trust_does_not_call_verify_integrity(tmp_path):
    """RED: _check_poe_trust 日常调用不应触发 verify_integrity（O(N) 全量）。

    SPEC §3.2：日常只验 receipt 存在性，全量验证由启动健康检查承担。
    """
    from cognitive_loop_entry import CognitiveLoopEntry
    cle = CognitiveLoopEntry(storage_path=str(tmp_path / "test_p0.db"))
    try:
        memory_id = cle.record(
            content="P0 简化测试",
            quality_level="C",
            source="test_p0",
        )
        with patch.object(cle.evidence_ledger, "verify_integrity", return_value=True) as mock_vi:
            trust, receipt = cle._check_poe_trust(memory_id)
            assert trust is True
            assert receipt
            # 关键断言：verify_integrity 未被调用
            assert mock_vi.call_count == 0, \
                "_check_poe_trust 日常路径不应跑 verify_integrity (O(N))"
    finally:
        cle.close()


def test_check_poe_trust_with_receipt_trusts_even_if_integrity_fails(tmp_path):
    """RED: 有 receipt 时，即使 verify_integrity 返回 False 仍信任 receipt。

    这是 P0 简化的核心设计权衡：日常不检测篡改，篡改检测由启动健康检查承担。
    """
    from cognitive_loop_entry import CognitiveLoopEntry
    cle = CognitiveLoopEntry(storage_path=str(tmp_path / "test_p0.db"))
    try:
        memory_id = cle.record(
            content="P0 信任 receipt 测试",
            quality_level="C",
            source="test_p0",
        )
        # mock verify_integrity 返回 False（模拟篡改）
        with patch.object(cle.evidence_ledger, "verify_integrity", return_value=False):
            trust, receipt = cle._check_poe_trust(memory_id)
            # 日常路径不跑 verify_integrity，所以即使它返回 False 也信任 receipt
            assert trust is True, "有 receipt 时日常路径应信任（不跑全量）"
            assert receipt
    finally:
        cle.close()


# ─────────────────────────────── P0-6: 启动健康检查 ───────────────────────────────

def test_startup_health_check_runs_verify_integrity(tmp_path):
    """RED: __init__ 末尾应跑一次 verify_integrity（健康检查）。"""
    from cognitive_loop_entry import CognitiveLoopEntry
    from evidence_ledger import EvidenceLedger
    with patch.object(EvidenceLedger, "verify_integrity", return_value=True) as mock_vi:
        cle = CognitiveLoopEntry(storage_path=str(tmp_path / "test_p0.db"))
        try:
            assert mock_vi.call_count >= 1, "__init__ 应在末尾跑一次 verify_integrity"
            assert cle._startup_integrity_passed is True, \
                "启动健康检查通过应记录在 _startup_integrity_passed=True"
        finally:
            cle.close()


def test_startup_health_check_detects_tamper(tmp_path):
    """RED: 篡改 Ledger 后再初始化，启动健康检查应检测到并记录 False。

    FAIL-OPEN：不抛异常，仅标记 _startup_integrity_passed=False。
    """
    from cognitive_loop_entry import CognitiveLoopEntry
    from evidence_ledger import EvidenceLedger, EvidenceEntry

    storage_path = tmp_path / "test_p0.db"
    ledger_path = Path(storage_path).parent / "evidence_ledger.db"

    # 第一阶段：初始化 + 写入 + 篡改
    ledger = EvidenceLedger(db_path=ledger_path)
    ledger.append(EvidenceEntry(
        subject="s", relation="r", object="o",
        source="src", confidence=0.8, level="observation",
    ))
    ledger._tamper_for_test(0, subject="HACKED")
    ledger.close()

    # 第二阶段：新实例加载篡改后的 DB
    cle = CognitiveLoopEntry(storage_path=str(storage_path))
    try:
        # 启动健康检查应检测到篡改
        assert cle._startup_integrity_passed is False, \
            "篡改后启动健康检查应标记 _startup_integrity_passed=False"
    finally:
        cle.close()


def test_startup_health_check_does_not_block_on_failure(tmp_path):
    """RED: 启动健康检查失败不阻塞 CognitiveLoopEntry 初始化（FAIL-OPEN）。"""
    from cognitive_loop_entry import CognitiveLoopEntry
    from evidence_ledger import EvidenceLedger, EvidenceEntry

    storage_path = tmp_path / "test_p0.db"
    ledger_path = Path(storage_path).parent / "evidence_ledger.db"

    # 篡改 DB
    ledger = EvidenceLedger(db_path=ledger_path)
    ledger.append(EvidenceEntry(
        subject="s", relation="r", object="o",
        source="src", confidence=0.8, level="observation",
    ))
    ledger._tamper_for_test(0, subject="HACKED")
    ledger.close()

    # 初始化不应抛异常
    cle = CognitiveLoopEntry(storage_path=str(storage_path))
    try:
        # 仍可正常使用
        assert cle._startup_integrity_passed is False
        # 但 record/verify 仍可调用（FAIL-OPEN）
        result = cle.record(content="FAIL-OPEN 测试", quality_level="C", source="test")
        assert result  # record 仍返回 memory_id
    finally:
        cle.close()
