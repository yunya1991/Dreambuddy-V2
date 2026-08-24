"""
SqliteUnified 实现：Schema 初始化入口

设计遵循（自上而下约束优先级）：
1. ADR-19-004：Decimal → TEXT（SQLite 不存 REAL 防精度丢失）
2. ADR-19-005：CREATE TABLE IF NOT EXISTS = 最终 Schema
   + _add_column_if_missing 对旧库补列（新库零动作）
3. SCHEMA_DESIGN.md §2~§8 列定义；§9.1 索引清单；§10 4 helper 契约
4. Experience 1040063：所有 DDL 幂等（IF NOT EXISTS 到处加）

入口：init_db_schema(conn)  → 每次启动 dreambuddy_dal / di.py = sqlite_unified 时调一次
"""
from __future__ import annotations

import sqlite3
from typing import Iterable

# ============================================================
# 1. CREATE TABLE IF NOT EXISTS × 20（普通表）
#    + CREATE VIRTUAL TABLE IF NOT EXISTS × 1（kg_terms_fts FTS5）
#    = 共 21 张
# ============================================================
_CREATE_TABLES_SQL: list[str] = [
    # ---- ma_* 元数据 3 张 ----
    """
CREATE TABLE IF NOT EXISTS ma_schema_version (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    version INTEGER NOT NULL,
    schema_semver TEXT NOT NULL,
    upgraded_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    upgraded_by TEXT NOT NULL DEFAULT 'system',
    notes TEXT
)
""",
    """
CREATE TABLE IF NOT EXISTS ma_migration_audit (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    category TEXT NOT NULL CHECK (category IN (
        'migration_script','legacy_write_fail','next_gen_write_fail','next_gen_read_fail',
        'id_mismatch','read_diff','integrity_check','schema_upgrade',
        'dual_write','shadow_read'
    )),
    event_name TEXT NOT NULL,
    entity_key TEXT,
    result TEXT NOT NULL CHECK (result IN ('APPLIED','SKIPPED','FAILED','WARN','MATCH','DIFF')),
    severity INTEGER NOT NULL DEFAULT 0 CHECK (severity BETWEEN 0 AND 3),
    details TEXT,
    latency_ms INTEGER
)
""",
    """
CREATE TABLE IF NOT EXISTS ma_integrity_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    integrity_result TEXT NOT NULL,
    db_size_bytes INTEGER NOT NULL,
    wal_size_bytes INTEGER,
    schema_version INTEGER NOT NULL,
    checkpoint_result TEXT,
    free_disk_pct REAL
)
""",
    # ---- tr_* 交易域 3 张（ADR-19-004：Decimal 价格/盈亏全 TEXT） ----
    """
CREATE TABLE IF NOT EXISTS tr_trades (
    trade_id TEXT PRIMARY KEY,
    sub_system TEXT NOT NULL DEFAULT 'unknown',
    strategy_name TEXT NOT NULL DEFAULT 'unknown',
    strategy_source TEXT NOT NULL DEFAULT 'unknown'
        CHECK (strategy_source IN ('yijing','v15','classic','triple_screen','manual','unknown')),
    symbol TEXT NOT NULL,
    inst_id TEXT,
    direction TEXT NOT NULL CHECK (direction IN ('long','short')),
    entry_price TEXT NOT NULL,
    quantity TEXT NOT NULL,
    entry_ts TEXT NOT NULL,
    stop_loss TEXT,
    take_profit TEXT,
    exit_price TEXT,
    exit_ts TEXT,
    realized_pnl TEXT NOT NULL DEFAULT '0',
    pnl_pct REAL NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'open' CHECK (status IN ('open','closed','partial')),
    exit_reason TEXT,
    close_info_json TEXT,
    confidence REAL CHECK (confidence IS NULL OR confidence BETWEEN 0 AND 1),
    hexagram TEXT,
    regime_pred TEXT,
    war_state TEXT CHECK (war_state IN ('ALLOW','DEFEND','SURRENDER')),
    strategy_mask TEXT,
    style_exposure TEXT,
    base_sl_roi REAL,
    base_tp_roi REAL,
    risk_level_cn TEXT NOT NULL DEFAULT '低风险',
    is_trial INTEGER NOT NULL DEFAULT 0 CHECK (is_trial IN (0,1)),
    trial_status TEXT CHECK (trial_status IN (
        'NOT_APPLICABLE','OPENED_30MIN_WAIT','EVAL_LARGEN','EVAL_CLOSE',
        'EVAL_HOLD_1H','EVAL_PASS'
    )),
    trial_open_ts TEXT,
    trial_eval_done INTEGER NOT NULL DEFAULT 0 CHECK (trial_eval_done IN (0,1)),
    trial_eval_result TEXT CHECK (trial_eval_result IS NULL OR trial_eval_result IN ('add','close','hold')),
    liangyi_state TEXT,
    market_snapshot TEXT,
    scale_params TEXT,
    extra_payload TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
)
""",
    """
CREATE TABLE IF NOT EXISTS tr_daily_stats (
    date TEXT PRIMARY KEY,
    total_trades INTEGER NOT NULL DEFAULT 0,
    win_trades INTEGER NOT NULL DEFAULT 0,
    loss_trades INTEGER NOT NULL DEFAULT 0,
    open_trades INTEGER NOT NULL DEFAULT 0,
    total_pnl TEXT NOT NULL DEFAULT '0',
    win_pnl TEXT NOT NULL DEFAULT '0',
    loss_pnl TEXT NOT NULL DEFAULT '0',
    avg_win TEXT NOT NULL DEFAULT '0',
    avg_loss TEXT NOT NULL DEFAULT '0',
    max_single_win TEXT NOT NULL DEFAULT '0',
    max_single_loss TEXT NOT NULL DEFAULT '0',
    win_rate REAL NOT NULL DEFAULT 0,
    profit_factor REAL NOT NULL DEFAULT 0,
    avg_r_multiple REAL NOT NULL DEFAULT 0,
    starting_equity TEXT NOT NULL DEFAULT '0',
    ending_equity TEXT NOT NULL DEFAULT '0',
    peak_equity TEXT NOT NULL DEFAULT '0',
    max_drawdown REAL NOT NULL DEFAULT 0,
    daily_drawdown REAL NOT NULL DEFAULT 0,
    circuit_breaker_triggered INTEGER NOT NULL DEFAULT 0,
    consecutive_losses_end INTEGER NOT NULL DEFAULT 0,
    computed_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    source TEXT NOT NULL DEFAULT 'agg_trades'
)
""",
    """
CREATE TABLE IF NOT EXISTS tr_daily_stats_overrides (
    date TEXT PRIMARY KEY REFERENCES tr_daily_stats(date) ON DELETE CASCADE,
    total_pnl_override TEXT,
    ending_equity_override TEXT,
    win_rate_override REAL,
    max_drawdown_override REAL,
    reason TEXT NOT NULL,
    operator TEXT NOT NULL,
    overridden_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    evidence_url TEXT
)
""",
    # ---- po_* 持仓域 2 张 ----
    """
CREATE TABLE IF NOT EXISTS po_positions (
    inst_id TEXT PRIMARY KEY,
    position_id TEXT NOT NULL,
    trade_id TEXT NOT NULL REFERENCES tr_trades(trade_id),
    sub_system TEXT NOT NULL,
    symbol TEXT NOT NULL,
    direction TEXT NOT NULL CHECK (direction IN ('long','short')),
    entry_price TEXT NOT NULL,
    quantity TEXT NOT NULL,
    opened_at TEXT NOT NULL,
    mark_price TEXT NOT NULL,
    unrealized_pnl TEXT NOT NULL DEFAULT '0',
    unrealized_pnl_pct REAL NOT NULL DEFAULT 0,
    liquidation_price TEXT,
    stop_loss_price TEXT,
    take_profit_price TEXT,
    current_leverage REAL,
    is_trial INTEGER NOT NULL DEFAULT 0,
    trial_open_ts TEXT,
    trial_eval_done INTEGER NOT NULL DEFAULT 0,
    last_price_refresh_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    version INTEGER NOT NULL DEFAULT 1
)
""",
    """
CREATE TABLE IF NOT EXISTS po_price_refresh_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    refresh_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    positions_updated INTEGER NOT NULL,
    latency_ms INTEGER NOT NULL,
    okx_api_error TEXT,
    source TEXT NOT NULL DEFAULT 'polling_trader'
)
""",
    # ---- mm_* 宏观域 6 张 ----
    """
CREATE TABLE IF NOT EXISTS mm_fear_greed (
    timestamp INTEGER PRIMARY KEY,
    fear_greed_index INTEGER NOT NULL CHECK (fear_greed_index BETWEEN 0 AND 100),
    value_classification TEXT,
    trend_7d REAL,
    raw_payload TEXT,
    ingested_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
)
""",
    """
CREATE TABLE IF NOT EXISTS mm_funding_rate (
    symbol TEXT NOT NULL,
    timestamp INTEGER NOT NULL,
    funding_rate REAL NOT NULL,
    funding_interval_hours INTEGER DEFAULT 8,
    raw_payload TEXT,
    ingested_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (symbol, timestamp)
) WITHOUT ROWID
""",
    """
CREATE TABLE IF NOT EXISTS mm_open_interest (
    symbol TEXT NOT NULL,
    timestamp INTEGER NOT NULL,
    open_interest REAL NOT NULL,
    oi_change_pct_24h REAL,
    raw_payload TEXT,
    ingested_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (symbol, timestamp)
) WITHOUT ROWID
""",
    """
CREATE TABLE IF NOT EXISTS mm_liquidation (
    symbol TEXT NOT NULL,
    timestamp INTEGER NOT NULL,
    liq_long_usdt REAL NOT NULL DEFAULT 0,
    liq_short_usdt REAL NOT NULL DEFAULT 0,
    liq_total_usdt REAL NOT NULL DEFAULT 0,
    raw_payload TEXT,
    ingested_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (symbol, timestamp)
) WITHOUT ROWID
""",
    """
CREATE TABLE IF NOT EXISTS mm_long_short_ratio (
    symbol TEXT NOT NULL,
    timestamp INTEGER NOT NULL,
    long_short_ratio REAL NOT NULL,
    long_accounts INTEGER,
    short_accounts INTEGER,
    raw_payload TEXT,
    ingested_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (symbol, timestamp)
) WITHOUT ROWID
""",
    """
CREATE TABLE IF NOT EXISTS mm_taker_volume (
    symbol TEXT NOT NULL,
    timestamp INTEGER NOT NULL,
    taker_buy_vol REAL NOT NULL DEFAULT 0,
    taker_sell_vol REAL NOT NULL DEFAULT 0,
    taker_buy_sell_ratio REAL,
    raw_payload TEXT,
    ingested_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (symbol, timestamp)
) WITHOUT ROWID
""",
    # ---- rs_* 风控域 2 张 ----
    """
CREATE TABLE IF NOT EXISTS rs_state (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    daily_pnl REAL NOT NULL DEFAULT 0,
    total_risk_exposure TEXT NOT NULL DEFAULT '0',
    open_positions_count INTEGER NOT NULL DEFAULT 0,
    daily_realized_pnl TEXT NOT NULL DEFAULT '0',
    daily_loss_limit REAL NOT NULL DEFAULT -1000,
    loss_limit_pct REAL NOT NULL DEFAULT 0.20,
    daily_drawdown_pct REAL NOT NULL DEFAULT 0,
    circuit_breaker_active INTEGER NOT NULL DEFAULT 0 CHECK (circuit_breaker_active IN (0,1)),
    circuit_breaker_reason TEXT,
    circuit_breaker_at TEXT,
    last_alert_ts TEXT,
    kill_switch_active INTEGER NOT NULL DEFAULT 0 CHECK (kill_switch_active IN (0,1)),
    current_consecutive_losses INTEGER NOT NULL DEFAULT 0,
    max_consecutive_losses INTEGER NOT NULL DEFAULT 0,
    trading_halted INTEGER NOT NULL DEFAULT 0 CHECK (trading_halted IN (0,1)),
    halt_reason TEXT,
    halt_by TEXT,
    halt_at TEXT,
    position_size_pct REAL NOT NULL DEFAULT 1.0,
    min_position_usdt REAL NOT NULL DEFAULT 10,
    five_domain_score REAL,
    war_state TEXT DEFAULT 'ALLOW' CHECK (war_state IN ('ALLOW','DEFEND','SURRENDER')),
    strategy_mask TEXT,
    style_exposure_weights TEXT,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_by TEXT NOT NULL DEFAULT 'system',
    version INTEGER NOT NULL DEFAULT 1
)
""",
    """
CREATE TABLE IF NOT EXISTS rs_cases (
    case_id TEXT PRIMARY KEY,
    case_type TEXT NOT NULL,
    severity INTEGER NOT NULL CHECK (severity BETWEEN 0 AND 5),
    alert_ts TEXT NOT NULL,
    symbol TEXT,
    description TEXT,
    related_trade_id TEXT REFERENCES tr_trades(trade_id),
    state_snapshot TEXT NOT NULL,
    rule_params TEXT,
    action_taken TEXT NOT NULL,
    outcome INTEGER,
    notes TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
)
""",
    # ---- cv_* 配置域 1 张 ----
    """
CREATE TABLE IF NOT EXISTS cv_config_versions (
    version TEXT PRIMARY KEY,
    config_family TEXT NOT NULL DEFAULT 'baseline'
        CHECK (config_family IN ('baseline','v15','yijing','risk_params','classic','global')),
    payload_json TEXT NOT NULL,
    changelog TEXT,
    created_by TEXT NOT NULL DEFAULT 'system',
    released_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    is_active INTEGER NOT NULL DEFAULT 0 CHECK (is_active IN (0,1)),
    notes TEXT,
    archived INTEGER NOT NULL DEFAULT 0
)
""",
    # ---- kg_* 知识图谱 3 张普通表 + 1 张 FTS5 虚拟表 ----
    """
CREATE TABLE IF NOT EXISTS kg_entities (
    entity_id TEXT PRIMARY KEY,
    label TEXT NOT NULL,
    category TEXT NOT NULL,
    metadata TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
)
""",
    """
CREATE TABLE IF NOT EXISTS kg_entity_aliases (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    entity_id TEXT NOT NULL REFERENCES kg_entities(entity_id) ON DELETE CASCADE,
    alias TEXT NOT NULL,
    is_primary INTEGER NOT NULL DEFAULT 0 CHECK (is_primary IN (0,1)),
    UNIQUE(entity_id, alias)
)
""",
    """
CREATE TABLE IF NOT EXISTS kg_triples (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    subject TEXT NOT NULL REFERENCES kg_entities(entity_id),
    predicate TEXT NOT NULL,
    object TEXT NOT NULL,
    confidence REAL NOT NULL DEFAULT 1.0 CHECK (confidence BETWEEN 0 AND 1),
    sources TEXT,
    valid_from TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    valid_to TEXT,
    tx_created TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    tx_retired TEXT
)
""",
    """
CREATE VIRTUAL TABLE IF NOT EXISTS kg_terms_fts USING fts5(
    term,
    entity_id UNINDEXED,
    triple_id UNINDEXED,
    content='kg_triples',
    content_rowid='id',
    tokenize = 'unicode61'
)
""",
]


# ============================================================
# 2. CREATE INDEX IF NOT EXISTS × 16（§9.1 共 22 个减去 6 PK）
# ============================================================
_CREATE_INDEXES_SQL: list[str] = [
    "CREATE INDEX IF NOT EXISTS idx_ma_audit_time_sev ON ma_migration_audit(run_at, severity)",
    "CREATE INDEX IF NOT EXISTS idx_ma_audit_category ON ma_migration_audit(category, run_at DESC)",
    "CREATE INDEX IF NOT EXISTS idx_ma_integrity_time ON ma_integrity_log(run_at DESC)",
    "CREATE INDEX IF NOT EXISTS idx_tr_trades_symbol_entry_time ON tr_trades(symbol, entry_ts DESC)",
    "CREATE INDEX IF NOT EXISTS idx_tr_trades_open ON tr_trades(exit_ts) WHERE exit_ts IS NULL",
    "CREATE INDEX IF NOT EXISTS idx_tr_trades_is_trial ON tr_trades(is_trial, trial_eval_done)",
    "CREATE INDEX IF NOT EXISTS idx_tr_trades_strategy ON tr_trades(strategy_source, entry_ts)",
    "CREATE INDEX IF NOT EXISTS idx_tr_trades_daily ON tr_trades(DATE(entry_ts))",
    "CREATE INDEX IF NOT EXISTS idx_po_positions_symbol ON po_positions(symbol)",
    "CREATE INDEX IF NOT EXISTS idx_po_positions_open_time ON po_positions(opened_at DESC)",
    "CREATE INDEX IF NOT EXISTS idx_po_refresh_time ON po_price_refresh_log(refresh_at DESC)",
    "CREATE INDEX IF NOT EXISTS idx_mm_funding_time ON mm_funding_rate(timestamp DESC)",
    "CREATE INDEX IF NOT EXISTS idx_rs_cases_severity ON rs_cases(severity DESC, alert_ts DESC)",
    "CREATE INDEX IF NOT EXISTS idx_rs_cases_type ON rs_cases(case_type, alert_ts DESC)",
    "CREATE INDEX IF NOT EXISTS idx_cv_versions_released ON cv_config_versions(released_at DESC)",
    "CREATE INDEX IF NOT EXISTS idx_cv_versions_family ON cv_config_versions(config_family, released_at DESC)",
    "CREATE INDEX IF NOT EXISTS idx_kg_triples_spo ON kg_triples(subject, predicate, object)",
    "CREATE INDEX IF NOT EXISTS idx_kg_triples_pred_obj ON kg_triples(predicate, object)",
    "CREATE INDEX IF NOT EXISTS idx_kg_triples_valid ON kg_triples(valid_from, COALESCE(valid_to, '9999-12-31'))",
    "CREATE INDEX IF NOT EXISTS idx_kg_aliases_alias ON kg_entity_aliases(alias)",
]


# ============================================================
# 3. CREATE TRIGGER IF NOT EXISTS × 4
# ============================================================
_CREATE_TRIGGERS_SQL: list[str] = [
    """
CREATE TRIGGER IF NOT EXISTS trg_rs_state_update
AFTER UPDATE ON rs_state
BEGIN
    UPDATE rs_state
    SET updated_at = CURRENT_TIMESTAMP,
        version    = version + 1
    WHERE id = 1;
END
""",
    """
CREATE TRIGGER IF NOT EXISTS trg_cv_version_uniq_active
AFTER INSERT ON cv_config_versions WHEN NEW.is_active = 1
BEGIN
    UPDATE cv_config_versions
    SET is_active = 0
    WHERE config_family = NEW.config_family
      AND version != NEW.version;
END
""",
    """
CREATE TRIGGER IF NOT EXISTS trg_kg_entity_ai
AFTER INSERT ON kg_entities BEGIN
    INSERT INTO kg_terms_fts(rowid, term, entity_id, triple_id)
    VALUES (new.rowid, NEW.label || ' ' || NEW.category, NEW.entity_id, NULL);
END
""",
    """
CREATE TRIGGER IF NOT EXISTS trg_kg_triple_ai
AFTER INSERT ON kg_triples BEGIN
    INSERT INTO kg_terms_fts(rowid, term, entity_id, triple_id)
    VALUES (new.rowid, NEW.subject || ' ' || NEW.predicate || ' ' || NEW.object, NULL, NEW.id);
END
""",
]


# ============================================================
# 4. 4 个迁移 Helper（§10 Experience 1040063 契约入口）
# ============================================================
def _add_column_if_missing(
    conn: sqlite3.Connection,
    table: str,
    column: str,
    ddl_with_default: str,
) -> bool:
    """§10 Helper 1/4：缺列 → ALTER TABLE ADD；必带 DEFAULT；幂等。"""
    cols = {r[1] for r in conn.execute(f"PRAGMA table_info({table})").fetchall()}
    if column in cols:
        return False
    conn.execute(f"ALTER TABLE {table} ADD COLUMN {ddl_with_default}")
    return True


def _add_index_if_missing(
    conn: sqlite3.Connection,
    name: str,
    table: str,
    cols: Iterable[str],
    unique: bool = False,
) -> bool:
    """§10 Helper 2/4：缺索引 → CREATE [UNIQUE] INDEX IF NOT EXISTS；幂等。

    Args:
        unique: True 时生成 UNIQUE INDEX（唯一值索引，冲突抛 IntegrityError）
    """
    existing = {r[1] for r in conn.execute(f"PRAGMA index_list({table})").fetchall()}
    if name in existing:
        return False
    uniq = "UNIQUE " if unique else ""
    conn.execute(
        f"CREATE {uniq}INDEX IF NOT EXISTS {name} ON {table}({', '.join(cols)})"
    )
    return True


def _ensure_singleton_row(
    conn: sqlite3.Connection,
    table: str,
    default_values: dict[str, object],
) -> None:
    """§10 Helper 4/4：单行表空表时 INSERT 默认行。幂等。"""
    exists = conn.execute(f"SELECT COUNT(*) FROM {table} WHERE id = 1").fetchone()[0]
    if exists:
        return
    cols = ", ".join(default_values.keys())
    placeholders = ", ".join([f":{k}" for k in default_values.keys()])
    conn.execute(
        f"INSERT INTO {table} (id, {cols}) VALUES (1, {placeholders})",
        default_values,
    )


# ============================================================
# 5. 主入口：init_db_schema(conn)
# ============================================================
def init_db_schema(conn: sqlite3.Connection) -> None:
    """Schema 初始化主入口。幂等。"""
    # 1) 21 张表
    for ddl in _CREATE_TABLES_SQL:
        conn.execute(ddl)
    # 2) 20 索引（§9.1 减去 PK 后）
    for sql in _CREATE_INDEXES_SQL:
        conn.execute(sql)
    # 3) 4 触发器
    for sql in _CREATE_TRIGGERS_SQL:
        conn.execute(sql)
    # 4) 2 张单行表默认行
    _ensure_singleton_row(
        conn,
        "ma_schema_version",
        {
            "version": 1,
            "schema_semver": "1.0.0",
            "upgraded_by": "schema_init",
            "notes": "P1 v1.0.0 首次初始化 21 张表 Schema（对齐 SCHEMA_DESIGN.md §2~§8）",
        },
    )
    _ensure_singleton_row(
        conn,
        "rs_state",
        {
            "daily_pnl": 0.0,
            "total_risk_exposure": "0",
            "open_positions_count": 0,
            "daily_realized_pnl": "0",
            "daily_loss_limit": -1000.0,
            "loss_limit_pct": 0.20,
            "daily_drawdown_pct": 0.0,
            "circuit_breaker_active": 0,
            "kill_switch_active": 0,
            "current_consecutive_losses": 0,
            "max_consecutive_losses": 0,
            "trading_halted": 0,
            "position_size_pct": 1.0,
            "min_position_usdt": 10.0,
            "war_state": "ALLOW",
            "updated_by": "schema_init",
            "version": 1,
        },
    )


__all__ = [
    "init_db_schema",
    "_add_column_if_missing",
    "_add_index_if_missing",
    "_ensure_singleton_row",
]
