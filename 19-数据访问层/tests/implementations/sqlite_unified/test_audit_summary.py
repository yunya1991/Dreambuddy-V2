"""
TDD：P2-1 audit_summary.py（G-1 双写差异率 + G-3 影子读一致率）
================================================================
audit_summary 是 P2 门禁的测量引擎，独立于 import_runner（防止既当裁判又当运动员）。

入口：
  from dreambuddy_dal.implementations.sqlite_unified.audit_summary import (
      compute_audit_summary, AuditSummary,
  )
  summary = compute_audit_summary(db_path, window_hours=72)
  → AuditSummary(write_total, write_fail, write_diff_rate,
                 shadow_read_total, shadow_read_match, shadow_read_diff,
                 read_consistency_rate, window_hours, computed_at)

G-1 通过标准：write_diff_rate < 0.001（即 < 0.1%）
G-3 通过标准：read_consistency_rate >= 0.9999（即 ≥ 99.99%）

数据来源：ma_migration_audit 表
  - category='dual_write'   → 写审计（result=APPLIED/SKIPPED/FAILED）
  - category='shadow_read'  → 读审计（result=MATCH/DIFF）
"""
from __future__ import annotations

import json
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


def _insert_audit(conn, *, category, entity_key, result, severity=0, latency_ms=10):
    conn.execute(
        """
        INSERT INTO ma_migration_audit
            (category, event_name, entity_key, result, severity, details, latency_ms)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (category, "test", entity_key, result, severity, "{}", latency_ms),
    )


def _insert_audit_with_time(conn, *, category, entity_key, result, run_at, severity=0):
    conn.execute(
        """
        INSERT INTO ma_migration_audit
            (category, event_name, entity_key, result, severity, details, latency_ms, run_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (category, "test", entity_key, result, severity, "{}", 10, run_at),
    )


# ===========================================================================
# 1. 空 DB → 0 写 0 读 → diff_rate=0, consistency=1.0（不炸除零）
# ===========================================================================
def test_empty_db_returns_safe_defaults(db_path):
    from dreambuddy_dal.implementations.sqlite_unified.audit_summary import (
        compute_audit_summary,
    )
    s = compute_audit_summary(db_path, window_hours=72)
    assert s.write_total == 0
    assert s.write_fail == 0
    assert s.write_diff_rate == 0.0  # 无写入时 diff_rate=0（不除零）
    assert s.shadow_read_total == 0
    assert s.shadow_read_match == 0
    assert s.shadow_read_diff == 0
    assert s.read_consistency_rate == 1.0  # 无读时 consistency=100%（不除零）


# ===========================================================================
# 2. G-1：100 写 → 0 fail → diff_rate=0.0（PASS）
# ===========================================================================
def test_g1_zero_write_fail_passes(db_path):
    from dreambuddy_dal.implementations.sqlite_unified.audit_summary import (
        compute_audit_summary,
    )
    with get_sqlite_connection(db_path) as conn:
        for i in range(100):
            _insert_audit(conn, category="dual_write",
                          entity_key=f"trade_{i}", result="APPLIED")
    s = compute_audit_summary(db_path, window_hours=72)
    assert s.write_total == 100
    assert s.write_fail == 0
    assert s.write_diff_rate == 0.0


# ===========================================================================
# 3. G-1：100 写 → 1 fail → diff_rate=0.01（BORDERLINE；门限 0.001）
# ===========================================================================
def test_g1_one_fail_out_of_hundred(db_path):
    from dreambuddy_dal.implementations.sqlite_unified.audit_summary import (
        compute_audit_summary,
    )
    with get_sqlite_connection(db_path) as conn:
        for i in range(99):
            _insert_audit(conn, category="dual_write",
                          entity_key=f"trade_{i}", result="APPLIED")
        _insert_audit(conn, category="dual_write",
                      entity_key="trade_bad", result="FAILED", severity=2)
    s = compute_audit_summary(db_path, window_hours=72)
    assert s.write_total == 100
    assert s.write_fail == 1
    assert abs(s.write_diff_rate - 0.01) < 1e-9  # 1/100 = 0.01


# ===========================================================================
# 4. G-3：100 影子读 → 100 MATCH → consistency=1.0（PASS）
# ===========================================================================
def test_g3_all_match_passes(db_path):
    from dreambuddy_dal.implementations.sqlite_unified.audit_summary import (
        compute_audit_summary,
    )
    with get_sqlite_connection(db_path) as conn:
        for i in range(100):
            _insert_audit(conn, category="shadow_read",
                          entity_key=f"read_{i}", result="MATCH")
    s = compute_audit_summary(db_path, window_hours=72)
    assert s.shadow_read_total == 100
    assert s.shadow_read_match == 100
    assert s.shadow_read_diff == 0
    assert s.read_consistency_rate == 1.0


# ===========================================================================
# 5. G-3：100 影子读 → 99 MATCH + 1 DIFF → consistency=0.99（FAIL，< 0.9999）
# ===========================================================================
def test_g3_one_diff_fails_gate(db_path):
    from dreambuddy_dal.implementations.sqlite_unified.audit_summary import (
        compute_audit_summary,
    )
    with get_sqlite_connection(db_path) as conn:
        for i in range(99):
            _insert_audit(conn, category="shadow_read",
                          entity_key=f"read_{i}", result="MATCH")
        _insert_audit(conn, category="shadow_read",
                      entity_key="read_bad", result="DIFF", severity=1)
    s = compute_audit_summary(db_path, window_hours=72)
    assert s.shadow_read_total == 100
    assert s.shadow_read_match == 99
    assert s.shadow_read_diff == 1
    assert abs(s.read_consistency_rate - 0.99) < 1e-9


# ===========================================================================
# 6. window 过滤：只计 72h 内的审计行
# ===========================================================================
def test_window_filter_excludes_old_rows(db_path):
    from dreambuddy_dal.implementations.sqlite_unified.audit_summary import (
        compute_audit_summary,
    )
    with get_sqlite_connection(db_path) as conn:
        _insert_audit_with_time(
            conn, category="dual_write", entity_key="old_fail",
            result="FAILED", run_at="2020-01-01T00:00:00+00:00", severity=2,
        )
        _insert_audit(conn, category="dual_write",
                      entity_key="recent_ok", result="APPLIED")
    s = compute_audit_summary(db_path, window_hours=72)
    assert s.write_total == 1
    assert s.write_fail == 0
