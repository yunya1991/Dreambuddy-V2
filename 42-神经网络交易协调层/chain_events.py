"""主神经网络链 stage event 写入（FAIL-OPEN，只读旁路）。

口径：15-监控告警系统/docs/TECHNICAL_DESIGN.md §14（M0–M14，source=main-nn）。
- 事件模型沿用 chain_event.v1，新增 source/mode/reason_category（向后兼容）
- 按 UTC 日期轮转：<runtime_dir>/chain_events-YYYYMMDD.jsonl
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
SOURCE = "main-nn"
_REPO_ROOT = Path(__file__).resolve().parents[1]
_DEFAULT_DIR = _REPO_ROOT / "42-神经网络交易协调层" / "runtime"
_LOCK = threading.Lock()


def new_trace_id(symbol: str, ts: datetime | None = None) -> str:
    """M6 生成的链路 trace_id，贯穿 M6→M13。"""
    _ts = ts or datetime.now(timezone.utc)
    _sym = str(symbol or "UNKNOWN").replace("/", "-")
    return f"mnn-{_ts.strftime('%Y%m%dT%H%M%S%f')}-{_sym}"


def runtime_dir(path: str | Path | None = None) -> Path:
    """事件目录：显式入参 > MAIN_NN_CHAIN_EVENTS_DIR > 42/runtime。"""
    if path:
        return Path(path)
    raw = os.getenv("MAIN_NN_CHAIN_EVENTS_DIR", "").strip()
    return Path(raw) if raw else _DEFAULT_DIR


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
    mode: str | None = None,
    reason_category: str | None = None,
    duration_ms: float | None = None,
    runtime: str | Path | None = None,
    ts: datetime | None = None,
) -> None:
    """写入一条主神经网络链路事件；失败静默，不影响调用方。"""
    try:
        _ts = ts or datetime.now(timezone.utc)
        record: dict[str, Any] = {
            "schema": SCHEMA,
            "source": SOURCE,
            "stage": str(stage),
            "node": str(node),
            "symbol": str(symbol or "MACRO"),
            "ts": _ts.isoformat(),
            "status": str(status),
        }
        if mode:
            record["mode"] = str(mode)
        if reason_category:
            record["reason_category"] = str(reason_category)
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

        path = runtime_dir(runtime) / f"chain_events-{_ts.strftime('%Y%m%d')}.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        line = json.dumps(record, ensure_ascii=False, separators=(",", ":"), default=str)
        with _LOCK:
            with path.open("a", encoding="utf-8") as fh:
                fh.write(line + "\n")
    except Exception as exc:  # noqa: BLE001 — 观测失败绝不影响交易
        logger.debug("[FO] main-nn chain_event emit fail stage=%s: %s", stage, exc)
