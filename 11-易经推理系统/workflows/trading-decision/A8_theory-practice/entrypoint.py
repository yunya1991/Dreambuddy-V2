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


def run_a8_theory_practice(payload: Dict[str, Any], output_dir: Optional[Path] = None) -> Dict[str, Any]:
    """Thin wrapper for A8 theory-practice verification output."""
    proto = _load_protocol_module()
    hypo = float(payload.get('hypothesis_score') or 0.0)
    prac = float(payload.get('practice_score') or 0.0)
    gap = abs(hypo - prac)

    ts = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    base = Path(output_dir) if output_dir is not None else Path('artifacts/trading')
    base.mkdir(parents=True, exist_ok=True)
    out_path = base / f'a8_theory_practice_{ts}.json'

    result = proto.ensure_contract_fields(
        {
        'stage_id': 'A8',
        'trace_id': payload.get('trace_id'),
        'hypothesis_score': hypo,
        'practice_score': prac,
        'gap_score': gap,
        'timestamp': ts,
        },
        producer="workflows/trading-decision/A8_theory-practice",
    )
    result['artifact_path'] = str(out_path)
    proto.require_contract_fields(result)
    out_path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    return proto.build_envelope(
        source="A8",
        target="A2",
        message_type="FEEDBACK",
        priority="MEDIUM",
        loop_type="governance",
        trace_id=result["trace_id"],
        correlation_id=payload.get("correlation_id"),
        timeout_ms=300000,
        payload=result,
    )
