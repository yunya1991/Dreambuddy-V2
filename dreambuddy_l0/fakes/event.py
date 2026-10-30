"""Event port 内存 fake：publish/consume。"""
from typing import Any, Dict, Optional


class FakeEvent:
    def __init__(self):
        self._events: List[Dict[str, Any]] = []

    def publish(self, event_type: str, payload: Dict[str, Any], *, trace_id: str = "") -> bool:
        self._events.append({"type": event_type, "payload": payload, "trace_id": trace_id})
        return True

    def consume(self, *, event_type: str = "", cursor: Optional[str] = None, limit: int = 100) -> Dict[str, Any]:
        evs = [e for e in self._events if not event_type or e["type"] == event_type]
        return {"events": evs[:limit], "cursor": None}
