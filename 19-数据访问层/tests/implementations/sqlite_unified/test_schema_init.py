"""
TDD RED: schema_init.py — 21 表 Schema + 幂等 + _add_column_if_missing

对齐 SCHEMA_DESIGN.md §2 + §9.1 + §10
- ADR-19-005: CREATE TABLE = 最终目标 Schema
- Experience 1040063: _add_column_if_missing 4 入口契约
"""
import sqlite3
from pathlib import Path

import pytest

from dreambuddy_dal.connection import get_sqlite_connection

# --- T1: 21 张表 + 前缀分区正确（ADR-19-003） ---
# 对齐 SCHEMA_DESIGN.md §2.1~§8.4：实际 21 张（kg_* 4 张含 FTS5 虚拟表 kg_terms_fts）
EXPECTED_21_TABLES = {
    # ma_* 元数据 3 张
    "ma_schema_version", "ma_migration_audit", "ma_integrity_log",
    # tr_* 交易 3 张
    "tr_trades", "tr_daily_stats", "tr_daily_stats_overrides",
    # po_* 持仓 2 张
    "po_positions", "po_price_refresh_log",
    # mm_* 宏观 6 张
    "mm_fear_greed", "mm_funding_rate", "mm_open_interest",
    "mm_liquidation", "mm_long_short_ratio", "mm_taker_volume",
    # rs_* 风控 2 张
    "rs_state", "rs_cases",
    # cv_* 配置 1 张
    "cv_config_versions",
    # kg_* 知识图谱 4 张（§8.4 kg_terms_fts = FTS5 虚拟表）
    "kg_entities", "kg_entity_aliases", "kg_triples", "kg_terms_fts",
}
assert len(EXPECTED_21_TABLES) == 21, f"设计应为 21 表，当前 {len(EXPECTED_21_TABLES)}"


# --- T2: 5 核心表关键列类型校验（抽样核心列，覆盖 PK/类型约束） ---
# ⚠️ 注意：列名完全对齐 ADR-19-004 + schema_init.py 最终列清单（SCHEMA_DESIGN §2 中 entry_time → 统一改为 entry_ts 命名）
EXPECTED_COLUMNS = {
    "tr_trades": [
        ("trade_id", "TEXT", 1),       # PK=1
        ("symbol", "TEXT", 0),
        ("direction", "TEXT", 0),      # enum value
        ("entry_price", "TEXT", 0),    # Decimal→TEXT（ADR-19-004）
        ("quantity", "TEXT", 0),       # Decimal→TEXT
        ("entry_ts", "TEXT", 0),       # ISO8601（统一命名 entry_ts，与 unified_models 一致）
        ("exit_ts", "TEXT", 0),        # NULL = 持仓中
        ("status", "TEXT", 0),
        ("exit_reason", "TEXT", 0),
        ("realized_pnl", "TEXT", 0),   # Decimal→TEXT
        ("strategy_source", "TEXT", 0),
        ("sub_system", "TEXT", 0),
        ("war_state", "TEXT", 0),
        ("is_trial", "INTEGER", 0),    # BOOL (0/1)
        ("trial_status", "TEXT", 0),
        ("trial_eval_result", "TEXT", 0),
        ("risk_level_cn", "TEXT", 0),
    ],
    "po_positions": [
        ("inst_id", "TEXT", 1),        # PK
        ("trade_id", "TEXT", 0),       # FK→tr_trades
        ("symbol", "TEXT", 0),
        ("direction", "TEXT", 0),
        ("entry_price", "TEXT", 0),    # Decimal→TEXT（对齐 entry_price 命名，不用 avg_ 前缀）
        ("quantity", "TEXT", 0),       # Decimal→TEXT
        ("mark_price", "TEXT", 0),
        ("opened_at", "TEXT", 0),
        ("unrealized_pnl", "TEXT", 0), # Decimal→TEXT
        ("is_trial", "INTEGER", 0),
        ("sub_system", "TEXT", 0),
        ("version", "INTEGER", 0),     # 乐观锁
    ],
    "rs_state": [
        ("id", "INTEGER", 1),          # CHECK id=1
        ("total_risk_exposure", "TEXT", 0),
        ("open_positions_count", "INTEGER", 0),
        ("daily_realized_pnl", "TEXT", 0),
        ("daily_pnl", "REAL", 0),      # REAL 允许（日内聚合）
        ("circuit_breaker_active", "INTEGER", 0),
        ("kill_switch_active", "INTEGER", 0),
        ("version", "INTEGER", 0),
    ],
    "cv_config_versions": [
        ("version", "TEXT", 1),        # PK SemVer 字符串
        ("config_family", "TEXT", 0),
        ("is_active", "INTEGER", 0),   # BOOLEAN：全局唯一 1 由触发器保证
        ("released_at", "TEXT", 0),
        ("payload_json", "TEXT", 0),   # 替代 SCHEMA_DESIGN 旧名 payload → payload_json
        ("created_by", "TEXT", 0),
        ("notes", "TEXT", 0),
        ("archived", "INTEGER", 0),
    ],
    "kg_triples": [
        ("id", "INTEGER", 1),          # AUTOINCREMENT PK
        ("subject", "TEXT", 0),
        ("predicate", "TEXT", 0),
        ("object", "TEXT", 0),
        ("confidence", "REAL", 0),     # 0~1 置信度 REAL 业界允许
        ("valid_from", "TEXT", 0),
        ("valid_to", "TEXT", 0),
    ],
}


# --- T3: 2 个关键业务触发器（不变量触发器，不可缺） ---
EXPECTED_TRIGGERS = {
    "trg_rs_state_update",      # rs_state UPDATE 自动 version+1 + WHERE id=1 单例
    "trg_cv_version_uniq_active",  # cv_config_versions 唯一 is_active=1（取消旧激活）
}


# --- T4: 10 个核心索引（覆盖 §9.1 主要高频查询） ---
EXPECTED_INDEXES = {
    "idx_tr_trades_symbol_entry_time",
    "idx_tr_trades_open",
    "idx_tr_trades_daily",
    "idx_po_positions_symbol",
    "idx_po_refresh_time",
    "idx_mm_funding_time",
    "idx_rs_cases_severity",
    "idx_cv_versions_released",
    "idx_kg_triples_spo",
    "idx_kg_aliases_alias",
}


@pytest.fixture
def fresh_sqlite(tmp_path: Path) -> Path:
    """每次测试全新 DB，避免测试间相互污染。"""
    db = tmp_path / "test_schema.db"
    assert not db.exists()
    return db


def _get_tables(conn: sqlite3.Connection) -> set[str]:
    rows = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
    ).fetchall()
    tables = {r[0] for r in rows}
    # 过滤 FTS5 虚拟表自动生成的 4 shadow 表（_config / _data / _docsize / _idx）
    # 这些是 FTS 内部表，业务 Schema 不把它们当作独立表
    fts_shadow_suffixes = ("_config", "_data", "_docsize", "_idx")
    return {
        t for t in tables
        if not any(t.endswith(s) for s in fts_shadow_suffixes)
    }


def _get_indexes(conn: sqlite3.Connection) -> set[str]:
    rows = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='index' AND name NOT LIKE 'sqlite_%'"
    ).fetchall()
    return {r[0] for r in rows}


def _get_triggers(conn: sqlite3.Connection) -> set[str]:
    rows = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='trigger'"
    ).fetchall()
    return {r[0] for r in rows}


def _get_column_info(conn: sqlite3.Connection, table: str) -> dict[str, tuple[str, int]]:
    """PRAGMA table_info → {col_name: (type, pk_flag)}"""
    rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    # cid, name, type, notnull, dflt_value, pk
    return {r[1]: (r[2].upper() if r[2] else "", r[5]) for r in rows}


# ============================================================
# T1: 21 张表存在且前缀分区正确
# ============================================================
def test_init_creates_exactly_21_tables_with_correct_prefixes(fresh_sqlite: Path):
    """SCHEMA_DESIGN §2~§8：21 张 CREATE TABLE IF NOT EXISTS 必须齐。"""
    from dreambuddy_dal.implementations.sqlite_unified.schema_init import init_db_schema

    with get_sqlite_connection(str(fresh_sqlite)) as conn:
        init_db_schema(conn)
        tables = _get_tables(conn)

    assert tables == EXPECTED_21_TABLES, (
        f"表集合不匹配!\n"
        f"  缺失: {EXPECTED_21_TABLES - tables}\n"
        f"  多余: {tables - EXPECTED_21_TABLES}"
    )


# ============================================================
# T2: 5 核心表关键列 × 类型 × PK 正确
# ============================================================
@pytest.mark.parametrize("table,expected_cols", list(EXPECTED_COLUMNS.items()))
def test_core_tables_column_types_and_pk_flags(fresh_sqlite: Path, table, expected_cols):
    """抽样 5 核心表：PK 位置 + 列类型与 SCHEMA_DESIGN 一致。"""
    from dreambuddy_dal.implementations.sqlite_unified.schema_init import init_db_schema

    with get_sqlite_connection(str(fresh_sqlite)) as conn:
        init_db_schema(conn)
        actual = _get_column_info(conn, table)

    for col_name, expected_type, expected_pk in expected_cols:
        assert col_name in actual, f"[{table}] 缺失列: {col_name}"
        actual_type, actual_pk = actual[col_name]
        # 允许 INTEGER PRIMARY KEY 被 SQLite 自动归一（INTEGER PK = ANY）
        if expected_pk:
            assert actual_pk == 1, f"[{table}] {col_name} 应为 PK，实际 pk_flag={actual_pk}"
        if expected_type:
            # Decimal→TEXT / BOOL→INTEGER 在 SQLite 中 type affinity 宽松，
            # 只要前缀类型一致即通过（不强制精确匹配 COLLATE 等）
            assert actual_type.startswith(expected_type) or expected_type.startswith(actual_type), (
                f"[{table}] 列 {col_name} 类型不匹配: 期望 {expected_type}, 实际 {actual_type}"
            )


# ============================================================
# T3: 2 个业务触发器必须存在（不变量 = 不可缺）
# ============================================================
def test_critical_invariant_triggers_exist(fresh_sqlite: Path):
    """trg_rs_state_update（乐观锁）+ trg_cv_version_uniq_active（单激活）。"""
    from dreambuddy_dal.implementations.sqlite_unified.schema_init import init_db_schema

    with get_sqlite_connection(str(fresh_sqlite)) as conn:
        init_db_schema(conn)
        triggers = _get_triggers(conn)

    missing = EXPECTED_TRIGGERS - triggers
    assert not missing, f"缺失关键触发器: {missing}（SCHEMA_DESIGN §2.8 / §2.7）"


# ============================================================
# T4: 10 核心索引存在（对齐 §9.1 高频查询命中）
# ============================================================
def test_core_10_indexes_exist(fresh_sqlite: Path):
    """10 个主要 CREATE INDEX IF NOT EXISTS 必须齐。"""
    from dreambuddy_dal.implementations.sqlite_unified.schema_init import init_db_schema

    with get_sqlite_connection(str(fresh_sqlite)) as conn:
        init_db_schema(conn)
        indexes = _get_indexes(conn)

    missing = EXPECTED_INDEXES - indexes
    assert not missing, f"缺失核心索引: {missing}（SCHEMA_DESIGN §9.1 清单）"


# ============================================================
# T5: 幂等性 — init 两次不报错、表/索引/触发器集合不变
# ============================================================
def test_init_is_idempotent_twice(fresh_sqlite: Path):
    """Experience 1040063: 脚本必须幂等可重复跑。"""
    from dreambuddy_dal.implementations.sqlite_unified.schema_init import init_db_schema

    with get_sqlite_connection(str(fresh_sqlite)) as conn:
        init_db_schema(conn)
        tables1, indexes1, triggers1 = _get_tables(conn), _get_indexes(conn), _get_triggers(conn)
        # 第二次（不应抛 IntegrityError / table already exists 等）
        init_db_schema(conn)
        tables2, indexes2, triggers2 = _get_tables(conn), _get_indexes(conn), _get_triggers(conn)

    assert tables1 == tables2, "init 两次后表集合变化！幂等性破了"
    assert indexes1 == indexes2, "init 两次后索引集合变化！幂等性破了"
    assert triggers1 == triggers2, "init 两次后触发器集合变化！幂等性破了"


# ============================================================
# T6: _add_column_if_missing 补列 + DEFAULT 保留旧数据
# ============================================================
def test_add_column_if_missing_restores_column_with_data_preserved(fresh_sqlite: Path):
    """Experience 1040063 契约 1/4：缺列能补回，已有行带 DEFAULT 值不丢数据。"""
    from dreambuddy_dal.implementations.sqlite_unified.schema_init import (
        _add_column_if_missing,
        init_db_schema,
    )

    with get_sqlite_connection(str(fresh_sqlite)) as conn:
        init_db_schema(conn)
        # 1) 插入 1 行测试数据（config_family 用白名单 'v15'，对齐 CHECK 约束）
        conn.execute(
            "INSERT INTO cv_config_versions (version, config_family, is_active, released_at, payload_json, created_by, notes) "
            "VALUES ('v0.1.0', 'v15', 1, '2026-08-24T00:00:00Z', '{}', 'pytest_tester', 'schema_init_red_test')"
        )
        # 2) 模拟旧库缺列：ALTER TABLE DROP（SQLite 无 DROP COLUMN 支持旧版，所以用其他方法：
        #    直接在另一张测试表上测 helper 的补列能力更可靠）
        conn.execute("CREATE TABLE IF NOT EXISTS _test_helper_table (id INTEGER PRIMARY KEY, a TEXT)")
        conn.execute("INSERT INTO _test_helper_table (id, a) VALUES (1, 'hello')")
        # 3) 补列 b INTEGER DEFAULT 0
        _add_column_if_missing(conn, "_test_helper_table", "b", "b INTEGER DEFAULT 0")
        # 4) 验证列存在，且已有行默认值已写入
        cols = _get_column_info(conn, "_test_helper_table")
        assert "b" in cols, "_add_column_if_missing 没把列补进去"
        row = conn.execute("SELECT id, a, b FROM _test_helper_table WHERE id=1").fetchone()
        assert row == (1, "hello", 0), (
            f"补列后 DEFAULT 未生效写入旧行: {row}. "
            "ADR-19-005 要求补列必须带 DEFAULT 保证旧行非空"
        )
        # 5) 重复调用应幂等（不重复添加列，不报错）
        _add_column_if_missing(conn, "_test_helper_table", "b", "b INTEGER DEFAULT 0")
        cols2 = _get_column_info(conn, "_test_helper_table")
        assert cols == cols2, "_add_column_if_missing 重复调用应幂等，列集合不变"


# ============================================================
# T7: 2 张单行表 CHECK(id=1) 约束生效（拒绝第二行）
# ============================================================
@pytest.mark.parametrize("table", ["ma_schema_version", "rs_state"])
def test_singleton_check_id_eq_1_enforced(fresh_sqlite: Path, table: str):
    """SCHEMA_DESIGN §2.1 / §2.8：CHECK (id = 1) 单例约束必须真正生效。"""
    from dreambuddy_dal.implementations.sqlite_unified.schema_init import init_db_schema

    with get_sqlite_connection(str(fresh_sqlite)) as conn:
        init_db_schema(conn)
        # 单行表 init 后应已插入 id=1 默认行（_ensure_singleton_row）
        first = conn.execute(f"SELECT COUNT(*) FROM {table} WHERE id=1").fetchone()[0]
        assert first == 1, f"{table} 应已存在 id=1 单例，实际 {first} 行"
        # 尝试插入 id=2 → 必须抛 IntegrityError
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(f"INSERT INTO {table} (id) VALUES (2)")
