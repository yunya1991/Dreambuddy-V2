from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from typing import Any, Callable, Dict, Optional


LoopRunner = Callable[..., Dict[str, Any]]


def _load_module(module_path: Path, module_name: str):
    spec = importlib.util.spec_from_file_location(module_name, module_path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


def _default_runners():
    root = Path(__file__).resolve().parents[1]
    exec_mod = _load_module(root / "orchestrator" / "execution_loop.py", "execution_loop_mod")
    gov_mod = _load_module(root / "orchestrator" / "governance_loop.py", "governance_loop_mod")
    a6_mod = _load_module(root / "A6_intelligence" / "entrypoint.py", "a6_entry_mod")
    return exec_mod.run_execution_loop, a6_mod.run_a6_intelligence, gov_mod.run_governance_loop


def _ship_messages(transport, messages):
    sent = 0
    for message in messages:
        if hasattr(transport, "send_envelope"):
            transport.send_envelope(message)
        else:
            header = message.get("header") or {}
            channel = str(header.get("loop_type") or "execution")
            transport.send(channel, message)
        sent += 1
    return sent


def _loop_failed(loop_output: Dict[str, Any]) -> bool:
    stage_outputs = loop_output.get("stage_outputs") or {}
    for payload in stage_outputs.values():
        if str(payload.get("status") or "").upper() in {"FAIL", "ERROR", "DEGRADED"}:
            return True
        if payload.get("error_code"):
            return True
    return False


def _collect_metrics(trace_id: str, loops: Dict[str, Dict[str, Any]], message_count: int) -> Dict[str, Any]:
    loop_count = len(loops)
    failure_distribution = {name: int(_loop_failed(output)) for name, output in loops.items()}
    success_count = loop_count - sum(failure_distribution.values())
    retry_count = 0
    for output in loops.values():
        stage_outputs = output.get("stage_outputs") or {}
        retry_count += sum(1 for key in stage_outputs.keys() if "retry" in key.lower() or "recheck" in key.lower())
    avg_duration_ms = 0
    known_durations = [int(output.get("duration_ms") or 0) for output in loops.values() if int(output.get("duration_ms") or 0) > 0]
    if known_durations:
        avg_duration_ms = int(sum(known_durations) / len(known_durations))
    return {
        "trace_id": trace_id,
        "loop_count": loop_count,
        "message_count": message_count,
        "success_rate": success_count / loop_count if loop_count else 0.0,
        "avg_duration_ms": avg_duration_ms,
        "retry_rate": retry_count / loop_count if loop_count else 0.0,
        "failure_distribution": failure_distribution,
    }


def run_system_loop(
    payload: Dict[str, Any],
    output_dir: Optional[Path] = None,
    *,
    transport: Any,
    execution_runner: Optional[LoopRunner] = None,
    intelligence_runner: Optional[LoopRunner] = None,
    governance_runner: Optional[LoopRunner] = None,
) -> Dict[str, Any]:
    if transport is None:
        root = Path(__file__).resolve().parents[1]
        mod = _load_module(root / "transports" / "adapters.py", "trading_transports_adapters")
        transport = mod.build_default_transport_router()

    default_execution, default_intelligence, default_governance = _default_runners()
    run_execution = execution_runner or default_execution
    run_intelligence = intelligence_runner or default_intelligence
    run_governance = governance_runner or default_governance

    execution_out = run_execution(payload, output_dir=output_dir)
    intelligence_out = run_intelligence(payload, output_dir=output_dir)
    governance_out = run_governance(payload, output_dir=output_dir)

    message_count = 0
    message_count += _ship_messages(transport, execution_out.get("messages") or [])
    message_count += _ship_messages(transport, intelligence_out.get("messages") or [])
    message_count += _ship_messages(transport, governance_out.get("messages") or [])
    trace_id = str(payload.get("trace_id") or "trace-missing")
    loops = {
        "execution": execution_out,
        "intelligence": intelligence_out,
        "governance": governance_out,
    }
    metrics = _collect_metrics(trace_id, loops, message_count)
    base = Path(output_dir) if output_dir is not None else Path("artifacts/trading")
    base.mkdir(parents=True, exist_ok=True)
    metrics_path = base / f"system_metrics_{trace_id}.json"
    metrics_path.write_text(json.dumps(metrics, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    return {
        "trace_id": trace_id,
        "loops": loops,
        "metrics": metrics,
        "metrics_artifact_path": str(metrics_path),
    }
