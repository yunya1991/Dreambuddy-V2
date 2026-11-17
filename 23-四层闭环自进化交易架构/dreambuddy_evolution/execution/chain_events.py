"""A 类交易链路 stage event 写入（FAIL-OPEN，只读旁路）。

设计口径：15-监控告警系统/docs/TECHNICAL_DESIGN.md §13.4
- 事件落盘为 JSONL，按 UTC 日期轮转：runtime/chain_events-YYYYMMDD.jsonl
- 任何异常都不得影响交易主链（全部 try/except 吞掉）
- 不写入密钥、不写完整订单原始报文
"""

from __future__ import annotations

import json
import logging
import os
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

SCHEMA = "chain_event.v1"
_REPO_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_DIR = _REPO_ROOT / "runtime"
_LOCK = threading.Lock()


def runtime_dir() -> Path:
    """事件目录，可用 EVOLUTION_CHAIN_EVENTS_DIR 覆盖。"""
    raw = os.getenv("EVOLUTION_CHAIN_EVENTS_DIR", "").strip()
    return Path(raw) if raw else _DEFAULT_DIR


def event_path(ts: datetime | None = None) -> Path:
    _ts = ts or datetime.now(timezone.utc)
    return runtime_dir() / f"chain_events-{_ts.strftime('%Y%m%d')}.jsonl"


def new_trace_id(symbol: str, ts: datetime | None = None) -> str:
    """N1 生成的推理段 trace_id，贯穿整条链路。"""
    _ts = ts or datetime.now(timezone.utc)
    _sym = str(symbol or "UNKNOWN").replace("/", "-")
    return f"evt-{_ts.strftime('%Y%m%dT%H%M%S%f')}-{_sym}"


def emit_stage(
    stage: str,
    node: str,
    symbol: str,
    status: str = "pass",
    *,
    data: dict[str, Any] | None = None,
    chain_id: str | None = None,
    decision_id: str | None = None,
    upstream_decision_id: str | None = None,
    trace_id: str | None = None,
    duration_ms: float | None = None,
    ts: datetime | None = None,
) -> None:
    """写入一条链路事件；失败静默，不影响调用方。"""
    try:
        _ts = ts or datetime.now(timezone.utc)
        record: dict[str, Any] = {
            "schema": SCHEMA,
            "stage": str(stage),
            "node": str(node),
            "symbol": str(symbol or "?"),
            "ts": _ts.isoformat(),
            "status": str(status),
        }
        if trace_id:
            record["trace_id"] = str(trace_id)
        if chain_id:
            record["chain_id"] = str(chain_id)
        if decision_id:
            record["decision_id"] = str(decision_id)
        if upstream_decision_id:
            record["upstream_decision_id"] = str(upstream_decision_id)
        if duration_ms is not None:
            record["duration_ms"] = round(float(duration_ms), 3)
        if data:
            record["data"] = data

        path = event_path(_ts)
        path.parent.mkdir(parents=True, exist_ok=True)
        line = json.dumps(record, ensure_ascii=False, separators=(",", ":"), default=str)
        with _LOCK:
            with path.open("a", encoding="utf-8") as fh:
                fh.write(line + "\n")
    except Exception as exc:  # noqa: BLE001 — 观测失败绝不影响交易
        logger.debug("[FO] chain_event emit fail stage=%s: %s", stage, exc)
