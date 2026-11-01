# -*- coding: utf-8 -*-
"""bcrm2 读路径 Store port 收编（C5 第四批，只读先行）。

原状：
  - `macro_data_fetcher.py` 4 处直连：2 处只读 data_center.db `records`，2 处写入（建表/补写）
  - `incremental_learner.py` 7 处直连：3 处只读 bcrm 学习库，4 处写入（建表/INSERT/commit）

本批按 SPEC-C **只读查询先行、写路径暂缓**：只收编 4 处只读，写路径原样保留。
读路径按文件粒度开关路由：
  BCRM_MACRO_STORE_PORT=1   → macro_data_fetcher 两处只读走 Store port
  BCRM_LEARNER_STORE_PORT=1 → incremental_learner 两处只读走 Store port
  默认（未设置）→ legacy 直连，SQL 与返回行为与原实现零变化。

SqliteReadOnlyPort 结构化实现 dreambuddy_l0.ports.store.StorePort 协议
（read/query/health），连接一律 `mode=ro`；本批 write 未开放。
"""

from __future__ import annotations

import os
import sqlite3
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


__all__ = ["SqliteReadOnlyPort", "fetch_records_by_sources", "fetch_table_rows"]
