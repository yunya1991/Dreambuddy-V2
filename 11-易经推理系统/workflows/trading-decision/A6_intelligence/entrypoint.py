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


def _route_alert(alert: Dict[str, Any]) -> Dict[str, Any]:
    risk_score = float(alert.get("risk_score") or 0.0)
    regime_change = bool(alert.get("regime_change"))
    theory_practice_score = float(alert.get("theory_practice_score") or 1.0)

    if risk_score >= 0.9:
        return {"level": "L0", "targets": ["A9"], "message_type": "EVENT", "priority": "CRITICAL", "action": "IMMEDIATE_EXIT"}
    if risk_score >= 0.7:
        return {"level": "L1", "targets": ["A4"], "message_type": "REQUEST", "priority": "HIGH", "action": "REVALIDATE"}
    if regime_change:
        return {"level": "L1.5", "targets": ["A2"], "message_type": "REQUEST", "priority": "HIGH", "action": "INCREMENTAL_UPDATE"}
    if risk_score >= 0.5:
        return {"level": "L2", "targets": ["OBSERVE"], "message_type": "NOTIFICATION", "priority": "MEDIUM", "action": "LOG_ONLY"}
    if theory_practice_score < 0.7:
        return {"level": "L3", "targets": ["A1", "A3"], "message_type": "EVENT", "priority": "MEDIUM", "action": "RESTART_RESEARCH"}
    return {"level": "L2", "targets": ["OBSERVE"], "message_type": "NOTIFICATION", "priority": "LOW", "action": "LOG_ONLY"}


def run_a6_intelligence(payload: Dict[str, Any], output_dir: Optional[Path] = None) -> Dict[str, Any]:
    """A6 intelligence output with L0/L1/L1.5/L2/L3 routing events."""
    proto = _load_protocol_module()
    alerts: List[Dict[str, Any]] = list(payload.get('alerts') or [])
    signal_shift = float(payload.get('signal_shift') or 0.0)

    ts = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    base = Path(output_dir) if output_dir is not None else Path('artifacts/trading')
    base.mkdir(parents=True, exist_ok=True)
    out_path = base / f'a6_intelligence_{ts}.json'

    routed_events: List[Dict[str, Any]] = []
    route_summary: Dict[str, int] = {"L0": 0, "L1": 0, "L1.5": 0, "L2": 0, "L3": 0}
    trace_id = str(payload.get("trace_id") or "trace-missing")
    correlation_id = payload.get("correlation_id")

    for idx, alert in enumerate(alerts):
        route = _route_alert(alert)
        level = route["level"]
        route_summary[level] = route_summary.get(level, 0) + 1

        alert_payload = proto.ensure_contract_fields(
            {
                "stage_id": "A6",
                "trace_id": trace_id,
                "alert_index": idx,
                "alert_level": level,
                "alert": alert,
                "action": route["action"],
            },
            producer="workflows/trading-decision/A6_intelligence",
        )

        for target in route["targets"]:
            routed_events.append(
                proto.build_envelope(
                    source="A6",
                    target=target,
                    message_type=route["message_type"],
                    priority=route["priority"],
                    loop_type="intelligence",
                    trace_id=trace_id,
                    correlation_id=correlation_id,
                    timeout_ms=0 if level == "L0" else 30000,
                    payload=alert_payload,
                )
            )

    result = proto.ensure_contract_fields(
        {
        'stage_id': 'A6',
        'trace_id': trace_id,
        'alert_count': len(alerts),
        'alerts': alerts,
        'signal_shift': signal_shift,
        'route_summary': route_summary,
        'routed_events': routed_events,
        'timestamp': ts,
        },
        producer="workflows/trading-decision/A6_intelligence",
    )
    result['artifact_path'] = str(out_path)
    proto.require_contract_fields(result)
    out_path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    return proto.build_envelope(
        source="A6",
        target="A4",
        message_type="NOTIFICATION",
        priority="MEDIUM",
        loop_type="intelligence",
        trace_id=trace_id,
        correlation_id=correlation_id,
        timeout_ms=30000,
        payload=result,
    )
