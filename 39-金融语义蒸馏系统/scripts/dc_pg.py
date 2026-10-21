# -*- coding: utf-8 -*-
"""39-金融语义蒸馏系统 · PostgreSQL 查询辅助模块

18 中心已从 SQLite 迁移至 PostgreSQL（38-数据库管理系统 SPEC 方案 4）：
  - 容器: dreambuddy-pg (127.0.0.1:5432)
  - 库: data_center（records/metrics/quality_issues/alerts 四表）
  - 认证: DATA_CENTER_PG_PASSWORD 环境变量，否则从 18 中心 .env 提取

本模块为 39/34/前端各脚本提供统一查询接口，替代原 sqlite3 直连：
  - fetch_records(sub_category_like, limit, order_desc): 查询 records
  - fetch_latest(sub_category): 取某 sub_category 最新一条
  - fetch_max_record_id(): 取 records 最大 id（原子事件断点续扫用）

FAIL-OPEN: PostgreSQL 不可达时返回空结果，不抛异常。
"""
import json
import os
import re

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_REPO = os.path.dirname(os.path.dirname(_THIS_DIR))
# 密码发现路径与 18 中心 sink_postgres 保持一致（7-产物中台 .env）
_18_ENV = os.path.join(_REPO, "7-产物中台", "系统研究索引体系", ".env")


def _discover_password():
    """密码发现：环境变量优先，否则从 18 中心 .env 提取（postgresql://user:pwd@host）。"""
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
    return ""


def _connect():
    import psycopg2
    return psycopg2.connect(
        host=os.environ.get("DATA_CENTER_PG_HOST", "127.0.0.1"),
        port=int(os.environ.get("DATA_CENTER_PG_PORT", "5432")),
        user=os.environ.get("DATA_CENTER_PG_USER", "dreambuddy"),
        password=_discover_password(),
        dbname=os.environ.get("DATA_CENTER_PG_DB", "data_center"),
        connect_timeout=10,
    )


def fetch_records(sub_category_like, limit=500, order_desc=True):
    """按 sub_category 模式查询 records，返回 [{id, sub_category, timestamp, metrics}]。
    metrics 为已解析的 dict（PostgreSQL jsonb → dict）。FAIL-OPEN: 异常返回 []。
    """
    try:
        conn = _connect()
        cur = conn.cursor()
        order = "DESC" if order_desc else "ASC"
        cur.execute(
            f"SELECT id, sub_category, timestamp, metrics FROM records "
            f"WHERE sub_category LIKE %s ORDER BY id {order} LIMIT %s",
            (sub_category_like, limit),
        )
        rows = cur.fetchall()
        conn.close()
        out = []
        for rid, sub_cat, ts, metrics in rows:
            if isinstance(metrics, str):
                try:
                    metrics = json.loads(metrics)
                except Exception:
                    metrics = {}
            out.append({
                "id": rid,
                "sub_category": sub_cat,
                "timestamp": ts.isoformat() if hasattr(ts, "isoformat") else str(ts),
                "metrics": metrics or {},
            })
        return out
    except Exception:
        return []


def fetch_latest(sub_category):
    """取某 sub_category 最新一条记录，返回 dict 或 None。"""
    rows = fetch_records(sub_category, limit=1, order_desc=True)
    return rows[0] if rows else None


def fetch_max_record_id():
    """取 records 表最大 id（原子事件断点续扫用）。FAIL-OPEN: 异常返回 0。"""
    try:
        conn = _connect()
        cur = conn.cursor()
        cur.execute("SELECT COALESCE(MAX(id), 0) FROM records")
        val = cur.fetchone()[0]
        conn.close()
        return int(val)
    except Exception:
        return 0


def fetch_latest_by_source(source, sub_category=None):
    """按 source（可选 sub_category）取最新一条记录（L0 datacenter.record scope 用）。

    返回 {source, category, sub_category, timestamp, metrics} 或 None。
    FAIL-OPEN: 异常或无记录返回 None。
    """
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
        metrics = row[4]
        if isinstance(metrics, str):
            try:
                metrics = json.loads(metrics)
            except Exception:
                pass
        ts = row[3].isoformat() if hasattr(row[3], "isoformat") else str(row[3])
        return {
            "source": row[0],
            "category": row[1],
            "sub_category": row[2],
            "timestamp": ts,
            "metrics": metrics,
        }
    except Exception:
        return None


def fetch_source_groups(limit=60):
    """按 source/category/sub_category 分组统计记录数（data_query 意图采集用）。

    返回 [{source, category, sub_category, count}]，按记录数降序。FAIL-OPEN: 异常返回 []。
    """
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


def fetch_records_since(sub_category_like, since_id, limit=5000):
    """按 id 增量查询（原子事件 --live 模式用），返回升序结果。"""
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
        out = []
        for rid, sub_cat, ts, metrics in rows:
            if isinstance(metrics, str):
                try:
                    metrics = json.loads(metrics)
                except Exception:
                    metrics = {}
            out.append({
                "id": rid,
                "sub_category": sub_cat,
                "timestamp": ts.isoformat() if hasattr(ts, "isoformat") else str(ts),
                "metrics": metrics or {},
            })
        return out
    except Exception:
        return []
