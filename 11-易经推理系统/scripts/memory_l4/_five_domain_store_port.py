# -*- coding: utf-8 -*-
"""five_domain_sqlite_reader 读路径 Store port 收编（C5 第三批，只读先行）。

原状：`five_domain_sqlite_reader.py` 两处 sqlite3 直连 `18-数据获取中心/data_center.db`
records 表（只为读，`mode=ro`）。本模块把直连集中到一处，读路径按文件粒度开关路由：
  FD_STORE_PORT=1 → 两处读走 Store port
  默认（未设置）→ legacy 直连，SQL 与返回行为与原实现零变化。

RecordsStorePort 结构化实现 dreambuddy_l0.ports.store.StorePort 协议
（read/write/query/health），面向 `data_center.db` records 表；本批只读（write 未开放）。
"""

from __future__ import annotations

import os
import sqlite3
from typing import Any, Dict, List, Optional, Sequence, Tuple

_TRUTHY = ("1", "true", "on")


def _switch(name: str = "FD_STORE_PORT") -> bool:
    return os.environ.get(name, "").strip().lower() in _TRUTHY


class RecordsStorePort:
    """data_center.db records 表的 StorePort 适配器（C5 第三批，只读）。

      read(table, key=...)            → {"row": dict|None, "error_code": str}
      write(...)                      → 本批只读收编，未开放
      query(table, filters=..., ...)  → {"rows": [dict, ...], "count": int, "error_code": str}
      health()                        → {"ok": bool, ...}
    query 额外支持 order_by（默认 "id DESC"）与裸 SQL 过滤条件 sql_where（仅供
    legacy 语义等价场景使用，如 id 区间；其余调用方用 filters 等值匹配）。
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
        if table != "records":
            return {"row": None, "error_code": "unknown_table"}
        conn = self._connect()
        try:
            row = conn.execute("SELECT * FROM records WHERE id = ?", (key,)).fetchone()
        finally:
            conn.close()
        if row is None:
            return {"row": None, "error_code": "not_found"}
        return {"row": dict(row), "error_code": ""}

    def write(self, table: str, *, data: Dict[str, Any], idempotency_key: str = "") -> bool:
        raise NotImplementedError("C5 第三批只读收编：write 未开放")

    def query(
        self,
        table: str,
        *,
        filters: Optional[Dict[str, Any]] = None,
        cursor: Optional[str] = None,
        limit: int = 100,
        order_by: str = "id DESC",
        columns: str = "*",
        sql_where: str = "",
        sql_params: Optional[Sequence[Any]] = None,
    ) -> Dict[str, Any]:
        if table != "records":
            return {"rows": [], "count": 0, "error_code": "unknown_table"}
        where, params = [], []
        for col in sorted(filters or {}):
            where.append(col + " = ?")
            params.append(filters[col])
        if sql_where:
            where.append("(" + sql_where + ")")
            params.extend(list(sql_params or ()))
        sql = "SELECT " + columns + " FROM records"
        if where:
            sql += " WHERE " + " AND ".join(where)
        sql += " ORDER BY " + order_by + " LIMIT ?"
        params.append(int(limit))
        conn = self._connect()
        try:
            rows = conn.execute(sql, params).fetchall()
        finally:
            conn.close()
        return {"rows": [dict(r) for r in rows], "count": len(rows), "error_code": ""}

    def health(self) -> Dict[str, Any]:
        try:
            conn = self._connect()
            try:
                n = conn.execute("SELECT COUNT(*) FROM records").fetchone()[0]
            finally:
                conn.close()
            return {"ok": True, "table": "records", "count": int(n)}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}


# ---------------------------------------------------------------------------
# 读取助手（文件粒度开关路由；默认 legacy 直连，行为零变化）
# ---------------------------------------------------------------------------

_MACRO_COLUMNS = "source, sub_category, metrics, raw, timestamp, id"


def fetch_rows_by_sources(
    db_path: str, sources: Sequence[str], switch: str = "FD_STORE_PORT"
) -> List[Any]:
    """按 source 白名单取 records 行（id DESC 全序）；无数据返回 []。

    供 read_macro_from_sqlite 使用。开关打开 → 走 RecordsStorePort；
    默认 legacy 直连（原 SQL 原样保留）。
    """
    if _switch(switch):
        try:
            port = RecordsStorePort(db_path)
            merged: List[Dict[str, Any]] = []
            for src in sources:
                r = port.query(
                    "records",
                    filters={"source": src},
                    columns=_MACRO_COLUMNS,
                    limit=1000000,
                    order_by="id DESC",
                )
                merged.extend(r.get("rows") or [])
            merged.sort(key=lambda row: row.get("id") or 0, reverse=True)
            return merged
        except Exception:
            return []  # FAIL-OPEN：与 legacy 异常路径一致（调用方返回部分 dict）
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        return conn.execute(
            "SELECT "
            + _MACRO_COLUMNS
            + " FROM records WHERE source IN ("
            + ",".join("?" * len(sources))
            + ") ORDER BY id DESC",
            tuple(sources),
        ).fetchall()
    finally:
        conn.close()


def fetch_top10_inflow_batch(
    db_path: str, source: str, sub_category: str, window: int = 50, switch: str = "FD_STORE_PORT"
) -> Tuple[Optional[Any], List[Any]]:
    """取 top10_inflow_di 同批次行：返回 (最新一行, 区间内行列表)，无数据返回 (None, [])。

    供 read_macro_from_sqlite 地维度汇总使用。开关打开 → 走 RecordsStorePort；
    默认 legacy 直连（原两条 SQL 原样保留，含 id >= top-50 AND id <= top 区间语义）。
    """
    if _switch(switch):
        try:
            port = RecordsStorePort(db_path)
            top_rows = (
                port.query(
                    "records",
                    filters={"source": source, "sub_category": sub_category},
                    columns="id, timestamp",
                    limit=1,
                    order_by="id DESC",
                ).get("rows")
                or []
            )
            if not top_rows:
                return None, []
            top = top_rows[0]
            min_id = max(0, int(top["id"]) - window)
            rows = (
                port.query(
                    "records",
                    filters={"source": source, "sub_category": sub_category},
                    columns="metrics, id",
                    limit=window + 1,
                    order_by="id DESC",
                ).get("rows")
                or []
            )
            rows = [r for r in rows if min_id <= int(r["id"]) <= int(top["id"])]
            return top, rows
        except Exception:
            return None, []  # FAIL-OPEN
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        top = conn.execute(
            "SELECT id, timestamp FROM records "
            "WHERE source=? AND sub_category=? ORDER BY id DESC LIMIT 1",
            (source, sub_category),
        ).fetchone()
        if not top:
            return None, []
        min_id = max(0, int(top["id"]) - window)
        rows = conn.execute(
            "SELECT metrics, id FROM records "
            "WHERE source=? AND sub_category=? AND id >= ? AND id <= ? "
            "ORDER BY id DESC",
            (source, sub_category, min_id, int(top["id"])),
        ).fetchall()
        return top, rows
    finally:
        conn.close()


def fetch_distinct_dates(
    db_path: str, sources: Sequence[str], switch: str = "FD_IC_STORE_PORT"
) -> List[str]:
    """DISTINCT date(timestamp) 升序日期列表（five_domain_ic_analysis._get_daily_snapshots）。

    开关打开 → 走 RecordsStorePort（FAIL-OPEN 返回 []）；默认 legacy 直连
    （原 SQL 原样保留，异常上抛，由调用方 try 兜底）。
    """
    if _switch(switch):
        try:
            port = RecordsStorePort(db_path)
            r = port.query(
                "records",
                columns="DISTINCT date(timestamp) AS d",
                sql_where="source IN (" + ",".join("?" * len(sources)) + ")",
                sql_params=tuple(sources),
                order_by="d ASC",
                limit=1000000,
            )
            return [row["d"] for row in (r.get("rows") or []) if row.get("d")]
        except Exception:
            return []  # FAIL-OPEN
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            "SELECT DISTINCT date(timestamp) as d FROM records WHERE source IN ("
            + ",".join("?" * len(sources))
            + ") ORDER BY d",
            tuple(sources),
        ).fetchall()
        return [r["d"] for r in rows]
    finally:
        conn.close()


def fetch_rows_by_sources_until(
    db_path: str,
    sources: Sequence[str],
    max_ts: str,
    switch: str = "FD_IC_STORE_PORT",
    use_date_func: bool = True,
) -> List[Any]:
    """主读取 + 时间上界过滤（ic_analysis._read_macro_for_date / backtest.build_macro_snapshot_for_date）。

    use_date_func=True  → date(timestamp) <= ?（ic_analysis 形态，max_ts 为日期串）
    use_date_func=False → timestamp <= ?（backtest 形态，max_ts 为 "YYYY-MM-DDT23:59:59"）
    开关打开 → 走 RecordsStorePort（FAIL-OPEN 返回 []）；默认 legacy 直连（异常上抛）。
    """
    ts_filter = "date(timestamp) <= ?" if use_date_func else "timestamp <= ?"
    if _switch(switch):
        try:
            port = RecordsStorePort(db_path)
            r = port.query(
                "records",
                columns=_MACRO_COLUMNS,
                sql_where="source IN (" + ",".join("?" * len(sources)) + ") AND " + ts_filter,
                sql_params=tuple(sources) + (max_ts,),
                order_by="id DESC",
                limit=1000000,
            )
            return r.get("rows") or []
        except Exception:
            return []  # FAIL-OPEN
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        return conn.execute(
            "SELECT "
            + _MACRO_COLUMNS
            + " FROM records WHERE source IN ("
            + ",".join("?" * len(sources))
            + ") AND "
            + ts_filter
            + " ORDER BY id DESC",
            tuple(sources) + (max_ts,),
        ).fetchall()
    finally:
        conn.close()


def fetch_latest_row(
    db_path: str,
    source: str,
    sub_category: str,
    columns: str = "*",
    switch: str = "FD_IC_STORE_PORT",
) -> Optional[Dict[str, Any]]:
    """(source, sub_category) 最新 1 行指定列（stablecoin_hist timeseries / overview raw 等）。

    开关打开 → 走 RecordsStorePort（FAIL-OPEN 返回 None）；默认 legacy 直连（异常上抛）。
    """
    if _switch(switch):
        try:
            port = RecordsStorePort(db_path)
            rows = (
                port.query(
                    "records",
                    filters={"source": source, "sub_category": sub_category},
                    columns=columns,
                    limit=1,
                    order_by="id DESC",
                ).get("rows")
                or []
            )
            return rows[0] if rows else None
        except Exception:
            return None  # FAIL-OPEN
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        row = conn.execute(
            "SELECT "
            + columns
            + " FROM records WHERE source=? AND sub_category=? ORDER BY id DESC LIMIT 1",
            (source, sub_category),
        ).fetchone()
        return row
    finally:
        conn.close()


def fetch_latest_rows_for_pairs(
    db_path: str,
    pairs: Sequence[Tuple[str, str]],
    columns: str = "metrics, raw",
    switch: str = "FD_BT5_STORE_PORT",
) -> Dict[Tuple[str, str], Any]:
    """批量取 (source, sub_category) 最新行（backtest slow_latest 慢变量缓存，共享单连接）。

    返回 {(src, sub): row}，仅含存在的行。开关打开 → 走 RecordsStorePort
    （FAIL-OPEN 返回 {}）；默认 legacy 直连（异常上抛）。
    """
    result: Dict[Tuple[str, str], Any] = {}
    if _switch(switch):
        try:
            port = RecordsStorePort(db_path)
            for src, sub in pairs:
                rows = (
                    port.query(
                        "records",
                        filters={"source": src, "sub_category": sub},
                        columns=columns,
                        limit=1,
                        order_by="id DESC",
                    ).get("rows")
                    or []
                )
                if rows:
                    result[(src, sub)] = rows[0]
            return result
        except Exception:
            return {}  # FAIL-OPEN
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        cur = conn.cursor()
        for src, sub in pairs:
            r = cur.execute(
                "SELECT "
                + columns
                + " FROM records WHERE source=? AND sub_category=? ORDER BY id DESC LIMIT 1",
                (src, sub),
            ).fetchone()
            if r:
                result[(src, sub)] = r
        return result
    finally:
        conn.close()


def fetch_top10_inflow_until(
    db_path: str,
    max_ts: str,
    switch: str = "FD_IC_STORE_PORT",
    use_date_func: bool = True,
    window: int = 50,
) -> Tuple[Optional[Any], List[Any]]:
    """top10_inflow_di 带时间上界的同批次行：(最新行, 区间内行列表)，无数据 (None, [])。

    use_date_func=True → date(timestamp) <= ?（ic_analysis）；False → timestamp <= ?（backtest）。
    开关打开 → 走 RecordsStorePort（FAIL-OPEN 返回 (None, [])）；默认 legacy 直连（异常上抛）。
    """
    ts_filter = "date(timestamp) <= ?" if use_date_func else "timestamp <= ?"
    if _switch(switch):
        try:
            port = RecordsStorePort(db_path)
            top_rows = (
                port.query(
                    "records",
                    filters={"source": "theblockbeats_dataview", "sub_category": "top10_inflow_di"},
                    columns="id",
                    sql_where=ts_filter,
                    sql_params=(max_ts,),
                    limit=1,
                    order_by="id DESC",
                ).get("rows")
                or []
            )
            if not top_rows:
                return None, []
            top = top_rows[0]
            min_id = max(0, int(top["id"]) - window)
            rows = (
                port.query(
                    "records",
                    filters={"source": "theblockbeats_dataview", "sub_category": "top10_inflow_di"},
                    columns="metrics",
                    sql_where="id >= ? AND id <= ?",
                    sql_params=(min_id, int(top["id"])),
                    limit=window + 1,
                    order_by="id DESC",
                ).get("rows")
                or []
            )
            return top, rows
        except Exception:
            return None, []  # FAIL-OPEN
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        top = conn.execute(
            "SELECT id FROM records WHERE source='theblockbeats_dataview' "
            "AND sub_category='top10_inflow_di' AND " + ts_filter + " "
            "ORDER BY id DESC LIMIT 1",
            (max_ts,),
        ).fetchone()
        if not top:
            return None, []
        rows = conn.execute(
            "SELECT metrics FROM records WHERE source='theblockbeats_dataview' "
            "AND sub_category='top10_inflow_di' AND id >= ? AND id <= ? ORDER BY id DESC",
            (max(0, int(top["id"]) - window), int(top["id"])),
        ).fetchall()
        return top, rows
    finally:
        conn.close()


__all__ = [
    "RecordsStorePort",
    "fetch_rows_by_sources",
    "fetch_top10_inflow_batch",
    "fetch_distinct_dates",
    "fetch_rows_by_sources_until",
    "fetch_latest_row",
    "fetch_latest_rows_for_pairs",
    "fetch_top10_inflow_until",
]
