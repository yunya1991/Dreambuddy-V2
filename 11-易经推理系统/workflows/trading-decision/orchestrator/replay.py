from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List


def _to_dt(ts: str) -> datetime:
    return datetime.fromisoformat(ts.replace("Z", "+00:00"))


def build_trace_index(events: List[Dict[str, Any]]) -> Dict[str, List[Dict[str, Any]]]:
    index: Dict[str, List[Dict[str, Any]]] = {}
    for event in events:
        trace_id = str(event.get("trace_id") or "")
        if not trace_id:
            continue
        index.setdefault(trace_id, []).append(dict(event))
    return index


def replay_trace(trace_id: str, index: Dict[str, List[Dict[str, Any]]]) -> Dict[str, Any]:
    events = sorted(index.get(trace_id, []), key=lambda x: x.get("timestamp", ""))
    if not events:
        return {"trace_id": trace_id, "stage_count": 0, "retry_count": 0, "duration_ms": 0}

    start = _to_dt(events[0]["timestamp"])
    end = _to_dt(events[-1]["timestamp"])
    retry_count = sum(1 for e in events if bool(e.get("retry")))
    return {
        "trace_id": trace_id,
        "stage_count": len(events),
        "retry_count": retry_count,
        "duration_ms": int((end - start).total_seconds() * 1000),
        "stages": [str(e.get("stage_id")) for e in events],
    }
