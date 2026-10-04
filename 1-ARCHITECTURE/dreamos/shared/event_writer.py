"""JSONL 事件写入器 — SPEC-20260929-L1-TRACE-PILOT

统一事件写入 ~/.workbuddy/events/{system}/{YYYY-MM-DD}.jsonl
- append-only, 按日期滚动
- 失败兜底 logging.warning, 不阻断业务
- 全局开关: DREAMOS_EVENT_JSONL=0 时禁用
- 双写开关: DREAMOS_EVENT_PG=1 时同时写 PostgreSQL (默认关闭)

Schema v1:
    {v, id, trace_id, span_id, parent_span_id, ts, system, layer, node,
     event_type, status, duration_ms, payload_ref, error, meta}
"""

from __future__ import annotations

import json
import logging
import os
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

_SYSTEM_DEFAULT = "dreamos"

# PostgreSQL 双写（L1 加速）
try:
    import psycopg2
    from psycopg2.extras import Json as PgJson
    _PG_AVAILABLE = True
except ImportError:
    _PG_AVAILABLE = False
    logger.warning("psycopg2 not available, PostgreSQL dual-write disabled")


def _resolve_events_root() -> Path:
    """统一 events root 解析 (P1)
    优先级: WORKBUDDY_EVENTS_ROOT > dreambuddy-v2/events
    注意: 基于 __file__ 计算, 不依赖 cwd
    """
    env = os.environ.get("WORKBUDDY_EVENTS_ROOT", "").strip()
    if env:
        return Path(env)
    # dreamos/shared/event_writer.py -> 项目根 = parents[3]
    return Path(__file__).resolve().parents[3] / "events"


_EVENTS_ROOT = _resolve_events_root()

# PostgreSQL 连接池（懒加载）
_pg_conn = None


def _get_pg_conn():
    """获取 PostgreSQL 连接（单例，带重连）"""
    global _pg_conn
    if not _PG_AVAILABLE:
        return None
    if os.environ.get("DREAMOS_EVENT_PG", "0") != "1":
        return None

    database_url = os.environ.get(
        "DATABASE_URL",
        "postgresql://postgres:dreambuddy@127.0.0.1:5432/dreambuddy"
    )

    try:
        if _pg_conn is None or _pg_conn.closed:
            _pg_conn = psycopg2.connect(database_url)
            _pg_conn.autocommit = True
        return _pg_conn
    except Exception as e:
        logger.warning(f"[event_writer] PG connect failed: {e}")
        return None


def _pg_emit_event(record: Dict[str, Any]) -> None:
    """将事件写入 PostgreSQL（失败兜底 logging.warning）"""
    conn = _get_pg_conn()
    if conn is None:
        return

    try:
        system = record.get("system", "")
        event_type = record.get("event_type", "")
        trace_id = record.get("trace_id", "")

        if system == "dreamos":
            if event_type in ("graph_execute.start", "graph_execute.end"):
                # Session 级
                status_map = {"ok": "completed", "fail": "failed", "skip": "skipped"}
                status = status_map.get(record.get("status", "ok"), "running")
                if event_type == "graph_execute.start":
                    status = "running"
                elif event_type == "graph_execute.end":
                    status = "completed" if record.get("status") == "ok" else "failed"

                with conn.cursor() as cur:
                    cur.execute("""
                        INSERT INTO dreamos_sessions (
                            trace_id, session_id, graph_name, status,
                            start_ts, end_ts, duration_ms,
                            total_nodes, executed_nodes,
                            budget_tokens, used_tokens,
                            termination_reason, extra,
                            created_at, updated_at
                        ) VALUES (
                            %s, %s, %s, %s,
                            %s, %s, %s,
                            %s, %s,
                            %s, %s,
                            %s, %s,
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
                    """, (
                        trace_id,
                        record.get("meta", {}).get("cycle_id", trace_id),
                        record.get("meta", {}).get("graph_name", "trading_agent"),
                        status,
                        record.get("ts"),
                        record.get("ts") if event_type == "graph_execute.end" else None,
                        record.get("duration_ms"),
                        record.get("meta", {}).get("total_nodes"),
                        record.get("meta", {}).get("executed_nodes"),
                        record.get("meta", {}).get("budget_tokens"),
                        record.get("meta", {}).get("used_tokens"),
                        record.get("meta", {}).get("termination_reason"),
                        PgJson(record.get("meta", {})),
                    ))
            else:
                # Span 级
                status_map = {"ok": "ok", "fail": "fail", "skip": "skip"}
                with conn.cursor() as cur:
                    cur.execute("""
                        INSERT INTO dreamos_spans (
                            trace_id, span_id, parent_span_id,
                            node_id, node_type, status,
                            start_ts, end_ts, duration_ms,
                            allocated_tokens, used_tokens,
                            confidence, error_message, meta
                        ) VALUES (
                            %s, %s, %s,
                            %s, %s, %s,
                            %s, %s, %s,
                            %s, %s,
                            %s, %s, %s
                        )
                    """, (
                        trace_id,
                        record.get("span_id", ""),
                        record.get("parent_span_id"),
                        record.get("node", ""),
                        record.get("meta", {}).get("node_type", "compute"),
                        status_map.get(record.get("status", "ok"), "ok"),
                        record.get("ts"),
                        record.get("ts"),
                        record.get("duration_ms"),
                        record.get("meta", {}).get("allocated_tokens"),
                        record.get("meta", {}).get("tokens_used"),
                        record.get("meta", {}).get("confidence"),
                        record.get("error"),
                        PgJson(record.get("meta", {})),
                    ))

        elif system == "dsh":
            with conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO dsh_subagent_calls (
                        trace_id, subagent_type,
                        request_payload, response_payload,
                        status, duration_ms, error_message
                    ) VALUES (
                        %s, %s,
                        %s, %s,
                        %s, %s, %s
                    )
                """, (
                    trace_id,
                    record.get("meta", {}).get("subagent_type", "unknown"),
                    PgJson(record.get("meta", {}).get("request", {})),
                    PgJson(record.get("meta", {}).get("response", {})),
                    "ok" if record.get("status") == "ok" else "fail",
                    record.get("duration_ms"),
                    record.get("error"),
                ))

    except Exception as e:
        logger.warning(f"[event_writer] PG write failed: {e}")
        # 连接异常时重置连接，下次重试
        try:
            if _pg_conn and not _pg_conn.closed:
                _pg_conn.close()
        except Exception:
            pass
        _pg_conn = None


def gen_span_id() -> str:
    return uuid.uuid4().hex[:8]


def gen_event_id() -> str:
    return f"evt_{uuid.uuid4().hex[:12]}"


def _today_file_name() -> str:
    return datetime.now().strftime("%Y-%m-%d") + ".jsonl"


def _ensure_dir(p: Path) -> None:
    p.mkdir(parents=True, exist_ok=True)


def emit_event(
    trace_id: str,
    system: str = _SYSTEM_DEFAULT,
    layer: str = "",
    node: str = "",
    event_type: str = "",
    status: str = "ok",           # ok | fail | skip
    span_id: Optional[str] = None,
    parent_span_id: Optional[str] = None,
    duration_ms: Optional[float] = None,
    payload_ref: Optional[str] = None,
    error: Optional[str] = None,
    meta: Optional[Dict[str, Any]] = None,
) -> None:
    """同步写入 JSONL 事件; 失败兜底 logging.warning, 不抛出"""
    if os.environ.get("DREAMOS_EVENT_JSONL", "1") == "0":
        return
    if not trace_id:
        return
    try:
        dir_path = _EVENTS_ROOT / system
        _ensure_dir(dir_path)
        file_path = dir_path / _today_file_name()
        record = {
            "v": 1,
            "id": gen_event_id(),
            "trace_id": trace_id,
            "span_id": span_id or gen_span_id(),
            "parent_span_id": parent_span_id,
            "ts": datetime.utcnow().isoformat() + "Z",
            "system": system,
            "layer": layer,
            "node": node,
            "event_type": event_type,
            "status": status,
            "duration_ms": duration_ms,
            "payload_ref": payload_ref,
            "error": error,
            "meta": meta or {},
        }
        with open(file_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")

        # PostgreSQL 双写（L1 加速）
        _pg_emit_event(record)

    except Exception as e:  # noqa: BLE001
        logger.warning(f"[event_writer] write failed: {e}")
