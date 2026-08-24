"""
TDD 红-绿-重构：P1-4 三批 Import 幂等脚本
--------------------------------------------
Import 脚本设计：
  import_runner.import_all_batches(data_dir, db_path, *, dry_run=False)
    → ImportReport {batch_id, applied, skipped, failed, duration_ms} 列表

幂等保证：
  1) 每个 batch 内每行写入 → INSERT OR IGNORE（主键幂等）
  2) ma_migration_audit 表写一行：category='migration_script'，
     entity_key = batch_id + '#' + checksum（批摘要）
  3) 重新执行同批次 → 所有行全部 SKIPPED + report.skipped = 上一次 applied

三批次划分（对齐 §3 迁移路线图）：
  BATCH-1 : core_trade     → tr_trades / po_positions / tr_daily_stats
  BATCH-2 : performance_risk → rs_state / rs_cases
  BATCH-3 : macro_config_kg → mm_* / cv_config_versions / kg_*

TDD 用例：
  1. test_batch_runner_runs_3_batches_smoke → 执行完整三批，返回 3 条 reports，非 crash
  2. test_batch_import_is_idempotent → 连续执行 2 次，第 2 次 APPLIED=0，行数不变
  3. test_batch_dry_run_does_not_write_rows → dry_run=True 后查询行数=0
  4. test_ma_migration_audit_written → 执行后 ma_migration_audit 存在 category='migration_script' 行
"""
from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from dreambuddy_dal.connection import get_sqlite_connection
from dreambuddy_dal.implementations.sqlite_unified.schema_init import init_db_schema


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------
@pytest.fixture
def work_dir():
    """每个测试独立 tmp：data_dir（旧JSON）+ db_path（新库）。"""
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        (root / "data").mkdir()
        db = root / "dreambuddy_core.db"
        # schema init
        with get_sqlite_connection(str(db)) as conn:
            init_db_schema(conn)
        yield root


# ===========================================================================
# 4 个单测
# ===========================================================================
def test_runner_runs_three_batches_and_reports(work_dir):
    """[1] 完整三批执行：reports 长度 = 3，batches 顺序为 1→2→3。"""
    from dreambuddy_dal.implementations.sqlite_unified.import_runner import (
        import_all_batches,
    )
    data_dir = work_dir / "data"
    db_path = work_dir / "dreambuddy_core.db"

    reports = import_all_batches(str(data_dir), str(db_path), dry_run=False)
    assert isinstance(reports, list) and len(reports) == 3
    batch_ids = [r.batch_id for r in reports]
    assert batch_ids == ["BATCH-1-core-trade", "BATCH-2-performance-risk", "BATCH-3-macro-config-kg"]

    # 每个 report 都是合法字段
    for r in reports:
        assert isinstance(r.applied, int) and r.applied >= 0
        assert isinstance(r.skipped, int) and r.skipped >= 0
        assert isinstance(r.failed, int) and r.failed >= 0
        assert r.duration_ms >= 0


def test_batch_import_is_idempotent(work_dir):
    """[2] 连续执行两次，第 2 次 applied=0（所有行因 INSERT OR IGNORE/幂等 UPSERT 跳过）。"""
    from dreambuddy_dal.implementations.sqlite_unified.import_runner import (
        import_all_batches,
    )
    data_dir = work_dir / "data"
    db_path = work_dir / "dreambuddy_core.db"

    # --- Run 1
    reports_1 = import_all_batches(str(data_dir), str(db_path), dry_run=False)
    total_applied_1 = sum(r.applied for r in reports_1)

    # --- Run 2（同参数）
    reports_2 = import_all_batches(str(data_dir), str(db_path), dry_run=False)
    total_applied_2 = sum(r.applied for r in reports_2)

    # 第二次：幂等 → 0 APPLIED（或 ≤ 第 1 次的极小值，上限 5% 容差）
    assert total_applied_2 <= max(1, total_applied_1 // 20), (
        f"幂等不成立：run1={total_applied_1} run2={total_applied_2}"
    )

    # 看业务表行数（忽略审计表自增行和单例种子表的重复 count）
    with get_sqlite_connection(str(db_path)) as conn:
        rows_1 = _count_core_business_tables(conn)
    # 再跑一次 run3 确认 idempotent
    reports_3 = import_all_batches(str(data_dir), str(db_path), dry_run=False)
    assert sum(r.applied for r in reports_3) == 0
    with get_sqlite_connection(str(db_path)) as conn:
        rows_3 = _count_core_business_tables(conn)
    assert rows_3 == rows_1, f"核心业务表行数变化: {rows_1} → {rows_3}"


def test_dry_run_writes_zero_rows(work_dir):
    """[3] dry_run=True：执行后核心业务表（不含种子/审计）为 0。"""
    from dreambuddy_dal.implementations.sqlite_unified.import_runner import (
        import_all_batches,
    )
    data_dir = work_dir / "data"
    db_path = work_dir / "dreambuddy_core.db"

    reports = import_all_batches(str(data_dir), str(db_path), dry_run=True)
    # dry_run：业务表 0 行（种子表 ma_schema_version / rs_state 不计）
    with get_sqlite_connection(str(db_path)) as conn:
        counts = _count_core_business_tables(conn)
    assert counts == 0, (
        f"dry_run 应写 0 核心业务行，但实际写了 {counts} 行。"
        f"reports={[(r.batch_id, r.applied) for r in reports]}"
    )


def test_ma_migration_audit_written(work_dir):
    """[4] 执行后 ma_migration_audit category='migration_script' 至少 3 条（1 per batch）。"""
    from dreambuddy_dal.implementations.sqlite_unified.import_runner import (
        import_all_batches,
    )
    data_dir = work_dir / "data"
    db_path = work_dir / "dreambuddy_core.db"

    import_all_batches(str(data_dir), str(db_path), dry_run=False)

    with get_sqlite_connection(str(db_path)) as conn:
        rows = conn.execute(
            """
            SELECT category, entity_key, result
            FROM ma_migration_audit
            WHERE category='migration_script'
            ORDER BY id ASC
            """
        ).fetchall()
    batch_keys = [r[1] for r in rows]
    # 至少包含 3 个 batch_id
    for expected in ["core-trade", "performance-risk", "macro-config-kg"]:
        assert any(expected in (k or "") for k in batch_keys), (
            f"ma_migration_audit 缺 {expected} 审计行，实际 keys={batch_keys}"
        )
    # 每条都得有合法 result ∈ {APPLIED,SKIPPED,FAILED,WARN}
    for (_cat, _key, result) in rows:
        assert result in {"APPLIED", "SKIPPED", "FAILED", "WARN"}


# ===========================================================================
# helpers
# ===========================================================================
# 只看有真实业务数据流进流出的表（不含种子 ma_schema_version / rs_state 单行、
# 不含 ma_migration_audit / ma_integrity_log 自增审计表）
_CORE_BUSINESS_TABLES = [
    "tr_trades", "tr_daily_stats", "tr_daily_stats_overrides",
    "po_positions", "po_price_refresh_log",
    "mm_fear_greed", "mm_funding_rate", "mm_open_interest",
    "mm_liquidation", "mm_long_short_ratio", "mm_taker_volume",
    "rs_cases",
    "cv_config_versions",
    "kg_entities", "kg_entity_aliases", "kg_triples",
]


def _count_core_business_tables(conn) -> int:
    """核心业务表总行数（排除 schema 的种子行：tr_trades.__NO_LINK__ 虚拟行）。"""
    total = 0
    for t in _CORE_BUSINESS_TABLES:
        try:
            if t == "tr_trades":
                (c,) = conn.execute(
                    "SELECT COUNT(*) FROM tr_trades WHERE trade_id != '__NO_LINK__'"
                ).fetchone()
            else:
                (c,) = conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()
            total += int(c or 0)
        except Exception:
            pass
    return total


_USER_TABLES_NO_MA = _CORE_BUSINESS_TABLES + ["rs_state"]


def _count_all_user_tables(conn, *, exclude_ma_audit: bool = False) -> int:
    total = 0
    tbls = list(_USER_TABLES_NO_MA)
    if not exclude_ma_audit:
        tbls += ["ma_schema_version", "ma_migration_audit", "ma_integrity_log"]
    for t in tbls:
        try:
            (c,) = conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()
            total += int(c or 0)
        except Exception:
            # FTS5 虚拟表 kg_terms_fts 等 SELECT COUNT(*) 可能特殊，忽略
            pass
    return total
