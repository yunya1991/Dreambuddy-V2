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


def _risk_gate(max_drawdown_pct: float, position_ratio: float, stop_loss_pct: float) -> str:
    if max_drawdown_pct > 6 or position_ratio > 0.8 or stop_loss_pct > 4:
        return 'BLOCK'
    if max_drawdown_pct > 3 or position_ratio > 0.5 or stop_loss_pct > 2:
        return 'REVIEW'
    return 'PASS'


def _retrieve_memory(payload: Dict[str, Any]) -> list:
    try:
        from workflows.trading_decision.orchestrator.memory_retriever import (
            retrieve_memory_refs_for_stage,
        )
        return retrieve_memory_refs_for_stage("A4", payload, topk=3)
    except Exception:
        return []


def run_a4_validation(payload: Dict[str, Any], output_dir: Optional[Path] = None) -> Dict[str, Any]:
    """Thin wrapper for A4 risk gate validation artifact output."""
    proto = _load_protocol_module()
    max_dd = float(payload.get('max_drawdown_pct') or 0.0)
    pos_ratio = float(payload.get('position_ratio') or 0.0)
    stop_loss = float(payload.get('stop_loss_pct') or 0.0)
    gate = _risk_gate(max_drawdown_pct=max_dd, position_ratio=pos_ratio, stop_loss_pct=stop_loss)

    ts = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    base = Path(output_dir) if output_dir is not None else Path('artifacts/trading')
    base.mkdir(parents=True, exist_ok=True)
    out_path = base / f'a4_validation_{ts}.json'

    memory_refs = _retrieve_memory(payload)

    result = proto.ensure_contract_fields(
        {
        'stage_id': 'A4',
        'trace_id': payload.get('trace_id'),
        'max_drawdown_pct': max_dd,
        'position_ratio': pos_ratio,
        'stop_loss_pct': stop_loss,
        'risk_gate': gate,
        'timestamp': ts,
        },
        producer="workflows/trading-decision/A4_validation",
    )
    result['memory_refs'] = memory_refs
    result['artifact_path'] = str(out_path)
    proto.require_contract_fields(result)
    out_path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    return proto.build_envelope(
        source="A4",
        target="A5",
        message_type="REQUEST",
        priority="HIGH",
        loop_type="execution",
        trace_id=result["trace_id"],
        correlation_id=payload.get("correlation_id"),
        timeout_ms=60000,
        payload=result,
    )
