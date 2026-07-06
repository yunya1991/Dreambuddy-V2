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
        return retrieve_memory_refs_for_stage("A5", payload, topk=3)
    except Exception:
        return []


def run_a5_execution(payload: Dict[str, Any], output_dir: Optional[Path] = None) -> Dict[str, Any]:
    """Thin wrapper for A5 execution plan artifact output."""
    proto = _load_protocol_module()
    direction = str(payload.get('direction') or 'LONG').upper()
    side = 'BUY' if direction == 'LONG' else 'SELL'

    order_plan = {
        'side': side,
        'entry_price': float(payload.get('entry_price') or 0.0),
        'leverage': int(payload.get('leverage') or 1),
        'order_type': 'LIMIT',
    }

    ts = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    base = Path(output_dir) if output_dir is not None else Path('artifacts/trading')
    base.mkdir(parents=True, exist_ok=True)
    out_path = base / f'a5_execution_{ts}.json'

    memory_refs = _retrieve_memory(payload)

    result = proto.ensure_contract_fields(
        {
        'stage_id': 'A5',
        'trace_id': payload.get('trace_id'),
        'direction': direction,
        'order_plan': order_plan,
        'timestamp': ts,
        },
        producer="workflows/trading-decision/A5_execution",
    )
    result['memory_refs'] = memory_refs
    result['artifact_path'] = str(out_path)
    proto.require_contract_fields(result)
    out_path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    return proto.build_envelope(
        source="A5",
        target="A9",
        message_type="REQUEST",
        priority="HIGH",
        loop_type="execution",
        trace_id=result["trace_id"],
        correlation_id=payload.get("correlation_id"),
        timeout_ms=60000,
        payload=result,
    )
