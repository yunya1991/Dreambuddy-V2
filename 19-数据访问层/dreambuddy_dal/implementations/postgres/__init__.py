"""dreambuddy_dal PG 后端（C4a）。

第四后端 postgres：PostgresTradeRepository 等（第一批：trade）。
- 协议 100% 对齐 dreambuddy_dal.protocols
- 序列化复用 sqlite_unified 实现（字段级一致）
- 连接：DAL_PG_URL / DATABASE_URL（短连接，与 sqlite_unified 同生命周期语义）
"""
from dreambuddy_dal.implementations.postgres.connection import (
    get_pg_connection,
    get_pg_dsn,
)
from dreambuddy_dal.implementations.postgres.trade_impl import (
    PostgresTradeRepository,
)

__all__ = [
    "get_pg_connection",
    "get_pg_dsn",
    "PostgresTradeRepository",
]
