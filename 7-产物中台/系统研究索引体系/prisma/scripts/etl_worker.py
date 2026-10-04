#!/usr/bin/env python3
"""
ETL Worker: JSONL → PostgreSQL
================================
从 events/{system}/{date}.jsonl 读取事件，批量写入 PostgreSQL observability 表。
设计原则：JSONL 为 SSOT，PostgreSQL 为物化视图；幂等写入，失败重试。

Usage:
    python etl_worker.py --date 2026-09-29 [--system frontend|dreamos|dsh|hub]
    python etl_worker.py --daemon  # 持续监控模式
"""

import argparse
import json
import logging
import os
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

import psycopg2
from psycopg2.extras import execute_batch, Json

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

# 默认路径
EVENTS_ROOT = Path(os.environ.get("EVENTS_ROOT", Path.home() / ".workbuddy" / "events"))
DATABASE_URL = os.environ.get(
    "DATABASE_URL",
    "postgresql://postgres:dreambuddy@127.0.0.1:5432/dreambuddy"
)

# 系统到表的映射
SYSTEM_TABLE_MAP = {
    "dreamos": {
        "sessions": "dreamos_sessions",
        "spans": "dreamos_spans",
    },
    "dsh": {
        "calls": "dsh_subagent_calls",
    },
}


def get_connection():
    """获取 PostgreSQL 连接（带重试）"""
    max_retries = 3
    for i in range(max_retries):
        try:
            conn = psycopg2.connect(DATABASE_URL)
            conn.autocommit = False
            return conn
        except Exception as e:
            logger.warning(f"DB connection attempt {i+1}/{max_retries} failed: {e}")
            if i < max_retries - 1:
                time.sleep(2 ** i)
    raise RuntimeError("Failed to connect to PostgreSQL after 3 retries")


def parse_jsonl_file(file_path: Path) -> List[Dict[str, Any]]:
    """解析 JSONL 文件，返回事件列表"""
    events = []
    if not file_path.exists():
        logger.warning(f"File not found: {file_path}")
        return events

    with open(file_path, "r", encoding="utf-8") as f:
        for line_no, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                event = json.loads(line)
                events.append(event)
            except json.JSONDecodeError as e:
                logger.warning(f"Invalid JSON at {file_path}:{line_no}: {e}")
    return events


def transform_dreamos_event(event: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """将 DreamOS JSONL 事件转换为数据库记录"""
    trace_id = event.get("trace_id")
    if not trace_id:
        return None

    event_type = event.get("event_type", "")
    node = event.get("node", "")

    # 判断是 session 级还是 span 级事件
    if event_type in ("graph_execute.start", "graph_execute.end"):
        # Session 级
        status_map = {"ok": "completed", "fail": "failed", "skip": "skipped"}
        status = status_map.get(event.get("status", "ok"), "running")
        if event_type == "graph_execute.start":
            status = "running"
        elif event_type == "graph_execute.end":
            status = "completed" if event.get("status") == "ok" else "failed"

        return {
            "_type": "session",
            "trace_id": trace_id,
            "session_id": event.get("meta", {}).get("cycle_id", trace_id),
            "graph_name": event.get("meta", {}).get("graph_name", "trading_agent"),
            "status": status,
            "start_ts": event.get("ts"),
            "end_ts": event.get("ts") if event_type == "graph_execute.end" else None,
            "duration_ms": event.get("duration_ms"),
            "total_nodes": event.get("meta", {}).get("total_nodes"),
            "executed_nodes": event.get("meta", {}).get("executed_nodes"),
            "budget_tokens": event.get("meta", {}).get("budget_tokens"),
            "used_tokens": event.get("meta", {}).get("used_tokens"),
            "termination_reason": event.get("meta", {}).get("termination_reason"),
            "extra": Json(event.get("meta", {})),
        }
    else:
        # Span 级
        status_map = {"ok": "ok", "fail": "fail", "skip": "skip"}
        return {
            "_type": "span",
            "trace_id": trace_id,
            "span_id": event.get("span_id", ""),
            "parent_span_id": event.get("parent_span_id"),
            "node_id": node,
            "node_type": event.get("meta", {}).get("node_type", "compute"),
            "status": status_map.get(event.get("status", "ok"), "ok"),
            "start_ts": event.get("ts"),
            "end_ts": event.get("ts"),
            "duration_ms": event.get("duration_ms"),
            "allocated_tokens": event.get("meta", {}).get("allocated_tokens"),
            "used_tokens": event.get("meta", {}).get("tokens_used"),
            "confidence": event.get("meta", {}).get("confidence"),
            "error_message": event.get("error"),
            "meta": Json(event.get("meta", {})),
        }


def transform_dsh_event(event: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """将 DSH JSONL 事件转换为数据库记录"""
    trace_id = event.get("trace_id")
    if not trace_id:
        return None

    return {
        "_type": "dsh_call",
        "trace_id": trace_id,
        "subagent_type": event.get("meta", {}).get("subagent_type", "unknown"),
        "request_payload": Json(event.get("meta", {}).get("request", {})),
        "response_payload": Json(event.get("meta", {}).get("response", {})),
        "status": "ok" if event.get("status") == "ok" else "fail",
        "duration_ms": event.get("duration_ms"),
        "error_message": event.get("error"),
    }


def upsert_sessions(conn, records: List[Dict[str, Any]]):
    """幂等写入 dreamos_sessions"""
    if not records:
        return 0

    sql = """
        INSERT INTO dreamos_sessions (
            trace_id, session_id, graph_name, status,
            start_ts, end_ts, duration_ms,
            total_nodes, executed_nodes,
            budget_tokens, used_tokens,
            termination_reason, extra,
            created_at, updated_at
        ) VALUES (
            %(trace_id)s, %(session_id)s, %(graph_name)s, %(status)s,
            %(start_ts)s, %(end_ts)s, %(duration_ms)s,
            %(total_nodes)s, %(executed_nodes)s,
            %(budget_tokens)s, %(used_tokens)s,
            %(termination_reason)s, %(extra)s,
            NOW(), NOW()
        )
        ON CONFLICT (trace_id) DO UPDATE SET
            status = EXCLUDED.status,
            end_ts = COALESCE(EXCLUDED.end_ts, dreamos_sessions.end_ts),
            duration_ms = COALESCE(EXCLUDED.duration_ms, dreamos_sessions.duration_ms),
            total_nodes = COALESCE(EXCLUDED.total_nodes, dreamos_sessions.total_nodes),
            executed_nodes = COALESCE(EXCLUDED.executed_nodes, dreamos_sessions.executed_nodes),
            used_tokens = COALESCE(EXCLUDED.used_tokens, dreamos_sessions.used_tokens),
            termination_reason = COALESCE(EXCLUDED.termination_reason, dreamos_sessions.termination_reason),
            updated_at = NOW()
    """

    with conn.cursor() as cur:
        execute_batch(cur, sql, records, page_size=100)
    conn.commit()
    return len(records)


def insert_spans(conn, records: List[Dict[str, Any]]):
    """写入 dreamos_spans（幂等：ON CONFLICT DO NOTHING）"""
    if not records:
        return 0

    sql = """
        INSERT INTO dreamos_spans (
            trace_id, span_id, parent_span_id,
            node_id, node_type, status,
            start_ts, end_ts, duration_ms,
            allocated_tokens, used_tokens,
            confidence, error_message, meta
        ) VALUES (
            %(trace_id)s, %(span_id)s, %(parent_span_id)s,
            %(node_id)s, %(node_type)s, %(status)s,
            %(start_ts)s, %(end_ts)s, %(duration_ms)s,
            %(allocated_tokens)s, %(used_tokens)s,
            %(confidence)s, %(error_message)s, %(meta)s
        )
        ON CONFLICT (trace_id, span_id) DO NOTHING
    """

    with conn.cursor() as cur:
        execute_batch(cur, sql, records, page_size=100)
    conn.commit()
    return len(records)


def insert_dsh_calls(conn, records: List[Dict[str, Any]]):
    """写入 dsh_subagent_calls（幂等：ON CONFLICT DO NOTHING）"""
    if not records:
        return 0

    sql = """
        INSERT INTO dsh_subagent_calls (
            trace_id, subagent_type,
            request_payload, response_payload,
            status, duration_ms, error_message
        ) VALUES (
            %(trace_id)s, %(subagent_type)s,
            %(request_payload)s, %(response_payload)s,
            %(status)s, %(duration_ms)s, %(error_message)s
        )
        ON CONFLICT (trace_id, subagent_type) DO NOTHING
    """

    with conn.cursor() as cur:
        execute_batch(cur, sql, records, page_size=100)
    conn.commit()
    return len(records)


def process_file(conn, file_path: Path, system: str) -> Dict[str, int]:
    """处理单个 JSONL 文件"""
    events = parse_jsonl_file(file_path)
    if not events:
        return {"sessions": 0, "spans": 0, "dsh_calls": 0}

    sessions = []
    spans = []
    dsh_calls = []

    for event in events:
        if system == "dreamos":
            record = transform_dreamos_event(event)
            if record:
                if record["_type"] == "session":
                    sessions.append(record)
                elif record["_type"] == "span":
                    spans.append(record)
        elif system == "dsh":
            record = transform_dsh_event(event)
            if record:
                dsh_calls.append(record)

    result = {"sessions": 0, "spans": 0, "dsh_calls": 0}

    if sessions:
        result["sessions"] = upsert_sessions(conn, sessions)
    if spans:
        result["spans"] = insert_spans(conn, spans)
    if dsh_calls:
        result["dsh_calls"] = insert_dsh_calls(conn, dsh_calls)

    return result


def run_etl(date_str: str, systems: Optional[List[str]] = None):
    """执行 ETL"""
    if systems is None:
        systems = ["frontend", "dreamos", "dsh", "hub"]

    conn = get_connection()
    total = {"sessions": 0, "spans": 0, "dsh_calls": 0}

    try:
        for system in systems:
            file_path = EVENTS_ROOT / system / f"{date_str}.jsonl"
            if not file_path.exists():
                logger.info(f"Skipping {system}: no file for {date_str}")
                continue

            logger.info(f"Processing {file_path} ({file_path.stat().st_size} bytes)")
            result = process_file(conn, file_path, system)
            logger.info(f"  → sessions={result['sessions']}, spans={result['spans']}, dsh_calls={result['dsh_calls']}")

            for k, v in result.items():
                total[k] += v

        logger.info(f"ETL complete: {total}")
        return total
    finally:
        conn.close()


def run_daemon(interval_seconds: int = 60):
    """持续监控模式：每分钟处理当天的文件"""
    logger.info(f"Starting ETL daemon (interval={interval_seconds}s)")
    while True:
        today = datetime.now().strftime("%Y-%m-%d")
        try:
            run_etl(today)
        except Exception as e:
            logger.error(f"ETL daemon error: {e}")
        time.sleep(interval_seconds)


def main():
    parser = argparse.ArgumentParser(description="JSONL → PostgreSQL ETL Worker")
    parser.add_argument("--date", help="Date to process (YYYY-MM-DD), default: today")
    parser.add_argument("--system", help="System to process (frontend/dreamos/dsh/hub)")
    parser.add_argument("--daemon", action="store_true", help="Run as daemon")
    parser.add_argument("--interval", type=int, default=60, help="Daemon interval seconds")
    args = parser.parse_args()

    if args.daemon:
        run_daemon(args.interval)
    else:
        date_str = args.date or datetime.now().strftime("%Y-%m-%d")
        systems = [args.system] if args.system else None
        run_etl(date_str, systems)


if __name__ == "__main__":
    main()
