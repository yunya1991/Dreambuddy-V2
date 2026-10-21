"""PostgreSQL 落库 — 接口与 sink_sqlite.SqliteSink 完全对齐。

属于 38-数据库管理系统 SPEC 方案 4（SQLite → PostgreSQL 迁移）。
- 表结构 / 去重语义 / 查询行为与 SQLite 版本一致
- 连接参数从环境变量读取，避免硬编码凭据：
    DATA_CENTER_PG_HOST      默认 127.0.0.1
    DATA_CENTER_PG_PORT      默认 5432
    DATA_CENTER_PG_USER      默认 dreambuddy
    DATA_CENTER_PG_PASSWORD
    DATA_CENTER_PG_DB        默认 data_center
- get_sink() 按 DATA_CENTER_BACKEND 环境变量切换后端（postgres|sqlite），
  默认 postgres（迁移完成后），回滚设 DATA_CENTER_BACKEND=sqlite。
"""
from __future__ import annotations

import json
import os
import re
from collections import defaultdict
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import psycopg2


def _discover_password() -> str:
    """密码发现：环境变量优先，否则从现有 .env 配置提取（postgresql://user:pwd@host 格式）。"""
    pwd = os.environ.get("DATA_CENTER_PG_PASSWORD", "")
    if pwd:
        return pwd
    for env_path in (
        Path.home() / "dreambuddy" / "7-产物中台" / "系统研究索引体系" / ".env",
        Path("/home/luke/dreambuddy/7-产物中台/系统研究索引体系/.env"),
    ):
        try:
            if env_path.exists():
                for line in env_path.read_text().splitlines():
                    m = re.search(r"postgresql://[^:\s]+:([^@\s]+)@", line)
                    if m:
                        return m.group(1)
        except Exception:
            continue
    return ""

from data_center.core.contract import DataRecord
from data_center.monitoring.alerting import Alert
from data_center.monitoring.metrics import InvocationMetric
from data_center.monitoring.quality import QualityIssue
from data_center.storage.cache import dedupe_key
from data_center.storage.sink_sqlite import _json_default

_SCHEMA_RECORDS = """
CREATE TABLE IF NOT EXISTS records (
    id BIGSERIAL PRIMARY KEY,
    dedupe_key TEXT UNIQUE,
    source TEXT, category TEXT, sub_category TEXT, timestamp TEXT,
    metrics TEXT, events TEXT, timeseries TEXT, raw TEXT, schema_version TEXT
);
CREATE INDEX IF NOT EXISTS idx_records_timestamp ON records(timestamp);
CREATE INDEX IF NOT EXISTS idx_records_source ON records(source);
"""
_SCHEMA_METRICS = """
CREATE TABLE IF NOT EXISTS metrics (
    id BIGSERIAL PRIMARY KEY,
    invocation_id TEXT, ts TEXT, source TEXT, category TEXT,
    status TEXT, duration_ms REAL, records_count INTEGER,
    error_type TEXT, error_msg TEXT
);
"""
_SCHEMA_QUALITY = """
CREATE TABLE IF NOT EXISTS quality_issues (
    id BIGSERIAL PRIMARY KEY,
    ts TEXT, source TEXT, category TEXT, code TEXT, message TEXT,
    invocation_id TEXT, extra TEXT
);
"""
_SCHEMA_ALERTS = """
CREATE TABLE IF NOT EXISTS alerts (
    id BIGSERIAL PRIMARY KEY,
    ts TEXT, level TEXT, title TEXT, message TEXT, tags TEXT
);
"""

_INSERT_SQL = """
INSERT INTO records (dedupe_key, source, category, sub_category, timestamp,
                     metrics, events, timeseries, raw, schema_version)
VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
ON CONFLICT (dedupe_key) DO UPDATE SET
    source = EXCLUDED.source,
    category = EXCLUDED.category,
    sub_category = EXCLUDED.sub_category,
    timestamp = EXCLUDED.timestamp,
    metrics = EXCLUDED.metrics,
    events = EXCLUDED.events,
    timeseries = EXCLUDED.timeseries,
    raw = EXCLUDED.raw,
    schema_version = EXCLUDED.schema_version
"""

_INSERT_METRIC_SQL = """
INSERT INTO metrics (invocation_id, ts, source, category, status,
                     duration_ms, records_count, error_type, error_msg)
VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
"""

_INSERT_QUALITY_SQL = """
INSERT INTO quality_issues (ts, source, category, code, message, invocation_id, extra)
VALUES (%s, %s, %s, %s, %s, %s, %s)
"""

_INSERT_ALERT_SQL = """
INSERT INTO alerts (ts, level, title, message, tags)
VALUES (%s, %s, %s, %s, %s)
"""

_SELECT_RECORDS = (
    "SELECT source, category, sub_category, timestamp, "
    "metrics, events, timeseries, raw, schema_version FROM records"
)


def _row_to_record(r) -> DataRecord:
    return DataRecord(
        source=r[0], category=r[1], sub_category=r[2], timestamp=r[3],
        metrics=json.loads(r[4]) if r[4] else {},
        events=json.loads(r[5]) if r[5] else [],
        timeseries=json.loads(r[6]) if r[6] else [],
        raw=json.loads(r[7]) if r[7] else {},
        schema_version=r[8] or "1.0",
    )


class PostgresSink:
    """数据中心 PostgreSQL 持久化层：接口与 SqliteSink 完全对齐。"""

    def __init__(self, db: Optional[str] = None):
        self.conn_params = {
            "host": os.environ.get("DATA_CENTER_PG_HOST", "127.0.0.1"),
            "port": int(os.environ.get("DATA_CENTER_PG_PORT", "5432")),
            "user": os.environ.get("DATA_CENTER_PG_USER", "dreambuddy"),
            "password": _discover_password(),
            "dbname": db or os.environ.get("DATA_CENTER_PG_DB", "data_center"),
        }
        with self._conn() as conn:
            with conn.cursor() as cur:
                cur.execute(_SCHEMA_RECORDS)
                cur.execute(_SCHEMA_METRICS)
                cur.execute(_SCHEMA_QUALITY)
                cur.execute(_SCHEMA_ALERTS)

    @contextmanager
    def _conn(self):
        """连接上下文：退出时提交事务并关闭连接（psycopg2 的 with 只提交不关闭）。"""
        conn = psycopg2.connect(**self.conn_params)
        try:
            with conn:
                yield conn
        finally:
            conn.close()

    # ──────────────────────────────────────────────────────────────────────
    # records 表（DataRecord 原始采集结果）
    # ──────────────────────────────────────────────────────────────────────
    def write(self, records: list[DataRecord]) -> int:
        """落库 DataRecord，返回实际新增行数（同 dedupe_key 覆盖旧值但不计为新增）。"""
        inserted = 0
        with self._conn() as conn:
            with conn.cursor() as cur:
                for r in records:
                    key = dedupe_key(r)
                    cur.execute(
                        "SELECT 1 FROM records WHERE dedupe_key = %s LIMIT 1", (key,)
                    )
                    exists = cur.fetchone()
                    cur.execute(
                        _INSERT_SQL,
                        (
                            key, r.source, r.category, r.sub_category, r.timestamp,
                            json.dumps(r.metrics, ensure_ascii=False, default=_json_default),
                            json.dumps(r.events, ensure_ascii=False, default=_json_default),
                            json.dumps(r.timeseries, ensure_ascii=False, default=_json_default),
                            json.dumps(r.raw, ensure_ascii=False, default=_json_default),
                            r.schema_version,
                        ),
                    )
                    if not exists:
                        inserted += 1
        return inserted

    def read_all(self) -> list[DataRecord]:
        with self._conn() as conn:
            with conn.cursor() as cur:
                cur.execute(_SELECT_RECORDS)
                rows = cur.fetchall()
        return [_row_to_record(r) for r in rows]

    def query_records(
        self,
        *,
        source: Optional[str] = None,
        category: Optional[str] = None,
        window_sec: Optional[float] = None,
        limit: int = 100,
    ) -> list[DataRecord]:
        """按 source/category/时间窗口过滤，返回 DataRecord 列表（最新在前）。"""
        sql = _SELECT_RECORDS + " WHERE 1=1"
        params: list[Any] = []
        if source is not None:
            sql += " AND source = %s"
            params.append(source)
        if category is not None:
            sql += " AND category = %s"
            params.append(category)
        sql += " ORDER BY id DESC LIMIT %s"
        params.append(limit)
        with self._conn() as conn:
            with conn.cursor() as cur:
                cur.execute(sql, params)
                rows = cur.fetchall()
        result = [_row_to_record(r) for r in rows]
        if window_sec is not None:
            cutoff = datetime.now(timezone.utc).timestamp() - window_sec
            filtered: list[DataRecord] = []
            for rec in result:
                try:
                    ts = datetime.fromisoformat(rec.timestamp.replace("Z", "+00:00"))
                    if ts.timestamp() >= cutoff:
                        filtered.append(rec)
                except Exception:
                    continue
            result = filtered
        return result

    def latest_records(self, *, source: str, limit: int = 10) -> list[DataRecord]:
        """某 source 最新 N 条 DataRecord（按 id 倒序）。"""
        return self.query_records(source=source, limit=limit)

    # ──────────────────────────────────────────────────────────────────────
    # metrics 表（InvocationMetric 调用统计）
    # ──────────────────────────────────────────────────────────────────────
    def write_metric(self, metric: InvocationMetric) -> None:
        """落库一次调用的统计。"""
        with self._conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    _INSERT_METRIC_SQL,
                    (
                        metric.invocation_id,
                        metric.ts.isoformat(),
                        metric.source, metric.category,
                        metric.status,
                        metric.duration_ms,
                        metric.records_count,
                        metric.error_type,
                        metric.error_msg,
                    ),
                )

    def summary(
        self,
        *,
        window_sec: Optional[float] = None,
    ) -> dict[tuple[str, str], dict[str, Any]]:
        """按 (source, category) 聚合统计：total/ok_count/error_count/avg_duration_ms/total_records。"""
        sql = "SELECT source, category, status, duration_ms, records_count, ts FROM metrics"
        params: list[Any] = []
        if window_sec is not None:
            cutoff_iso = datetime.fromtimestamp(
                datetime.now(timezone.utc).timestamp() - window_sec,
                tz=timezone.utc,
            ).isoformat()
            sql += " WHERE ts >= %s"
            params.append(cutoff_iso)
        with self._conn() as conn:
            with conn.cursor() as cur:
                cur.execute(sql, params)
                rows = cur.fetchall()
        buckets: dict[tuple[str, str], list[tuple]] = defaultdict(list)
        for r in rows:
            buckets[(r[0], r[1])].append(r)
        out: dict[tuple[str, str], dict[str, Any]] = {}
        for key, items in buckets.items():
            total = len(items)
            ok = sum(1 for x in items if x[2] == "ok")
            avg = sum(x[3] for x in items) / total if total else 0.0
            out[key] = {
                "total": total,
                "ok_count": ok,
                "error_count": total - ok,
                "avg_duration_ms": round(avg, 3),
                "total_records": sum(x[4] for x in items),
            }
        return out

    def source_health(self) -> dict[str, dict[str, Any]]:
        """各 source 最近一次采集状态 + 累计统计。"""
        with self._conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT m.source, m.status, m.ts, m.duration_ms, m.records_count "
                    "FROM metrics m "
                    "INNER JOIN (SELECT source, MAX(id) AS max_id FROM metrics GROUP BY source) l "
                    "ON m.id = l.max_id"
                )
                latest_rows = cur.fetchall()
                cur.execute(
                    "SELECT source, COUNT(*), "
                    "SUM(CASE WHEN status='ok' THEN 1 ELSE 0 END), "
                    "SUM(CASE WHEN status='error' THEN 1 ELSE 0 END) "
                    "FROM metrics GROUP BY source"
                )
                agg_rows = cur.fetchall()
        agg_map = {r[0]: {"total": r[1], "ok_count": r[2], "error_count": r[3]} for r in agg_rows}
        out: dict[str, dict[str, Any]] = {}
        for r in latest_rows:
            src = r[0]
            out[src] = {
                "last_status": r[1],
                "last_ts": r[2],
                "last_duration_ms": r[3],
                "last_records": r[4],
                **(agg_map.get(src, {"total": 0, "ok_count": 0, "error_count": 0})),
            }
        return out

    # ──────────────────────────────────────────────────────────────────────
    # quality_issues 表
    # ──────────────────────────────────────────────────────────────────────
    def write_quality(
        self,
        metric: InvocationMetric,
        issues: list[QualityIssue],
    ) -> None:
        """落库一批 QualityIssue，关联 invocation_id 便于追溯。"""
        if not issues:
            return
        with self._conn() as conn:
            with conn.cursor() as cur:
                for q in issues:
                    cur.execute(
                        _INSERT_QUALITY_SQL,
                        (
                            q.ts.isoformat(),
                            q.source or metric.source,
                            q.category or metric.category,
                            q.code.value if hasattr(q.code, "value") else str(q.code),
                            q.message,
                            metric.invocation_id,
                            json.dumps(q.extra, ensure_ascii=False, default=_json_default) if q.extra else None,
                        ),
                    )

    def recent_issues(self, *, limit: int = 20) -> list[dict[str, Any]]:
        """按时间倒序返回最近 N 条质量 issue。"""
        with self._conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT ts, source, category, code, message, invocation_id, extra "
                    "FROM quality_issues ORDER BY id DESC LIMIT %s",
                    (limit,),
                )
                rows = cur.fetchall()
        return [
            {
                "ts": r[0], "source": r[1], "category": r[2],
                "code": r[3], "message": r[4],
                "invocation_id": r[5],
                "extra": json.loads(r[6]) if r[6] else {},
            }
            for r in rows
        ]

    # ──────────────────────────────────────────────────────────────────────
    # alerts 表
    # ──────────────────────────────────────────────────────────────────────
    def write_alert(self, alert: Alert) -> None:
        """落库一条告警。"""
        with self._conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    _INSERT_ALERT_SQL,
                    (
                        alert.ts.isoformat(),
                        alert.level.value if hasattr(alert.level, "value") else str(alert.level),
                        alert.title,
                        alert.message,
                        json.dumps(alert.tags, ensure_ascii=False, default=_json_default),
                    ),
                )

    def recent_alerts(self, *, limit: int = 20) -> list[dict[str, Any]]:
        """按时间倒序返回最近 N 条告警。"""
        with self._conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT ts, level, title, message, tags FROM alerts ORDER BY id DESC LIMIT %s",
                    (limit,),
                )
                rows = cur.fetchall()
        return [
            {
                "ts": r[0], "level": r[1], "title": r[2],
                "message": r[3],
                "tags": json.loads(r[4]) if r[4] else [],
            }
            for r in rows
        ]


def get_sink(db_path: Optional[str] = None):
    """按 DATA_CENTER_BACKEND 环境变量返回存储后端（postgres|sqlite），默认 sqlite 保持现状。"""
    backend = os.environ.get("DATA_CENTER_BACKEND", "postgres").lower()
    if backend == "postgres":
        return PostgresSink()
    from data_center.storage.sink_sqlite import SqliteSink
    return SqliteSink(db_path or os.environ.get("DATA_CENTER_DB_PATH", "data_center.db"))
