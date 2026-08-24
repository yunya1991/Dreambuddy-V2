"""
TDD：P2-3 gate_check.py（G-1~G-5 五项门禁一键检查）
=====================================================
gate_check 是 P2 切读前的最终门禁。G-1~G-5 任意一项不通过 = 不允许切读。

入口：
  from dreambuddy_dal.implementations.sqlite_unified.gate_check import (
      run_gate_check, GateCheckResult,
  )
  result = run_gate_check(db_path, log_dir=None, window_hours=72)
  → GateCheckResult(g1_pass, g2_pass, g3_pass, g4_pass, g5_pass, all_pass, details)
  result.all_pass == True → 可以切读
  result.all_pass == False → 延长观察期

5 项门禁（对齐 MIGRATION_PLAN §3.1）：
  G-1: 双写差异率 < 0.001（≤1 笔 / 10 万）
  G-2: "database is locked" 0 次（扫描日志目录）
  G-3: 影子读一致率 ≥ 99.99%
  G-4: 回滚演练 30 分钟零事故（现场操作，需手动传入 pass/fail）
  G-5: 冷备份可用性（PRAGMA integrity_check + 抽样 10 条）
"""
from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from dreambuddy_dal.connection import get_sqlite_connection
from dreambuddy_dal.implementations.sqlite_unified.schema_init import init_db_schema


@pytest.fixture
def db_path():
    with tempfile.TemporaryDirectory() as td:
        db = Path(td) / "dreambuddy_core.db"
        with get_sqlite_connection(str(db)) as conn:
            init_db_schema(conn)
        yield str(db)


# ===========================================================================
# 1. 全部 PASS → all_pass=True
# ===========================================================================
def test_all_pass(db_path):
    from dreambuddy_dal.implementations.sqlite_unified.gate_check import (
        run_gate_check,
    )
    # 写 100 条 APPLIED（G-1 0 fail）+ 100 条 MATCH（G-3 100%）
    with get_sqlite_connection(db_path) as conn:
        for i in range(100):
            conn.execute(
                "INSERT INTO ma_migration_audit(category,event_name,entity_key,result,severity,details,latency_ms)"
                " VALUES(?,?,?,?,?,?,?)",
                ("dual_write", "test", f"w{i}", "APPLIED", 0, "{}", 10),
            )
            conn.execute(
                "INSERT INTO ma_migration_audit(category,event_name,entity_key,result,severity,details,latency_ms)"
                " VALUES(?,?,?,?,?,?,?)",
                ("shadow_read", "test", f"r{i}", "MATCH", 0, "{}", 10),
            )
    result = run_gate_check(
        db_path,
        log_dir=None,  # 无日志目录 → G-2 跳过（默认 PASS）
        rollback_drill_pass=True,  # G-4 手动传入
        backup_db_path=None,  # 无冷备份 → G-5 跳过
    )
    assert result.g1_pass is True
    assert result.g2_pass is True  # 无日志 = PASS
    assert result.g3_pass is True
    assert result.g4_pass is True
    assert result.g5_pass is True  # 无备份 = PASS（P3 才做冷备）
    assert result.all_pass is True


# ===========================================================================
# 2. G-1 FAIL（1 fail / 10 total = 0.1%）→ all_pass=False
# ===========================================================================
def test_g1_fail_blocks_all(db_path):
    from dreambuddy_dal.implementations.sqlite_unified.gate_check import (
        run_gate_check,
    )
    with get_sqlite_connection(db_path) as conn:
        for i in range(9):
            conn.execute(
                "INSERT INTO ma_migration_audit(category,event_name,entity_key,result,severity,details,latency_ms)"
                " VALUES(?,?,?,?,?,?,?)",
                ("dual_write", "test", f"w{i}", "APPLIED", 0, "{}", 10),
            )
        conn.execute(
            "INSERT INTO ma_migration_audit(category,event_name,entity_key,result,severity,details,latency_ms)"
            " VALUES(?,?,?,?,?,?,?)",
            ("dual_write", "test", "w_bad", "FAILED", 2, "{}", 10),
        )
    result = run_gate_check(db_path, rollback_drill_pass=True)
    assert result.g1_pass is False
    assert result.all_pass is False


# ===========================================================================
# 3. G-2 FAIL（日志含 "database is locked"）→ all_pass=False
# ===========================================================================
def test_g2_detects_db_locked(db_path, tmp_path):
    from dreambuddy_dal.implementations.sqlite_unified.gate_check import (
        run_gate_check,
    )
    log_dir = tmp_path / "logs"
    log_dir.mkdir()
    (log_dir / "trader_001.log").write_text(
        "2026-08-24 ERROR: database is locked\n"
        "2026-08-24 INFO: retry succeeded\n"
    )
    result = run_gate_check(db_path, log_dir=str(log_dir), rollback_drill_pass=True)
    assert result.g2_pass is False
    assert result.all_pass is False


# ===========================================================================
# 4. G-2 PASS（日志无 "database is locked"）
# ===========================================================================
def test_g2_pass_no_locked_errors(db_path, tmp_path):
    from dreambuddy_dal.implementations.sqlite_unified.gate_check import (
        run_gate_check,
    )
    log_dir = tmp_path / "logs"
    log_dir.mkdir()
    (log_dir / "trader_001.log").write_text("2026-08-24 INFO: all good\n")
    (log_dir / "dal_001.jsonl").write_text('{"level":"INFO","msg":"ok"}\n')
    result = run_gate_check(db_path, log_dir=str(log_dir), rollback_drill_pass=True)
    assert result.g2_pass is True


# ===========================================================================
# 5. G-4 FAIL（回滚演练未通过）→ all_pass=False
# ===========================================================================
def test_g4_rollback_drill_fail(db_path):
    from dreambuddy_dal.implementations.sqlite_unified.gate_check import (
        run_gate_check,
    )
    result = run_gate_check(db_path, rollback_drill_pass=False)
    assert result.g4_pass is False
    assert result.all_pass is False


# ===========================================================================
# 6. G-5 PASS（integrity_check=ok + 抽样 10 条匹配）
# ===========================================================================
def test_g5_integrity_ok(db_path):
    from dreambuddy_dal.implementations.sqlite_unified.gate_check import (
        run_gate_check,
    )
    # 用自身 DB 做冷备（测试简化）
    result = run_gate_check(
        db_path, rollback_drill_pass=True, backup_db_path=db_path,
    )
    assert result.g5_pass is True
