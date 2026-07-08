import importlib.util
from typing import Any, Dict, List
from pathlib import Path


def _load_protocol_module():
    mod_path = Path(__file__).resolve().parents[1] / "protocol" / "message.py"
    spec = importlib.util.spec_from_file_location("trading_protocol_message", mod_path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


def run_a0_contradiction_analysis(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Thin wrapper for A0 contradiction ranking."""
    proto = _load_protocol_module()
    items: List[Dict[str, Any]] = list(payload.get("contradictions") or [])
    items.sort(key=lambda x: float(x.get("score") or 0.0), reverse=True)
    primary = items[0] if items else {"id": "none", "score": 0.0, "direction": "NEUTRAL"}
    direction = str(primary.get("direction") or "NEUTRAL")

    result = proto.ensure_contract_fields(
        {
        "stage_id": "A0",
        "trace_id": payload.get("trace_id"),
        "primary_contradiction": primary,
        "direction": direction,
        "total_contradictions": len(items),
        },
        producer="workflows/trading-decision/A0_contradiction",
    )
    proto.require_contract_fields(result)
    return proto.build_envelope(
        source="A0",
        target="A1",
        message_type="REQUEST",
        priority="HIGH",
        loop_type="governance",
        trace_id=result["trace_id"],
        correlation_id=payload.get("correlation_id"),
        timeout_ms=30000,
        payload=result,
    )
