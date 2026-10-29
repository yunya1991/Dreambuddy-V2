# -*- coding: utf-8 -*-
"""DreamOS 事件生产者：将编排器埋点事件写入本地 JSONL，供 etl-worker 消费。

FAIL-OPEN 设计：任何异常均静默吞掉，绝不影响业务主流程。
"""
import json
import os
import time
import uuid
from datetime import datetime

_EVENTS_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "events", "dreamos",
)


def emit_event(trace_id, system, layer, node, event_type, status,
               span_id=None, parent_span_id=None, duration_ms=None,
               payload_ref=None, error=None, meta=None):
    """写入一条事件到本地 JSONL 文件（按本地日期分文件）。"""
    try:
        event = {
            "trace_id": trace_id,
            "system": system,
            "layer": layer,
            "node": node,
            "event_type": event_type,
            "status": status,
            "span_id": span_id or uuid.uuid4().hex[:16],
            "parent_span_id": parent_span_id,
            "duration_ms": duration_ms,
            "payload_ref": payload_ref,
            "error": str(error) if error else None,
            "meta": meta or {},
            "ts": datetime.now().isoformat(),
            "unix_ts": time.time(),
        }
        os.makedirs(_EVENTS_DIR, exist_ok=True)
        path = os.path.join(
            _EVENTS_DIR, datetime.now().strftime("%Y-%m-%d") + ".jsonl"
        )
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(event, ensure_ascii=False) + "\n")
        return True
    except Exception:
        return False
