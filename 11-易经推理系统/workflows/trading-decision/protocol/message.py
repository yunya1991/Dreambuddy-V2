from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, Optional
from uuid import uuid4


VALID_LOOP_TYPES = {"execution", "intelligence", "governance"}


def _utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def build_header(
    *,
    source: str,
    target: str,
    message_type: str,
    priority: str,
    loop_type: str,
    trace_id: str,
    correlation_id: Optional[str] = None,
    timeout_ms: int = 30000,
    version: str = "2.0",
    message_id: Optional[str] = None,
    timestamp: Optional[str] = None,
) -> Dict[str, Any]:
    if loop_type not in VALID_LOOP_TYPES:
        raise ValueError(f"invalid loop_type: {loop_type}")

    return {
        "message_id": message_id or f"msg_{source.lower()}_{target.lower()}_{uuid4().hex[:10]}",
        "timestamp": timestamp or _utc_iso(),
        "version": version,
        "source": source,
        "target": target,
        "type": message_type,
        "priority": priority,
        "correlation_id": correlation_id,
        "trace_id": trace_id,
        "loop_type": loop_type,
        "timeout_ms": int(timeout_ms),
    }


def build_envelope(
    *,
    source: str,
    target: str,
    message_type: str,
    priority: str,
    loop_type: str,
    trace_id: str,
    payload: Dict[str, Any],
    correlation_id: Optional[str] = None,
    timeout_ms: int = 30000,
) -> Dict[str, Any]:
    return {
        "header": build_header(
            source=source,
            target=target,
            message_type=message_type,
            priority=priority,
            loop_type=loop_type,
            trace_id=trace_id,
            correlation_id=correlation_id,
            timeout_ms=timeout_ms,
        ),
        "payload": payload,
    }


def ensure_contract_fields(
    payload: Dict[str, Any],
    *,
    producer: str,
    constraint_version: str = "v0.1",
    schema_version: str = "2.0",
) -> Dict[str, Any]:
    data = dict(payload)
    data.setdefault("constraint_version", constraint_version)
    data.setdefault("memory_refs", [])
    data.setdefault("evidence_refs", [])
    data.setdefault("producer", producer)
    data.setdefault("schema_version", schema_version)
    data.setdefault("timestamp", _utc_iso())
    return data


def require_contract_fields(payload: Dict[str, Any]) -> Dict[str, Any]:
    required = [
        "stage_id",
        "trace_id",
        "constraint_version",
        "memory_refs",
        "evidence_refs",
        "producer",
        "schema_version",
    ]
    missing = [k for k in required if k not in payload or payload[k] in (None, "")]
    if missing:
        raise ValueError(f"missing required contract fields: {', '.join(missing)}")
    return payload


def envelope_payload(data: Dict[str, Any]) -> Dict[str, Any]:
    if "payload" in data and isinstance(data["payload"], dict):
        return data["payload"]
    return data
