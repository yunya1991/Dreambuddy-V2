"""SqliteUnified 实现：Schema 初始化 / Repository 实现 / 迁移脚本入口。"""
from .config_impl import SqliteConfigRepository
from .kg_impl import SqliteKnowledgeGraphRepository
from .market_macro_impl import SqliteMarketMacroRepository
from .position_impl import SqlitePositionRepository
from .risk_impl import SqliteRiskRepository
from .schema_init import (
    _add_column_if_missing,
    _add_index_if_missing,
    _ensure_singleton_row,
    init_db_schema,
)
from .trade_impl import SqliteTradeRepository


def get_default_sqlite_db_path() -> str:
    """默认 sqlite_unified 单库路径 = DATA_DIR/dreambuddy_core.db。"""
    import os
    data_dir = os.environ.get("DATA_DIR", "./data")
    env_override = os.environ.get("DREAMBUDDY_CORE_DB")
    if env_override:
        return env_override
    return os.path.join(data_dir, "dreambuddy_core.db")


__all__ = [
    "init_db_schema",
    "_add_column_if_missing",
    "_add_index_if_missing",
    "_ensure_singleton_row",
    "SqliteTradeRepository",
    "SqlitePositionRepository",
    "SqliteRiskRepository",
    "SqliteMarketMacroRepository",
    "SqliteConfigRepository",
    "SqliteKnowledgeGraphRepository",
    "get_default_sqlite_db_path",
]
