"""sqlite 落库 — 对齐 TECHNICAL_DESIGN.md §6。

默认落库表 records，schema 对齐 DataRecord；dedupe_key 唯一 + INSERT OR IGNORE 去重。

扩展（持续采集调度器配套）：
  - metrics 表：持久化 InvocationMetric，支持按 (source, category) 聚合统计
  - quality_issues 表：持久化 QualityIssue，支持按时间倒序查询
  - alerts 表：持久化 Alert，支持按时间倒序查询
  - query_records / latest_records：按源/时间窗口查询 DataRecord
  - source_health：各数据源最近一次采集状态 + 累计统计
"""
from __future__ import annotations

import json
import sqlite3
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any, Optional

from data_center.core.contract import DataRecord
from data_center.monitoring.alerting import Alert
from data_center.monitoring.metrics import InvocationMetric
from data_center.monitoring.quality import QualityIssue
from data_center.storage.cache import dedupe_key

# ── records 表（DataRecord 原始采集结果）─────────────────────────────────────
_SCHEMA_RECORDS = """
CREATE TABLE IF NOT EXISTS records (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    dedupe_key TEXT UNIQUE,
    source TEXT, category TEXT, sub_category TEXT, timestamp TEXT,
    metrics TEXT, events TEXT, timeseries TEXT, raw TEXT, schema_version TEXT
)
"""

_COLUMNS = [
    "dedupe_key", "source", "category", "sub_category", "timestamp",
    "metrics", "events", "timeseries", "raw", "schema_version",
]
_INSERT_SQL = (
    f"INSERT OR IGNORE INTO records ({', '.join(_COLUMNS)}) "
    f"VALUES ({', '.join(['?'] * len(_COLUMNS))})"
)

# ── metrics 表（InvocationMetric 调用统计）───────────────────────────────────
_SCHEMA_METRICS = """
CREATE TABLE IF NOT EXISTS metrics (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    invocation_id TEXT,
    ts TEXT,
    source TEXT, category TEXT,
    status TEXT,
    duration_ms REAL,
    records_count INTEGER,
    error_type TEXT,
    error_msg TEXT
)
"""
_INSERT_METRIC_SQL = (
    "INSERT INTO metrics (invocation_id, ts, source, category, status, "
    "duration_ms, records_count, error_type, error_msg) VALUES (?,?,?,?,?,?,?,?,?)"
)

# ── quality_issues 表（QualityIssue 数据质量问题）─────────────────────────────
_SCHEMA_QUALITY = """
CREATE TABLE IF NOT EXISTS quality_issues (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT,
    source TEXT, category TEXT,
    code TEXT,
    message TEXT,
    invocation_id TEXT,
    extra TEXT
)
"""
_INSERT_QUALITY_SQL = (
    "INSERT INTO quality_issues (ts, source, category, code, message, invocation_id, extra) "
    "VALUES (?,?,?,?,?,?,?)"
)

# ── alerts 表（Alert 告警记录）────────────────────────────────────────────────
_SCHEMA_ALERTS = """
CREATE TABLE IF NOT EXISTS alerts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT,
    level TEXT,
    title TEXT,
    message TEXT,
    tags TEXT
)
"""
_INSERT_ALERT_SQL = (
    "INSERT INTO alerts (ts, level, title, message, tags) VALUES (?,?,?,?,?)"
)


class SqliteSink:
    """数据中心 SQLite 持久化层：records / metrics / quality_issues / alerts 四表统一管理。"""

    def __init__(self, db_path: str):
        self.db_path = db_path
        conn = sqlite3.connect(db_path)
        conn.execute(_SCHEMA_RECORDS)
        conn.execute(_SCHEMA_METRICS)
        conn.execute(_SCHEMA_QUALITY)
        conn.execute(_SCHEMA_ALERTS)
        conn.commit()
        conn.close()

    # ──────────────────────────────────────────────────────────────────────
    # records 表（DataRecord 原始采集结果）
    # ──────────────────────────────────────────────────────────────────────
    def write(self, records: list[DataRecord]) -> int:
        """落库 DataRecord，返回实际新增行数（同 dedupe_key 被忽略）。"""
        conn = sqlite3.connect(self.db_path)
        inserted = 0
        for r in records:
            cur = conn.execute(
                _INSERT_SQL,
                (
                    dedupe_key(r), r.source, r.category, r.sub_category, r.timestamp,
                    json.dumps(r.metrics, ensure_ascii=False),
                    json.dumps(r.events, ensure_ascii=False),
                    json.dumps(r.timeseries, ensure_ascii=False),
                    json.dumps(r.raw, ensure_ascii=False),
                    r.schema_version,
                ),
            )
            inserted += cur.rowcount
        conn.commit()
        conn.close()
        return inserted

    def read_all(self) -> list[DataRecord]:
        conn = sqlite3.connect(self.db_path)
        rows = conn.execute(
            "SELECT source, category, sub_category, timestamp, "
            "metrics, events, timeseries, raw, schema_version FROM records"
        ).fetchall()
        conn.close()
        return [
            DataRecord(
                source=r[0], category=r[1], sub_category=r[2], timestamp=r[3],
                metrics=json.loads(r[4]), events=json.loads(r[5]),
                timeseries=json.loads(r[6]), raw=json.loads(r[7]),
                schema_version=r[8],
            )
            for r in rows
        ]

    def query_records(
        self,
        *,
        source: Optional[str] = None,
        category: Optional[str] = None,
        window_sec: Optional[float] = None,
        limit: int = 100,
    ) -> list[DataRecord]:
        """按 source/category/时间窗口过滤，返回 DataRecord 列表（最新在前）。"""
        sql = (
            "SELECT source, category, sub_category, timestamp, "
            "metrics, events, timeseries, raw, schema_version FROM records WHERE 1=1"
        )
        params: list[Any] = []
        if source is not None:
            sql += " AND source = ?"
            params.append(source)
        if category is not None:
            sql += " AND category = ?"
            params.append(category)
        if window_sec is not None:
            cutoff = datetime.now(timezone.utc).timestamp() - window_sec
            # timestamp 字段为 ISO8601 字符串，需先解析为 epoch 比较
            # SQLite 没有 ISO8601→epoch 内置函数，这里用 Python 端过滤更稳
            pass
        sql += " ORDER BY id DESC LIMIT ?"
        params.append(limit)
        conn = sqlite3.connect(self.db_path)
        rows = conn.execute(sql, params).fetchall()
        conn.close()
        result = [
            DataRecord(
                source=r[0], category=r[1], sub_category=r[2], timestamp=r[3],
                metrics=json.loads(r[4]), events=json.loads(r[5]),
                timeseries=json.loads(r[6]), raw=json.loads(r[7]),
                schema_version=r[8],
            )
            for r in rows
        ]
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
        conn = sqlite3.connect(self.db_path)
        conn.execute(
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
        conn.commit()
        conn.close()

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
            sql += " WHERE ts >= ?"
            params.append(cutoff_iso)
        conn = sqlite3.connect(self.db_path)
        rows = conn.execute(sql, params).fetchall()
        conn.close()
        buckets: dict[tuple[str, str], list[tuple]] = defaultdict(list)
        for r in rows:
            buckets[(r[0], r[1])].append(r)
        out: dict[tuple[str, str], dict[str, Any]] = {}
        for key, items in buckets.items():
            total = len(items)
            ok = sum(1 for x in items if x[2] == "ok")
            errs = total - ok
            avg = sum(x[3] for x in items) / total if total else 0.0
            total_records = sum(x[4] for x in items)
            out[key] = {
                "total": total,
                "ok_count": ok,
                "error_count": errs,
                "avg_duration_ms": round(avg, 3),
                "total_records": total_records,
            }
        return out

    def source_health(self) -> dict[str, dict[str, Any]]:
        """各 source 最近一次采集状态 + 累计统计。

        返回 {source: {last_status, last_ts, last_duration_ms, last_records,
                       total, ok_count, error_count}}
        """
        conn = sqlite3.connect(self.db_path)
        # 各 source 最新一条 metric
        latest_rows = conn.execute(
            "SELECT m.source, m.status, m.ts, m.duration_ms, m.records_count "
            "FROM metrics m "
            "INNER JOIN (SELECT source, MAX(id) AS max_id FROM metrics GROUP BY source) l "
            "ON m.id = l.max_id"
        ).fetchall()
        # 各 source 累计统计
        agg_rows = conn.execute(
            "SELECT source, COUNT(*) AS total, "
            "SUM(CASE WHEN status='ok' THEN 1 ELSE 0 END) AS ok, "
            "SUM(CASE WHEN status='error' THEN 1 ELSE 0 END) AS err "
            "FROM metrics GROUP BY source"
        ).fetchall()
        conn.close()
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
        conn = sqlite3.connect(self.db_path)
        for q in issues:
            conn.execute(
                _INSERT_QUALITY_SQL,
                (
                    q.ts.isoformat(),
                    q.source or metric.source,
                    q.category or metric.category,
                    q.code.value if hasattr(q.code, "value") else str(q.code),
                    q.message,
                    metric.invocation_id,
                    json.dumps(q.extra, ensure_ascii=False) if q.extra else None,
                ),
            )
        conn.commit()
        conn.close()

    def recent_issues(self, *, limit: int = 20) -> list[dict[str, Any]]:
        """按时间倒序返回最近 N 条质量 issue。"""
        conn = sqlite3.connect(self.db_path)
        rows = conn.execute(
            "SELECT ts, source, category, code, message, invocation_id, extra "
            "FROM quality_issues ORDER BY id DESC LIMIT ?",
            (limit,),
        ).fetchall()
        conn.close()
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
        conn = sqlite3.connect(self.db_path)
        conn.execute(
            _INSERT_ALERT_SQL,
            (
                alert.ts.isoformat(),
                alert.level.value if hasattr(alert.level, "value") else str(alert.level),
                alert.title,
                alert.message,
                json.dumps(alert.tags, ensure_ascii=False),
            ),
        )
        conn.commit()
        conn.close()

    def recent_alerts(self, *, limit: int = 20) -> list[dict[str, Any]]:
        """按时间倒序返回最近 N 条告警。"""
        conn = sqlite3.connect(self.db_path)
        rows = conn.execute(
            "SELECT ts, level, title, message, tags FROM alerts ORDER BY id DESC LIMIT ?",
            (limit,),
        ).fetchall()
        conn.close()
        return [
            {
                "ts": r[0], "level": r[1], "title": r[2],
                "message": r[3],
                "tags": json.loads(r[4]) if r[4] else [],
            }
            for r in rows
        ]
