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


def _least_resistance_path(rsi: float, funding_rate: float, fgi: int) -> str:
    score = 50.0
    if rsi > 70:
        score += 20
    elif rsi < 30:
        score -= 20
    if funding_rate > 0.0005:
        score += 10
    elif funding_rate < -0.0005:
        score -= 10
    if fgi > 70:
        score += 10
    elif fgi < 30:
        score -= 10

    if score < 40:
        return "UP"
    if score > 60:
        return "DOWN"
    return "NEUTRAL"


def run_a2_first_principles(payload: Dict[str, Any], output_dir: Optional[Path] = None) -> Dict[str, Any]:
    """Thin wrapper for A2 first-principles artifact output."""
    proto = _load_protocol_module()
    rsi = float(payload.get("rsi") or 50.0)
    funding_rate = float(payload.get("funding_rate") or 0.0)
    fgi = int(payload.get("fgi") or 50)

    path = _least_resistance_path(rsi=rsi, funding_rate=funding_rate, fgi=fgi)
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")

    base = Path(output_dir) if output_dir is not None else Path("artifacts/trading")
    base.mkdir(parents=True, exist_ok=True)
    out_path = base / f"a2_first_principles_{ts}.json"

    result = proto.ensure_contract_fields(
        {
        "stage_id": "A2",
        "trace_id": payload.get("trace_id"),
        "least_resistance_path": path,
        "rsi": rsi,
        "funding_rate": funding_rate,
        "fgi": fgi,
        "timestamp": ts,
        },
        producer="workflows/trading-decision/A2_first-principles",
    )
    result["artifact_path"] = str(out_path)
    proto.require_contract_fields(result)
    out_path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return proto.build_envelope(
        source="A2",
        target="A3",
        message_type="REQUEST",
        priority="HIGH",
        loop_type="execution",
        trace_id=result["trace_id"],
        correlation_id=payload.get("correlation_id"),
        timeout_ms=60000,
        payload=result,
    )
