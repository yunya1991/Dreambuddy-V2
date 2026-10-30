# -*- coding: utf-8 -*-
"""force_vector 读路径 Store port 收编（C5 第一批，只读先行）。

原状：4 个文件各自 sqlite3 直连 18-数据获取中心 data_center.db 的 records 表（纯只读）。
本模块将直连集中到一处，读路径按文件粒度开关路由：
  FV_STORE_PORT_VALUATION=1 → coin_fundamental_valuation_query 读走 Store port
  FV_STORE_PORT_CATALYST=1   → follow_up_catalyst 读走 Store port
  FV_STORE_PORT_WATERLINE=1  → sector_waterline 读走 Store port
  FV_STORE_PORT_TIMELINE=1   → coin_fundamental_event_timeline 读走 Store port
  默认（未设置）→ legacy 直连，SQL 与返回行为与原实现零变化。

RecordsStorePort 结构化实现 dreambuddy_l0.ports.store.StorePort 协议
（read/write/query/health），面向 data_center.db records 表；本批只读使用（write 未开放）。
"""
from __future__ import annotations

import os
import sqlite3
from typing import Any, Dict, List, Optional, Tuple

_TRUTHY = ("1", "true", "on")


def _switch(name: str) -> bool:
    return os.environ.get("FV_STORE_PORT_" + name, "").strip().lower() in _TRUTHY


class RecordsStorePort:
    """data_center.db records 表的 StorePort 适配器（C5 第一批，只读）。

    结构化实现 dreambuddy_l0 StorePort 协议：
      read(table, key=...)            → {"row": dict|None, "error_code": str}
      write(...)                      → 本批只读收编，未开放
      query(table, filters=..., ...)  → {"rows": [dict, ...], "count": int, "error_code": str}
      health()                        → {"ok": bool, ...}
    query 额外支持 order_by（默认 "id ASC"，协议调用方不传时行为确定）。
    """

    def __init__(self, db_path: str):
        self._db_path = db_path

    def _connect(self):
        conn = sqlite3.connect(self._db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def read(self, table: str, *, key: str, cursor: Optional[str] = None,
             limit: int = 100) -> Dict[str, Any]:
        if table != "records":
            return {"row": None, "error_code": "unknown_table"}
        conn = self._connect()
        try:
            row = conn.execute(
                "SELECT * FROM records WHERE id = ?", (key,)
            ).fetchone()
        finally:
            conn.close()
        if row is None:
            return {"row": None, "error_code": "not_found"}
        return {"row": dict(row), "error_code": ""}

    def write(self, table: str, *, data: Dict[str, Any],
              idempotency_key: str = "") -> bool:
        raise NotImplementedError("C5 第一批只读收编：write 未开放")

    def query(self, table: str, *, filters: Optional[Dict[str, Any]] = None,
              cursor: Optional[str] = None, limit: int = 100,
              order_by: str = "id ASC") -> Dict[str, Any]:
        if table != "records":
            return {"rows": [], "count": 0, "error_code": "unknown_table"}
        where, params = [], []
        for col in sorted(filters or {}):
            where.append(col + " = ?")
            params.append(filters[col])
        sql = "SELECT * FROM records"
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

def fetch_chart_timeseries_json(coin_id: str, db_path: str,
                                switch: str = "CHART") -> Optional[str]:
    """取 chart_{coin_id} 最新一条 timeseries JSON 字符串；无数据返回 None。

    供 coin_fundamental_valuation_query / follow_up_catalyst / sector_waterline 使用
    （各传自己的 switch 名，实现文件粒度开关）。
    开关打开 → 走 RecordsStorePort；默认 legacy 直连（原 SQL 原样保留）。
    """
    if _switch(switch):
        try:
            port = RecordsStorePort(db_path)
            r = port.query(
                "records",
                filters={"source": "coingecko", "category": "coin",
                         "sub_category": "chart_" + coin_id},
                limit=1,
                order_by="timestamp DESC",
            )
            rows = r.get("rows") or []
            if not rows:
                return None
            return rows[0].get("timeseries") or None
        except Exception:
            return None  # FAIL-OPEN：与 legacy 路径异常时调用方兜底语义一致
    conn = sqlite3.connect(db_path)
    try:
        row = conn.execute(
            "SELECT timeseries FROM records "
            "WHERE source='coingecko' AND category='coin' "
            "AND sub_category=? "
            "ORDER BY timestamp DESC LIMIT 1",
            ("chart_" + coin_id,),
        ).fetchone()
        return row[0] if row else None
    finally:
        conn.close()


def fetch_newsflash_rows(db_path: str,
                         switch: str = "NEWSFLASH") -> List[Tuple[str, str, str]]:
    """取 odaily_newsflash 全量 (metrics, events, raw) 元组列表。

    供 coin_fundamental_event_timeline 使用。
    开关打开 → 走 RecordsStorePort；默认 legacy 直连（原 SQL 原样保留）。
    """
    if _switch(switch):
        try:
            port = RecordsStorePort(db_path)
            r = port.query(
                "records",
                filters={"source": "odaily_newsflash", "category": "news"},
                limit=1000000,
            )
            return [
                (row.get("metrics") or "", row.get("events") or "",
                 row.get("raw") or "")
                for row in (r.get("rows") or [])
            ]
        except Exception:
            return []  # FAIL-OPEN
    conn = sqlite3.connect(db_path)
    try:
        return conn.execute(
            "SELECT metrics, events, raw FROM records "
            "WHERE source='odaily_newsflash' AND category='news'"
        ).fetchall()
    finally:
        conn.close()


__all__ = ["RecordsStorePort", "fetch_chart_timeseries_json", "fetch_newsflash_rows"]
