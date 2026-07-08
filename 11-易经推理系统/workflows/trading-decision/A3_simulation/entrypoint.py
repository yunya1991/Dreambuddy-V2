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


def _pick_strategy_mode(signal_score: float, volatility: float, market_regime: str) -> str:
    regime = (market_regime or '').lower()
    if signal_score >= 60 and volatility <= 0.03 and regime in {'trend', 'breakout'}:
        return 'trend_follow'
    if volatility >= 0.04 or regime in {'range', 'chop'}:
        return 'mean_revert'
    return 'neutral'


def _retrieve_memory(payload: Dict[str, Any]) -> list:
    try:
        from workflows.trading_decision.orchestrator.memory_retriever import (
            retrieve_memory_refs_for_stage,
        )
        return retrieve_memory_refs_for_stage("A3", payload, topk=3)
    except Exception:
        return []


def run_a3_simulation(payload: Dict[str, Any], output_dir: Optional[Path] = None) -> Dict[str, Any]:
    """Thin wrapper for A3 strategy simulation artifact output."""
    proto = _load_protocol_module()
    signal_score = float(payload.get('signal_score') or 50.0)
    volatility = float(payload.get('volatility') or 0.02)
    market_regime = str(payload.get('market_regime') or 'neutral')
    strategy_mode = _pick_strategy_mode(signal_score, volatility, market_regime)

    ts = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    base = Path(output_dir) if output_dir is not None else Path('artifacts/trading')
    base.mkdir(parents=True, exist_ok=True)
    out_path = base / f'a3_simulation_{ts}.json'

    memory_refs = _retrieve_memory(payload)

    result = proto.ensure_contract_fields(
        {
        'stage_id': 'A3',
        'trace_id': payload.get('trace_id'),
        'signal_score': signal_score,
        'volatility': volatility,
        'market_regime': market_regime,
        'strategy_mode': strategy_mode,
        'timestamp': ts,
        },
        producer="workflows/trading-decision/A3_simulation",
    )
    result['memory_refs'] = memory_refs
    result['artifact_path'] = str(out_path)
    proto.require_contract_fields(result)
    out_path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    return proto.build_envelope(
        source="A3",
        target="A4",
        message_type="REQUEST",
        priority="HIGH",
        loop_type="execution",
        trace_id=result["trace_id"],
        correlation_id=payload.get("correlation_id"),
        timeout_ms=60000,
        payload=result,
    )
