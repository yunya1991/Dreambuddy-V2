import json
import importlib.util
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional


def _load_protocol_module():
    mod_path = Path(__file__).resolve().parents[1] / "protocol" / "message.py"
    spec = importlib.util.spec_from_file_location("trading_protocol_message", mod_path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


def _retrieve_memory(payload: Dict[str, Any]) -> list:
    try:
        from workflows.trading_decision.orchestrator.memory_retriever import (
            retrieve_memory_refs_for_stage,
        )
        return retrieve_memory_refs_for_stage("A1", payload, topk=3)
    except Exception:
        return []


def run_a1_research(payload: Dict[str, Any], output_dir: Optional[Path] = None) -> Dict[str, Any]:
    """Thin wrapper for A1 research artifact output."""
    proto = _load_protocol_module()
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    base = Path(output_dir) if output_dir is not None else Path("artifacts/trading")
    base.mkdir(parents=True, exist_ok=True)
    out_path = base / f"a1_research_{ts}.json"

    memory_refs = _retrieve_memory(payload)

    result = proto.ensure_contract_fields(
        {
        "stage_id": "A1",
        "trace_id": payload.get("trace_id"),
        "signals": list(payload.get("signals") or []),
        "confidence": float(payload.get("confidence") or 0.0),
        "timestamp": ts,
        },
        producer="workflows/trading-decision/A1_research",
    )
    result["memory_refs"] = memory_refs
    result["artifact_path"] = str(out_path)
    proto.require_contract_fields(result)
    out_path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return proto.build_envelope(
        source="A1",
        target="A2",
        message_type="REQUEST",
        priority="HIGH",
        loop_type="execution",
        trace_id=result["trace_id"],
        correlation_id=payload.get("correlation_id"),
        timeout_ms=60000,
        payload=result,
    )
