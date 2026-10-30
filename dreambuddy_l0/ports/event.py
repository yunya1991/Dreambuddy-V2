"""Event port：publish / consume（跨能力通知语义）。

调度器写 job_runs、dispatcher 消费事件一律走 Store/Event（SPEC-C §3.1）。
"""
from typing import Any, Dict, Optional, Protocol, runtime_checkable


@runtime_checkable
class EventPort(Protocol):
    def publish(self, event_type: str, payload: Dict[str, Any], *,
                trace_id: str = "") -> bool: ...
    def consume(self, *, event_type: str = "", cursor: Optional[str] = None,
                limit: int = 100) -> Dict[str, Any]: ...
