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


def _exit_action(unrealized_pnl_pct: float, risk_level: str) -> str:
    risk = (risk_level or '').lower()
    if unrealized_pnl_pct >= 3.0:
        return 'TAKE_PROFIT'
    if unrealized_pnl_pct <= -2.0 or risk in {'high', 'extreme'}:
        return 'STOP_LOSS'
    return 'HOLD'


def _retrieve_memory(payload: Dict[str, Any]) -> list:
    try:
        from workflows.trading_decision.orchestrator.memory_retriever import (
            retrieve_memory_refs_for_stage,
        )
        return retrieve_memory_refs_for_stage("A9", payload, topk=3)
    except Exception:
        return []


def run_a9_exit(payload: Dict[str, Any], output_dir: Optional[Path] = None) -> Dict[str, Any]:
    """Thin wrapper for A9 exit plan output."""
    proto = _load_protocol_module()
    pnl = float(payload.get('unrealized_pnl_pct') or 0.0)
    risk_level = str(payload.get('risk_level') or 'medium')
    action = _exit_action(unrealized_pnl_pct=pnl, risk_level=risk_level)

    ts = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    base = Path(output_dir) if output_dir is not None else Path('artifacts/trading')
    base.mkdir(parents=True, exist_ok=True)
    out_path = base / f'a9_exit_{ts}.json'

    memory_refs = _retrieve_memory(payload)

    result = proto.ensure_contract_fields(
        {
        'stage_id': 'A9',
        'trace_id': payload.get('trace_id'),
        'unrealized_pnl_pct': pnl,
        'risk_level': risk_level,
        'exit_action': action,
        'timestamp': ts,
        },
        producer="workflows/trading-decision/A9_exit",
    )
    result['memory_refs'] = memory_refs
    result['artifact_path'] = str(out_path)
    proto.require_contract_fields(result)
    out_path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    return proto.build_envelope(
        source="A9",
        target="A7",
        message_type="EVENT",
        priority="HIGH",
        loop_type="execution",
        trace_id=result["trace_id"],
        correlation_id=payload.get("correlation_id"),
        timeout_ms=30000,
        payload=result,
    )
