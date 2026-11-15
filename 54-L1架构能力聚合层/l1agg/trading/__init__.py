# -*- coding: utf-8 -*-
"""L1-D / L1-X 内部账本（SPEC-54 §4.6，永不进信封）。

五张表同库 `data/trading.db`（与 `cognitive_memory.db` 隔离）：
    signal      方向记录，只追加不可变（UPDATE/DELETE 被触发器拒绝）
    order       交易意图（22 执行侧回填，可改 status）
    fill        成交明细，只追加
    position    持仓快照，由 fill 重算
    comparison  L1-D ↔ L2 对照与事后收益打分（ADR-V17）
"""

from .store import (
    DB_ENV_VAR,
    DEFAULT_DB,
    SIGNAL_COLUMNS,
    TABLES,
    TradingStoreError,
    append_signal,
    connect,
    list_signals,
    migrate,
    table_columns,
)

__all__ = [
    "DB_ENV_VAR",
    "DEFAULT_DB",
    "SIGNAL_COLUMNS",
    "TABLES",
    "TradingStoreError",
    "append_signal",
    "connect",
    "list_signals",
    "migrate",
    "table_columns",
]
