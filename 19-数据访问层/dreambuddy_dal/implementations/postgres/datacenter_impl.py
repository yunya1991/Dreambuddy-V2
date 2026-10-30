# -*- coding: utf-8 -*-
"""dreambuddy_dal PG data_center 查询实现（C4b：dc_pg 收编）。

能力来源：39-金融语义蒸馏系统/scripts/dc_pg.py（原直连实现），
本模块为其 DAL 落地，语义与返回结构 100% 对齐：
  - fetch_records(sub_category_like, limit, order_desc) → [{id, sub_category, timestamp, metrics}]
  - fetch_latest(sub_category) → dict | None
  - fetch_max_record_id() → int（异常 0）
  - fetch_latest_by_source(source, sub_category) → {source, category, sub_category, timestamp, metrics} | None
  - fetch_source_groups(limit) → [{source, category, sub_category, count}]
  - fetch_records_since(sub_category_like, since_id, limit) → 升序列表

FAIL-OPEN：PostgreSQL 不可达或异常时返回空结果（[]/None/0），不抛异常。

连接：data_center 库（容器 dreambuddy-pg）。
DSN 发现（优先级由高到低）：
  1. DAL_DC_PG_URL 环境变量（完整 DSN）
  2. DATA_CENTER_PG_HOST/PORT/USER/PASSWORD/DB 组装（密码 fallback：18 中心 .env 提取，与原 dc_pg 一致）
"""
from __future__ import annotations

import json
import os
import re
from typing import Any, Dict, List, Optional

_18_ENV = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(
        os.path.dirname(os.path.abspath(__file__)))))),
    "7-产物中台", "系统研究索引体系", ".env",
)


def _discover_password() -> str:
    """密码发现：环境变量优先，否则从 18 中心 .env 提取（与原 dc_pg 一致）。"""
    pwd = os.environ.get("DATA_CENTER_PG_PASSWORD", "")
    if pwd:
        return pwd
    try:
        with open(_18_ENV, "r", encoding="utf-8") as f:
            for line in f:
                m = re.search(r"postgresql://[^:\s]+:([^@\s]+)@", line)
                if m:
                    return m.group(1)
    except Exception:
        pass
    # fallback: /etc/dreambuddy-pg.env 的 DATA_CENTER_PG_PASSWORD（18 中心 .env 缺失时）
    try:
        with open("/etc/dreambuddy-dal.env", "r", encoding="utf-8") as f:
            for line in f:
                if line.startswith("DATA_CENTER_PG_PASSWORD="):
                    return line.split("=", 1)[1].strip()
    except Exception:
        pass
    return ""


def _connect():
    import psycopg2
    url = os.environ.get("DAL_DC_PG_URL", "")
    if url:
        return psycopg2.connect(url, connect_timeout=10)
    return psycopg2.connect(
        host=os.environ.get("DATA_CENTER_PG_HOST", "127.0.0.1"),
        port=int(os.environ.get("DATA_CENTER_PG_PORT", "5432")),
        user=os.environ.get("DATA_CENTER_PG_USER", "dreambuddy"),
        password=_discover_password(),
        dbname=os.environ.get("DATA_CENTER_PG_DB", "data_center"),
        connect_timeout=10,
    )


def _parse_metrics(metrics: Any) -> Dict[str, Any]:
    if isinstance(metrics, str):
        try:
            metrics = json.loads(metrics)
        except Exception:
            metrics = {}
    return metrics or {}


def _iso(ts: Any) -> str:
    return ts.isoformat() if hasattr(ts, "isoformat") else str(ts)


class DataCenterQueries:
    """data_center 库 records 表只读查询（FAIL-OPEN）。"""

    def fetch_records(self, sub_category_like: str, limit: int = 500,
                      order_desc: bool = True) -> List[Dict[str, Any]]:
        try:
            conn = _connect()
            cur = conn.cursor()
            order = "DESC" if order_desc else "ASC"
            cur.execute(
                "SELECT id, sub_category, timestamp, metrics FROM records "
                "WHERE sub_category LIKE %s ORDER BY id " + order + " LIMIT %s",
                (sub_category_like, limit),
            )
            rows = cur.fetchall()
            conn.close()
            return [
                {"id": rid, "sub_category": sub_cat, "timestamp": _iso(ts),
                 "metrics": _parse_metrics(metrics)}
                for rid, sub_cat, ts, metrics in rows
            ]
        except Exception:
            return []

    def fetch_latest(self, sub_category: str) -> Optional[Dict[str, Any]]:
        rows = self.fetch_records(sub_category, limit=1, order_desc=True)
        return rows[0] if rows else None

    def fetch_max_record_id(self) -> int:
        try:
            conn = _connect()
            cur = conn.cursor()
            cur.execute("SELECT COALESCE(MAX(id), 0) FROM records")
            val = cur.fetchone()[0]
            conn.close()
            return int(val)
        except Exception:
            return 0

    def fetch_latest_by_source(self, source: str,
                              sub_category: Optional[str] = None) -> Optional[Dict[str, Any]]:
        try:
            conn = _connect()
            cur = conn.cursor()
            if sub_category:
                cur.execute(
                    "SELECT source, category, sub_category, timestamp, metrics FROM records "
                    "WHERE source = %s AND sub_category = %s ORDER BY id DESC LIMIT 1",
                    (source, sub_category),
                )
            else:
                cur.execute(
                    "SELECT source, category, sub_category, timestamp, metrics FROM records "
                    "WHERE source = %s ORDER BY id DESC LIMIT 1",
                    (source,),
                )
            row = cur.fetchone()
            conn.close()
            if not row:
                return None
            return {
                "source": row[0], "category": row[1], "sub_category": row[2],
                "timestamp": _iso(row[3]), "metrics": _parse_metrics(row[4]),
            }
        except Exception:
            return None

    def fetch_source_groups(self, limit: int = 60) -> List[Dict[str, Any]]:
        try:
            conn = _connect()
            cur = conn.cursor()
            cur.execute(
                "SELECT source, category, sub_category, COUNT(*) FROM records "
                "GROUP BY source, category, sub_category ORDER BY 4 DESC LIMIT %s",
                (limit,),
            )
            rows = cur.fetchall()
            conn.close()
            return [
                {"source": r[0], "category": r[1], "sub_category": r[2], "count": int(r[3])}
                for r in rows
            ]
        except Exception:
            return []

    def fetch_records_since(self, sub_category_like: str, since_id: int,
                           limit: int = 5000) -> List[Dict[str, Any]]:
        try:
            conn = _connect()
            cur = conn.cursor()
            cur.execute(
                "SELECT id, sub_category, timestamp, metrics FROM records "
                "WHERE sub_category LIKE %s AND id > %s ORDER BY id ASC LIMIT %s",
                (sub_category_like, since_id, limit),
            )
            rows = cur.fetchall()
            conn.close()
            return [
                {"id": rid, "sub_category": sub_cat, "timestamp": _iso(ts),
                 "metrics": _parse_metrics(metrics)}
                for rid, sub_cat, ts, metrics in rows
            ]
        except Exception:
            return []


__all__ = ["DataCenterQueries"]
