#!/usr/bin/env python3
"""40 周期神经网络系统 · 统一数据库访问助手（跟随 DATA_CENTER_BACKEND 配置）。

背景（2026-11-10 修复）：云端 18-数据获取中心已切换 DATA_CENTER_BACKEND=postgres，
本模块 p1/p2/p3/risk_guards 脚本原先直连 SQLite data_center.db（云端为 0 字节空文件），
导致日更流水线首节点 no such table: records 中止。

本助手提供：
  - 后端切换：DATA_CENTER_BACKEND=postgres（默认，与 18 中心一致）| sqlite
  - 密码发现：DATA_CENTER_PG_PASSWORD 环境变量 → ~/.dreambuddy-pg.env → 7-产物中台 .env
  - FRED 序列查询（等价原 json_extract(metrics, '$.value') 语义）
  - 最近时间戳查询 / 计数查询 / 记录写入（smart_money 用）

SQL 方言适配：
  - SQLite: json_extract(metrics, '$.value')
  - PostgreSQL: (metrics::json->>'value')::float8
"""

from __future__ import annotations

import json
import os
import re
import sqlite3
from pathlib import Path

_DREAMBUDDY_ROOT = os.environ.get("DREAMBUDDY_ROOT") or os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
)
SQLITE_DB = os.path.join(_DREAMBUDDY_ROOT, "18-数据获取中心", "data_center.db")


def _discover_pg_password() -> str:
    """密码发现：环境变量优先，回退 luke 私有凭证文件与 7-产物中台 .env。"""
    pwd = os.environ.get("DATA_CENTER_PG_PASSWORD", "")
    if pwd:
        return pwd
    for env_path in (
        Path.home() / ".dreambuddy-pg.env",
        Path(_DREAMBUDDY_ROOT) / "7-产物中台" / "系统研究索引体系" / ".env",
    ):
        try:
            if env_path.exists():
                for line in env_path.read_text().splitlines():
                    if line.strip().startswith("DATA_CENTER_PG_PASSWORD="):
                        return line.strip().split("=", 1)[1].strip()
                    m = re.search(r"postgresql://[^:\s]+:([^@\s]+)@", line)
                    if m:
                        return m.group(1)
        except Exception:
            continue
    return ""


def backend() -> str:
    """当前存储后端：postgres（默认）| sqlite。"""
    return os.environ.get("DATA_CENTER_BACKEND", "postgres").lower()


def _connect_sqlite():
    return sqlite3.connect(SQLITE_DB)


def _connect_pg():
    import psycopg2

    return psycopg2.connect(
        host=os.environ.get("DATA_CENTER_PG_HOST", "127.0.0.1"),
        port=int(os.environ.get("DATA_CENTER_PG_PORT", "5432")),
        user=os.environ.get("DATA_CENTER_PG_USER", "dreambuddy"),
        password=_discover_pg_password(),
        dbname=os.environ.get("DATA_CENTER_PG_DB", "data_center"),
    )


def connect():
    """按 DATA_CENTER_BACKEND 返回数据库连接（sqlite3 或 psycopg2）。"""
    if backend() == "sqlite":
        return _connect_sqlite()
    return _connect_pg()


def _placeholder(sql: str) -> str:
    """SQLite 风格 ? 占位符 → PG %s（仅本模块内部使用，调用方统一写 ?）。"""
    if backend() == "sqlite":
        return sql
    return sql.replace("?", "%s")


def query_fred_series(sub_category: str, source: str = "fred"):
    """查询 FRED 序列全量历史：[(timestamp, value), ...] 按 timestamp 升序。

    等价原 SQL: SELECT timestamp, json_extract(metrics, '$.value') FROM records
                WHERE source = ? AND sub_category = ? ORDER BY timestamp
    """
    if backend() == "sqlite":
        sql = (
            "SELECT timestamp, json_extract(metrics, '$.value') FROM records "
            "WHERE source = ? AND sub_category = ? ORDER BY timestamp"
        )
    else:
        sql = (
            "SELECT timestamp, (metrics::json->>'value')::float8 FROM records "
            "WHERE source = %s AND sub_category = %s ORDER BY timestamp"
        )
    conn = connect()
    try:
        cur = conn.cursor()
        cur.execute(sql, (source, sub_category))
        return cur.fetchall()
    finally:
        conn.close()


def query_recent_timestamps(source: str, sub_category: str, limit: int = 5):
    """查询某序列最近 N 条时间戳（降序）。risk_guards 新鲜度检查用。"""
    sql = _placeholder(
        "SELECT timestamp FROM records WHERE source = ? AND sub_category = ? "
        "ORDER BY timestamp DESC LIMIT " + str(int(limit))
    )
    conn = connect()
    try:
        cur = conn.cursor()
        cur.execute(sql, (source, sub_category))
        return cur.fetchall()
    finally:
        conn.close()


def count_series(source: str, sub_category: str) -> int:
    """统计某序列记录数。risk_guards 尾部置信度检查用。"""
    sql = _placeholder(
        "SELECT COUNT(*) FROM records WHERE source = ? AND sub_category = ?"
    )
    conn = connect()
    try:
        cur = conn.cursor()
        cur.execute(sql, (source, sub_category))
        return int(cur.fetchone()[0])
    finally:
        conn.close()


def insert_record(
    *,
    dedupe_key: str,
    source: str,
    category: str,
    sub_category: str,
    timestamp: str,
    metrics: dict,
    raw: dict | None = None,
) -> bool:
    """写入一条记录（幂等：dedupe_key 冲突时忽略）。p3_smart_money 用。

    返回 True=新写入，False=已存在被忽略。
    """
    metrics_json = json.dumps(metrics, ensure_ascii=False)
    raw_json = json.dumps(raw or {}, ensure_ascii=False)
    if backend() == "sqlite":
        sql = (
            "INSERT OR IGNORE INTO records "
            "(dedupe_key, source, category, sub_category, timestamp, metrics, "
            "events, timeseries, raw, schema_version) "
            "VALUES (?, ?, ?, ?, ?, ?, '[]', '[]', ?, 'v1')"
        )
    else:
        sql = (
            "INSERT INTO records "
            "(dedupe_key, source, category, sub_category, timestamp, metrics, "
            "events, timeseries, raw, schema_version) "
            "VALUES (%s, %s, %s, %s, %s, %s, '[]', '[]', %s, 'v1') "
            "ON CONFLICT (dedupe_key) DO NOTHING"
        )
    params = (dedupe_key, source, category, sub_category, timestamp, metrics_json, raw_json)
    conn = connect()
    try:
        cur = conn.cursor()
        cur.execute(sql, params)
        conn.commit()
        return cur.rowcount > 0
    finally:
        conn.close()
