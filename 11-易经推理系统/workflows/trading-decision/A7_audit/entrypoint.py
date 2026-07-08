import json
import importlib.util
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional


def _load_protocol_module():
    mod_path = Path(__file__).resolve().parents[1] / "protocol" / "message.py"
    spec = importlib.util.spec_from_file_location("trading_protocol_message", mod_path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


def run_a7_audit(payload: Dict[str, Any], output_dir: Optional[Path] = None) -> Dict[str, Any]:
    """Thin wrapper for A7 audit output."""
    proto = _load_protocol_module()
    violations: List[Dict[str, Any]] = list(payload.get('violations') or [])
    status = 'PASS' if not violations else 'REVIEW'

    ts = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    base = Path(output_dir) if output_dir is not None else Path('artifacts/trading')
    base.mkdir(parents=True, exist_ok=True)
    out_path = base / f'a7_audit_{ts}.json'

    result = proto.ensure_contract_fields(
        {
        'stage_id': 'A7',
        'trace_id': payload.get('trace_id'),
        'checks': payload.get('checks') or {},
        'violations': violations,
        'audit_status': status,
        'timestamp': ts,
        },
        producer="workflows/trading-decision/A7_audit",
    )
    result['artifact_path'] = str(out_path)
    proto.require_contract_fields(result)
    out_path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    return proto.build_envelope(
        source="A7",
        target="A8",
        message_type="REQUEST",
        priority="MEDIUM",
        loop_type="governance",
        trace_id=result["trace_id"],
        correlation_id=payload.get("correlation_id"),
        timeout_ms=300000,
        payload=result,
    )
