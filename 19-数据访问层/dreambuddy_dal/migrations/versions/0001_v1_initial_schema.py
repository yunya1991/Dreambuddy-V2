"""v1.0 initial schema: 21 tables + 20 indexes + 4 triggers

Revision ID: 0001_v1_initial_schema
Revises:
Create Date: 2026-08-24

对齐 SCHEMA_DESIGN.md v1.0 + schema_init.py 的 TARGET_CREATE_TABLES_SQL。
此 revision 是迁移链起点；后续 Schema 变更必须走 Alembic（ADR-19-005）。
"""
from __future__ import annotations

import os
import sys
from typing import Sequence, Union

from alembic import op

# revision identifiers
revision: str = "0001_v1_initial_schema"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _get_schema_sqls() -> list[str]:
    """从 schema_init.py 引入 DDL 列表，保持单一事实源。"""
    this_dir = os.path.dirname(os.path.abspath(__file__))
    for p in [
        os.path.join(this_dir, ".."),       # migrations/
        os.path.join(this_dir, "..", ".."),  # dreambuddy_dal/
        os.path.join(this_dir, "..", "..", ".."),  # 19-数据访问层/
    ]:
        if p not in sys.path:
            sys.path.insert(0, p)
    from dreambuddy_dal.implementations.sqlite_unified.schema_init import (
        _CREATE_TABLES_SQL,
        _CREATE_INDEXES_SQL,
    )
    return list(_CREATE_TABLES_SQL) + list(_CREATE_INDEXES_SQL)


def upgrade() -> None:
    """v1.0 建表 + 建索引（幂等：CREATE TABLE IF NOT EXISTS）。"""
    for sql in _get_schema_sqls():
        op.execute(sql)

    # 种子数据：ma_schema_version v1.0.0（单行表 CHECK id=1）
    op.execute(
        "INSERT OR IGNORE INTO ma_schema_version (id, version, schema_semver, upgraded_by, notes) "
        "VALUES (1, 1, '1.0.0', 'alembic_v1', 'P1 v1.0.0 首次初始化 21 张表 Schema（对齐 SCHEMA_DESIGN.md）')"
    )
    # rs_state 单行种子
    op.execute(
        "INSERT OR IGNORE INTO rs_state (id, version) VALUES (1, 1)"
    )
    # tr_trades 虚拟 FK 种子行
    op.execute(
        "INSERT OR IGNORE INTO tr_trades (trade_id, sub_system, strategy_name, "
        "symbol, direction, entry_price, quantity, entry_ts, stop_loss, take_profit, "
        "risk_level_cn) "
        "VALUES ('__NO_LINK__', 'MANUAL', 'system', 'NONE', 'long', 0, 0, "
        "'1970-01-01T00:00:00+00:00', 0, 0, '低风险')"
    )


def downgrade() -> None:
    """downgrade 慎用：DROP 全部表。"""
    tables = [
        "kg_terms_fts", "kg_triples", "kg_entity_aliases", "kg_entities",
        "cv_config_versions",
        "rs_cases", "rs_state",
        "mm_taker_volume", "mm_long_short_ratio", "mm_liquidation",
        "mm_open_interest", "mm_funding_rate", "mm_fear_greed",
        "po_price_refresh_log", "po_positions",
        "tr_daily_stats_overrides", "tr_daily_stats", "tr_trades",
        "ma_integrity_log", "ma_migration_audit", "ma_schema_version",
    ]
    for t in tables:
        op.execute(f"DROP TABLE IF EXISTS {t}")
