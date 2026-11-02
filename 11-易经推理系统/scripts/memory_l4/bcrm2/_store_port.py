# -*- coding: utf-8 -*-
"""bcrm2 读/写路径 Store port 收编（C5 第四批只读先行；第七批写路径收编）。

原状：
  - `macro_data_fetcher.py` 4 处直连：2 处只读 data_center.db `records`，2 处缓存读写
  - `incremental_learner.py` 7 处直连：3 处只读 bcrm 学习库，4 处写入（建表/INSERT/commit）
  - `scripts/backfill_fma_shadow.py` 3 处直连：regime 读 / shadow 清写 / 评估读

第四批按 SPEC-C **只读查询先行、写路径暂缓**：收编 4 处只读。
第七批收编写路径与剩余读路径（共 9 处调用点）：
  BCRM_MACRO_STORE_PORT=1    → macro_data_fetcher 缓存读写走 port 分支
  BCRM_LEARNER_STORE_PORT=1  → incremental_learner 四处写走 port 分支
  BCRM_BACKFILL_STORE_PORT=1 → backfill_fma_shadow 三处读写走 port 分支
  默认（未设置）→ legacy 直连，SQL 与返回行为与原实现零变化。

写路径 fail-safe：port 分支任何异常一律回退 legacy 直写（保持久性，
非 FAIL-OPEN 返回空）；全部写操作幂等（INSERT OR IGNORE/REPLACE、
CREATE IF NOT EXISTS、DELETE+重插、to_sql replace），回退重放安全。

第八批收编 3 处剩余直连：
  - learner 聚合读（AVG/SUM 专用 SQL，通用 port 不可表达 → fetch_recent_performance，
    复用 BCRM_LEARNER_STORE_PORT 开关，port 分支 _connect_ro 同 SQL）；
  - storage.py / kg_store.py 连接持有型：connect_persistent / connect_autocommit
    纯透传工厂（参数与原直连逐字节等价，故无开关），connect 字面量集中本文件。

SqliteReadOnlyPort 结构化实现 dreambuddy_l0.ports.store.StorePort 协议
（read/query/health），连接一律 `mode=ro`；write 未开放。
写路径 port 分支统一经 `_connect_rw`（单一收口，未来可替换真实 Store 实现）。
"""

from __future__ import annotations

import os
import sqlite3
from datetime import datetime
from typing import Any, Dict, List, Optional, Sequence, Tuple

_TRUTHY = ("1", "true", "on")


def _switch(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in _TRUTHY


class SqliteReadOnlyPort:
    """只读 SQLite StorePort 适配器（泛化表名/列/过滤，C5 第四批）。

    read(table, key=...)            → {"row": dict|None, "error_code": str}
    write(...)                      → 本批只读收编，未开放
    query(table, filters=..., ...)  → {"rows": [dict, ...], "count": int, "error_code": str}
    health()                        → {"ok": bool, ...}
    """

    def __init__(self, db_path: str):
        self._db_path = db_path

    def _connect(self):
        conn = sqlite3.connect(f"file:{self._db_path}?mode=ro", uri=True)
        conn.row_factory = sqlite3.Row
        return conn

    def read(
        self, table: str, *, key: str, cursor: Optional[str] = None, limit: int = 100
    ) -> Dict[str, Any]:
        conn = self._connect()
        try:
            row = conn.execute("SELECT * FROM " + table + " WHERE id = ?", (key,)).fetchone()
        except sqlite3.Error:
            return {"row": None, "error_code": "unknown_table"}
        finally:
            conn.close()
        if row is None:
            return {"row": None, "error_code": "not_found"}
        return {"row": dict(row), "error_code": ""}

    def write(self, table: str, *, data: Dict[str, Any], idempotency_key: str = "") -> bool:
        raise NotImplementedError("C5 第四批只读收编：write 未开放")

    def query(
        self,
        table: str,
        *,
        filters: Optional[Dict[str, Any]] = None,
        cursor: Optional[str] = None,
        limit: int = 100,
        order_by: str = "rowid DESC",
        columns: str = "*",
    ) -> Dict[str, Any]:
        where, params = [], []
        for col in sorted(filters or {}):
            where.append(col + " = ?")
            params.append(filters[col])
        sql = "SELECT " + columns + " FROM " + table
        if where:
            sql += " WHERE " + " AND ".join(where)
        if order_by:
            sql += " ORDER BY " + order_by
        sql += " LIMIT ?"
        params.append(int(limit))
        conn = self._connect()
        try:
            rows = conn.execute(sql, params).fetchall()
        except sqlite3.Error:
            return {"rows": [], "count": 0, "error_code": "unknown_table"}
        finally:
            conn.close()
        return {"rows": [dict(r) for r in rows], "count": len(rows), "error_code": ""}

    def health(self) -> Dict[str, Any]:
        try:
            conn = self._connect()
            conn.close()
            return {"ok": True, "db": self._db_path}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}


# ---------------------------------------------------------------------------
# 读取助手（文件粒度开关路由；默认 legacy 直连，行为零变化）
# ---------------------------------------------------------------------------


def fetch_records_by_sources(
    db_path: str,
    sources: Sequence[str],
    switch: str = "BCRM_MACRO_STORE_PORT",
    columns: str = "source, sub_category, metrics, timestamp, id",
    as_tuple: bool = True,
) -> List[Any]:
    """按 source 白名单取 data_center.db `records` 行（id DESC 全序）。

    供 macro_data_fetcher 两处只读使用。开关打开 → 走 SqliteReadOnlyPort；
    默认 legacy 直连（原 SQL 原样保留，返回 sqlite3.Row 可索引）。
    两模式返回均支持下标访问（port 分支按 columns 顺序转 tuple）。
    """
    if _switch(switch):
        try:
            port = SqliteReadOnlyPort(db_path)
            merged: List[Any] = []
            for src in sources:
                r = port.query(
                    "records",
                    filters={"source": src},
                    columns=columns,
                    limit=1000000,
                    order_by="id DESC",
                )
                cols = [c.strip() for c in columns.split(",")]
                for row in r.get("rows") or []:
                    if as_tuple:
                        merged.append(tuple(row.get(c) for c in cols))
                    else:
                        merged.append(row)
            cols = [c.strip() for c in columns.split(",")]
            id_idx = cols.index("id") if "id" in cols else None
            if as_tuple:
                sort_idx = id_idx if id_idx is not None else len(cols) - 1
                merged.sort(key=lambda t: t[sort_idx], reverse=True)
            else:
                merged.sort(key=lambda d: d.get("id") or 0, reverse=True)
            return merged
        except Exception:
            return []  # FAIL-OPEN：与 legacy 异常路径一致（调用方返回空 DataFrame）
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        return conn.execute(
            "SELECT "
            + columns
            + " FROM records WHERE source IN ("
            + ",".join("?" * len(sources))
            + ") ORDER BY id DESC",
            tuple(sources),
        ).fetchall()
    finally:
        conn.close()


def fetch_table_rows(
    db_path: str,
    table: str,
    switch: str,
    filters: Optional[Dict[str, Any]] = None,
    order_by: str = "rowid DESC",
    limit: Optional[int] = None,
    columns: str = "*",
) -> List[Dict[str, Any]]:
    """泛化表读取（返回 dict 列表）；供 incremental_learner 读 bcrm 学习库。

    开关打开 → 走 SqliteReadOnlyPort；默认 legacy 直连（原 cursor/
    description 组装 dict 的方式原样保留，异常返回 []）。
    limit=None 时 legacy 不加 LIMIT（与原 SQL 逐字一致），port 侧取全量。
    """
    if _switch(switch):
        try:
            port = SqliteReadOnlyPort(db_path)
            return (
                port.query(
                    table,
                    filters=filters,
                    columns=columns,
                    limit=limit or 1000000,
                    order_by=order_by,
                ).get("rows")
                or []
            )
        except Exception:
            return []  # FAIL-OPEN
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    try:
        sql = "SELECT " + columns + " FROM " + table
        params: Tuple[Any, ...] = ()
        if filters:
            sql += " WHERE " + " AND ".join(c + " = ?" for c in sorted(filters))
            params = tuple(filters[c] for c in sorted(filters))
        sql += " ORDER BY " + order_by
        if limit is not None:
            sql += " LIMIT ?"
            params += (limit,)
        cursor.execute(sql, params)
        rows = cursor.fetchall()
        cols = [desc[0] for desc in cursor.description]
        return [dict(zip(cols, row, strict=True)) for row in rows]
    except Exception:
        return []
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# 连接工厂（C5 第七批：写路径 port 分支统一收口；legacy 分支仍内联原连接）
# ---------------------------------------------------------------------------


def _connect_rw(db_path: str):
    """写路径 port 分支统一连接入口（未来可替换为真实 Store 实现）。"""
    return sqlite3.connect(db_path)


def _connect_ro(db_path: str, *, row: bool = True):
    """读路径 port 分支只读连接（mode=ro）；row=True 时按列名取值。"""
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    if row:
        conn.row_factory = sqlite3.Row
    return conn


def connect_persistent(db_path):
    """连接持有型 Store 的持久连接工厂（C5 第八批收编集中点）。

    纯参数透传（check_same_thread=False，供 Flask 多线程读取），
    与调用方原直连逐字节等价，故无开关；row_factory 设置留调用方。
    """
    return sqlite3.connect(str(db_path), check_same_thread=False)


def connect_autocommit(db_path):
    """autocommit（isolation_level=None）连接工厂（KGStore WAL+FTS 场景）。

    纯参数透传，与调用方原直连逐字节等价，故无开关；
    PRAGMA / DDL / 重试逻辑留调用方。
    """
    return sqlite3.connect(db_path, isolation_level=None)


# ---------------------------------------------------------------------------
# 写助手：incremental_learner（C5 第七批；开关 BCRM_LEARNER_STORE_PORT）
# SQL 与原实现逐字一致；port 分支异常回退 legacy 直写（幂等，重放安全）。
# ---------------------------------------------------------------------------

_LEARNER_DDL = (
    """
    CREATE TABLE IF NOT EXISTS trades (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        symbol TEXT NOT NULL,
        direction INTEGER NOT NULL,
        entry_time TEXT NOT NULL,
        exit_time TEXT,
        entry_price REAL NOT NULL,
        exit_price REAL,
        pnl_pct REAL,
        hold_bars INTEGER,
        exit_reason TEXT,
        confidence REAL,
        hexagram TEXT,
        upper_gua TEXT,
        lower_gua TEXT,
        position_factor REAL,
        model_version TEXT,
        fold_id INTEGER,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(symbol, entry_time, direction)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS model_versions (
        version_id TEXT PRIMARY KEY,
        symbol TEXT NOT NULL,
        created_at TEXT NOT NULL,
        sharpe_ratio REAL,
        win_rate REAL,
        total_trades INTEGER,
        train_bars INTEGER,
        feature_count INTEGER,
        status TEXT DEFAULT 'active',
        notes TEXT
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS model_performance (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        version_id TEXT NOT NULL,
        symbol TEXT NOT NULL,
        date TEXT NOT NULL,
        n_trades INTEGER,
        win_rate REAL,
        avg_pnl REAL,
        max_drawdown REAL,
        FOREIGN KEY(version_id) REFERENCES model_versions(version_id)
    )
    """,
)

_TRADE_INSERT_SQL = """
    INSERT OR IGNORE INTO trades (
        symbol, direction, entry_time, exit_time,
        entry_price, exit_price, pnl_pct, hold_bars,
        exit_reason, confidence, hexagram, upper_gua,
        lower_gua, position_factor, model_version, fold_id
    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
"""


def _trade_params(trade: Dict[str, Any]) -> Tuple[Any, ...]:
    return (
        trade.get("symbol", ""),
        trade.get("direction", 0),
        trade.get("entry_time", ""),
        trade.get("exit_time", ""),
        trade.get("entry_price", 0),
        trade.get("exit_price", 0),
        trade.get("pnl_pct", 0),
        trade.get("hold_bars", 0),
        trade.get("exit_reason", ""),
        trade.get("confidence", 0),
        trade.get("hexagram", ""),
        trade.get("upper_gua", ""),
        trade.get("lower_gua", ""),
        trade.get("position_factor", 1.0),
        trade.get("model_version", ""),
        trade.get("fold_id", 0),
    )


def init_learner_tables(db_path: str, switch: str = "BCRM_LEARNER_STORE_PORT") -> None:
    """建 learner 三表（CREATE IF NOT EXISTS 幂等 DDL）。

    开关打开走 port 分支（_connect_rw）；port 异常回退 legacy 直写。
    legacy 分支为原 TradeDatabase._init_db 内联实现（异常向调用方传播）。
    """
    if _switch(switch):
        try:
            conn = _connect_rw(db_path)
            try:
                for ddl in _LEARNER_DDL:
                    conn.execute(ddl)
                conn.commit()
            finally:
                conn.close()
            return
        except Exception:
            pass  # 回退 legacy 直写（fail-safe 保持久性）
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    for ddl in _LEARNER_DDL:
        cursor.execute(ddl)
    conn.commit()
    conn.close()


def insert_trade(
    db_path: str, trade_data: Dict[str, Any], switch: str = "BCRM_LEARNER_STORE_PORT"
) -> int:
    """插入单条交易（INSERT OR IGNORE），成功返回 lastrowid，失败返回 -1。

    port 分支异常 → rollback 后回退 legacy 直写（INSERT OR IGNORE 幂等）。
    legacy 分支为原 TradeDatabase.add_trade 内联实现。
    """
    params = _trade_params(trade_data)
    if _switch(switch):
        try:
            conn = _connect_rw(db_path)
            try:
                cur = conn.execute(_TRADE_INSERT_SQL, params)
                conn.commit()
                return cur.lastrowid
            except Exception:
                conn.rollback()
                raise
            finally:
                conn.close()
        except Exception:
            pass  # 回退 legacy 直写
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    try:
        cursor.execute(_TRADE_INSERT_SQL, params)
        conn.commit()
        return cursor.lastrowid
    except Exception:
        conn.rollback()
        return -1
    finally:
        conn.close()


def insert_trades_batch(
    db_path: str, trades: List[Dict[str, Any]], switch: str = "BCRM_LEARNER_STORE_PORT"
) -> int:
    """批量插入交易（INSERT OR IGNORE 循环 + 单次 commit），成功返回 len(trades)，失败 0。

    port 分支异常 → rollback（单事务未提交不产生部分行）后回退 legacy 直写。
    legacy 分支为原 TradeDatabase.add_trades_batch 内联实现。
    """
    params_list = [_trade_params(t) for t in trades]
    if _switch(switch):
        try:
            conn = _connect_rw(db_path)
            try:
                for params in params_list:
                    conn.execute(_TRADE_INSERT_SQL, params)
                conn.commit()
                return len(trades)
            except Exception:
                conn.rollback()
                raise
            finally:
                conn.close()
        except Exception:
            pass  # 回退 legacy 直写
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    try:
        for params in params_list:
            cursor.execute(_TRADE_INSERT_SQL, params)
        conn.commit()
        return len(trades)
    except Exception:
        conn.rollback()
        return 0
    finally:
        conn.close()


def upsert_model_version(
    db_path: str,
    version_id: str,
    symbol: str,
    metrics: Dict[str, Any],
    notes: str = "",
    switch: str = "BCRM_LEARNER_STORE_PORT",
) -> bool:
    """保存模型版本（INSERT OR REPLACE），成功 True / 失败 False。

    port 分支异常 → rollback 后回退 legacy 直写（REPLACE 幂等）。
    legacy 分支为原 TradeDatabase.save_model_version 内联实现。
    """
    params = (
        version_id,
        symbol,
        datetime.now().isoformat(),
        metrics.get("sharpe_ratio", 0),
        metrics.get("win_rate", 0),
        metrics.get("total_trades", 0),
        metrics.get("train_bars", 0),
        metrics.get("feature_count", 0),
        "active",
        notes,
    )
    sql = """
        INSERT OR REPLACE INTO model_versions (
            version_id, symbol, created_at, sharpe_ratio,
            win_rate, total_trades, train_bars, feature_count, status, notes
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """
    if _switch(switch):
        try:
            conn = _connect_rw(db_path)
            try:
                conn.execute(sql, params)
                conn.commit()
                return True
            except Exception:
                conn.rollback()
                raise
            finally:
                conn.close()
        except Exception:
            pass  # 回退 legacy 直写
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    try:
        cursor.execute(sql, params)
        conn.commit()
        return True
    except Exception:
        conn.rollback()
        return False
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# 读助手：learner 聚合读（C5 第八批；开关复用 BCRM_LEARNER_STORE_PORT）
# ---------------------------------------------------------------------------

_RECENT_PERF_SQL = """
    SELECT COUNT(*) as n_trades,
           AVG(pnl_pct) as avg_pnl,
           SUM(CASE WHEN pnl_pct > 0 THEN 1 ELSE 0 END) * 100.0 / COUNT(*) as win_rate
    FROM trades WHERE symbol = ?
"""


def fetch_recent_performance(
    db_path: str, symbol: str, switch: str = "BCRM_LEARNER_STORE_PORT"
) -> Dict[str, Any]:
    """learner 聚合读（AVG/SUM 专用 SQL，SqliteReadOnlyPort.query 不可表达）。

    port 分支用 _connect_ro 同 SQL；port 异常回退 legacy 直连。
    legacy 分支为原 TradeDatabase.get_recent_performance 内联实现
    （异常返回 {}，days 参数原样不参与 SQL——保留原行为不修复）。
    """
    if _switch(switch):
        try:
            conn = _connect_ro(db_path, row=False)
            try:
                cur = conn.cursor()
                cur.execute(_RECENT_PERF_SQL, (symbol,))
                row = cur.fetchone()
                if row:
                    columns = [desc[0] for desc in cur.description]
                    return dict(zip(columns, row, strict=True))
                return {}
            finally:
                conn.close()
        except Exception:
            pass  # 回退 legacy 直连
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    try:
        cursor.execute(_RECENT_PERF_SQL, (symbol,))
        row = cursor.fetchone()
        if row:
            columns = [desc[0] for desc in cursor.description]
            return dict(zip(columns, row, strict=True))
        return {}
    except Exception:
        return {}
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# 读写助手：macro_data_fetcher 缓存（C5 第七批；开关 BCRM_MACRO_STORE_PORT）
# ---------------------------------------------------------------------------


def load_cache_dataframe(
    db_path: str, table: str, switch: str = "BCRM_MACRO_STORE_PORT"
) -> Optional[Any]:
    """pd.read_sql 整表（timestamp ASC）；任何失败返回 None（与原 _load_cache 一致）。

    port 分支用 _connect_ro（row=False 兼容 pandas）；port 异常回退 legacy 直连。
    legacy 分支为原 MacroDataFetcher._load_cache 的 DB 触达段内联实现。
    """
    import pandas as pd  # 惰性导入：_store_port 本身不依赖 pandas

    sql = "SELECT * FROM " + table + " ORDER BY timestamp"
    if _switch(switch):
        try:
            conn = _connect_ro(db_path, row=False)
            try:
                return pd.read_sql(sql, conn)
            finally:
                conn.close()
        except Exception:
            pass  # 回退 legacy 直连
    try:
        conn = sqlite3.connect(db_path)
        try:
            return pd.read_sql(sql, conn)
        finally:
            conn.close()
    except Exception:
        return None


def save_cache_dataframe(
    db_path: str, table: str, df: Any, switch: str = "BCRM_MACRO_STORE_PORT"
) -> None:
    """df.to_sql(if_exists="replace") 写缓存；异常向调用方传播（原 _save_cache 仅 warning）。

    port 分支异常回退 legacy 直写（replace = 删表重建，幂等，重放安全）。
    legacy 分支为原 MacroDataFetcher._save_cache 的 DB 触达段内联实现。
    """
    if _switch(switch):
        try:
            conn = _connect_rw(db_path)
            try:
                df.to_sql(table, conn, if_exists="replace", index=False)
            finally:
                conn.close()
            return
        except Exception:
            pass  # 回退 legacy 直写
    conn = sqlite3.connect(db_path)
    try:
        df.to_sql(table, conn, if_exists="replace", index=False)
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# 读写助手：backfill_fma_shadow（C5 第七批；开关 BCRM_BACKFILL_STORE_PORT）
# ---------------------------------------------------------------------------

_REGIME_COLUMNS = (
    "timestamp, symbol, price_close, level_smooth, trend_smooth, "
    "consensus, hmm_state, regime_probs, top3"
)

_SHADOW_INSERT_SQL = """
    INSERT INTO shadow_param_log (
        symbol, timestamp,
        actual_direction, actual_confidence, actual_threshold,
        actual_pnl_pct, actual_win,
        fma_on_allowed, actual_entry_time
    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
"""

_SHADOW_STATS_SQL = """
    SELECT
        COUNT(*) as total,
        COUNT(actual_pnl_pct) as with_pnl,
        SUM(CASE WHEN fma_on_allowed=1 THEN 1 ELSE 0 END) as fma_on,
        SUM(CASE WHEN fma_on_allowed=1 AND actual_pnl_pct IS NOT NULL THEN 1 ELSE 0 END) as fma_on_with_pnl,
        SUM(CASE WHEN actual_pnl_pct >= 0 THEN 1 ELSE 0 END) as wins,
        SUM(CASE WHEN fma_on_allowed=1 AND actual_pnl_pct >= 0 THEN 1 ELSE 0 END) as fma_on_wins
    FROM shadow_param_log
    WHERE actual_direction IS NOT NULL AND actual_direction != 'HOLD'
      AND actual_confidence IS NOT NULL AND actual_threshold IS NOT NULL
"""

_SHADOW_PER_SYMBOL_SQL = """
    SELECT symbol,
           COUNT(*) as total,
           SUM(CASE WHEN fma_on_allowed=1 THEN 1 ELSE 0 END) as fma_on,
           SUM(CASE WHEN actual_pnl_pct >= 0 THEN 1 ELSE 0 END) as wins
    FROM shadow_param_log
    WHERE actual_direction IS NOT NULL AND actual_direction != 'HOLD'
    GROUP BY symbol ORDER BY symbol
"""

_SHADOW_EVAL_SQL = """
    SELECT actual_direction, actual_confidence, actual_threshold,
           actual_pnl_pct, actual_win, fma_on_allowed
    FROM shadow_param_log
    WHERE actual_direction IS NOT NULL AND actual_direction != 'HOLD'
      AND actual_confidence IS NOT NULL AND actual_threshold IS NOT NULL
"""


def fetch_regime_rows(
    db_path: str, symbol: str = "BTCUSDT", switch: str = "BCRM_BACKFILL_STORE_PORT"
) -> List[Dict[str, Any]]:
    """读 regime_state_daily 全量（timestamp ASC），返回 dict 列表。

    port 分支走 SqliteReadOnlyPort.query（等值过滤可表达）；
    port 异常回退 legacy 直连（原 fetch_btc_regime_data 的 DB 触达段）。
    """
    if _switch(switch):
        try:
            port = SqliteReadOnlyPort(db_path)
            return (
                port.query(
                    "regime_state_daily",
                    filters={"symbol": symbol},
                    columns=_REGIME_COLUMNS,
                    limit=1000000,
                    order_by="timestamp ASC",
                ).get("rows")
                or []
            )
        except Exception:
            pass  # 回退 legacy 直连
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    rows = cur.execute(
        "SELECT " + _REGIME_COLUMNS + " FROM regime_state_daily "
        "WHERE symbol = ? ORDER BY timestamp ASC",
        (symbol,),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def purge_and_insert_shadow_rows(
    db_path: str, records: List[Dict[str, Any]], switch: str = "BCRM_BACKFILL_STORE_PORT"
) -> int:
    """清空 shadow_param_log 并批量插入，返回清除前旧记录数。

    port 分支：COUNT+DELETE+INSERT 单事务原子提交（成功路径终态与 legacy
    两段提交一致；任何异常 rollback 表保持原状，回退重放无重复行风险）。
    legacy 分支为原 backfill_fma_shadow 主流程内联实现
    （COUNT→DELETE→commit→循环 INSERT→commit）。
    """
    rows = [
        (
            r["symbol"],
            r["timestamp"],
            r["actual_direction"],
            r["actual_confidence"],
            r["actual_threshold"],
            r["actual_pnl_pct"],
            r["actual_win"],
            r["fma_on_allowed"],
            r["actual_entry_time"],
        )
        for r in records
    ]
    if _switch(switch):
        try:
            conn = _connect_rw(db_path)
            try:
                old_count = conn.execute("SELECT COUNT(*) FROM shadow_param_log").fetchone()[0]
                conn.execute("DELETE FROM shadow_param_log")
                for params in rows:
                    conn.execute(_SHADOW_INSERT_SQL, params)
                conn.commit()
                return old_count
            except Exception:
                conn.rollback()
                raise
            finally:
                conn.close()
        except Exception:
            pass  # port 单事务已 rollback，表保持原状，回退 legacy 重放安全
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) as cnt FROM shadow_param_log")
    old_count = cur.fetchone()["cnt"]
    cur.execute("DELETE FROM shadow_param_log")
    conn.commit()
    for params in rows:
        cur.execute(_SHADOW_INSERT_SQL, params)
    conn.commit()
    conn.close()
    return old_count


def fetch_shadow_stats(db_path: str, switch: str = "BCRM_BACKFILL_STORE_PORT") -> Dict[str, Any]:
    """shadow_param_log 验证统计 + 按币种聚合（一次连接两查询，同原主流程）。

    返回 {"stats": dict, "per_symbol": [dict, ...]}。
    聚合 SQL（COUNT/SUM/CASE/GROUP BY）超出 SqliteReadOnlyPort 表达力，
    port 分支用 _connect_ro 同 SQL；port 异常回退 legacy 直连。
    """
    if _switch(switch):
        try:
            conn = _connect_ro(db_path)
            try:
                stats = conn.execute(_SHADOW_STATS_SQL).fetchone()
                per_symbol = conn.execute(_SHADOW_PER_SYMBOL_SQL).fetchall()
            finally:
                conn.close()
            return {
                "stats": dict(stats) if stats is not None else {},
                "per_symbol": [dict(r) for r in per_symbol],
            }
        except Exception:
            pass  # 回退 legacy 直连
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    stats = cur.execute(_SHADOW_STATS_SQL).fetchone()
    per_symbol = cur.execute(_SHADOW_PER_SYMBOL_SQL).fetchall()
    conn.close()
    return {
        "stats": dict(stats) if stats is not None else {},
        "per_symbol": [dict(r) for r in per_symbol],
    }


def fetch_shadow_eval_records(
    db_path: str, switch: str = "BCRM_BACKFILL_STORE_PORT"
) -> List[Dict[str, Any]]:
    """读 shadow_param_log 评估记录（复杂 WHERE 超 port 表达力）。

    port 分支用 _connect_ro 同 SQL；port 异常回退 legacy 直连。
    bool 转换（fma_on_allowed/actual_win）由调用方完成，同原主流程。
    """
    if _switch(switch):
        try:
            conn = _connect_ro(db_path)
            try:
                rows = conn.execute(_SHADOW_EVAL_SQL).fetchall()
            finally:
                conn.close()
            return [dict(r) for r in rows]
        except Exception:
            pass  # 回退 legacy 直连
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    rows = cur.execute(_SHADOW_EVAL_SQL).fetchall()
    conn.close()
    return [dict(r) for r in rows]


__all__ = [
    "SqliteReadOnlyPort",
    "fetch_records_by_sources",
    "fetch_table_rows",
    "init_learner_tables",
    "insert_trade",
    "insert_trades_batch",
    "upsert_model_version",
    "load_cache_dataframe",
    "save_cache_dataframe",
    "fetch_regime_rows",
    "purge_and_insert_shadow_rows",
    "fetch_shadow_stats",
    "fetch_shadow_eval_records",
    "connect_persistent",
    "connect_autocommit",
    "fetch_recent_performance",
]
