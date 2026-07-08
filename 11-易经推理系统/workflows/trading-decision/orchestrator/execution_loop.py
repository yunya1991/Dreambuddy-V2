from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import Any, Callable, Dict, Optional


StageRunner = Callable[[Dict[str, Any], Optional[Path]], Dict[str, Any]]


def _load_module(module_path: Path, module_name: str):
    spec = importlib.util.spec_from_file_location(module_name, module_path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


def _load_protocol_module():
    path = Path(__file__).resolve().parents[1] / "protocol" / "message.py"
    return _load_module(path, "trading_protocol_message")


def _default_stage_runners() -> Dict[str, StageRunner]:
    root = Path(__file__).resolve().parents[1]
    mapping = {
        "A1": ("A1_research/entrypoint.py", "run_a1_research"),
        "A2": ("A2_first-principles/entrypoint.py", "run_a2_first_principles"),
        "A3": ("A3_simulation/entrypoint.py", "run_a3_simulation"),
        "A4": ("A4_validation/entrypoint.py", "run_a4_validation"),
        "A5": ("A5_execution/entrypoint.py", "run_a5_execution"),
        "A6": ("A6_intelligence/entrypoint.py", "run_a6_intelligence"),
        "A9": ("A9_exit/entrypoint.py", "run_a9_exit"),
    }
    runners: Dict[str, StageRunner] = {}
    for stage, (rel_path, fn_name) in mapping.items():
        mod = _load_module(root / rel_path, f"trade_{stage.lower()}_entrypoint")
        runners[stage] = getattr(mod, fn_name)
    return runners


def _transition_message(proto, source: str, target: str, trace_id: str, correlation_id: Optional[str], payload: Dict[str, Any]):
    return proto.build_envelope(
        source=source,
        target=target,
        message_type="REQUEST",
        priority="HIGH",
        loop_type="execution",
        trace_id=trace_id,
        correlation_id=correlation_id,
        timeout_ms=60000,
        payload=payload,
    )


def run_execution_loop(
    payload: Dict[str, Any],
    output_dir: Optional[Path] = None,
    stage_runners: Optional[Dict[str, StageRunner]] = None,
    max_retries: int = 1,
) -> Dict[str, Any]:
    """Run A1->A2->A3->A4->A5->A6->A9 execution loop with fallback hops.

    Per spec:
    - A5 execution result notifies A6 (intelligence monitoring)
    - A9 exit triggers A7 (practice record) via governance transition message
    """
    proto = _load_protocol_module()
    runners = stage_runners or _default_stage_runners()
    trace_id = str(payload.get("trace_id") or "trace-missing")
    correlation_id = payload.get("correlation_id")

    messages = []
    stage_outputs: Dict[str, Dict[str, Any]] = {}
    stage_order = ["A1", "A2", "A3", "A4", "A5"]
    retry_count = 0
    next_input = dict(payload)

    for idx, stage in enumerate(stage_order):
        stage_out = runners[stage](next_input, output_dir=output_dir)
        out = proto.envelope_payload(stage_out)
        out = proto.ensure_contract_fields(
            out,
            producer=f"workflows/trading-decision/{stage}",
        )
        proto.require_contract_fields(out)
        stage_outputs[stage] = out
        next_input.update(out)

        if idx + 1 < len(stage_order):
            messages.append(
                _transition_message(proto, stage, stage_order[idx + 1], trace_id, correlation_id, out)
            )

        if stage == "A4" and out.get("risk_gate") != "PASS" and retry_count < max_retries:
            retry_count += 1
            a3_stage_out = runners["A3"](next_input, output_dir=output_dir)
            a3_out = proto.envelope_payload(a3_stage_out)
            a3_out = proto.ensure_contract_fields(a3_out, producer="workflows/trading-decision/A3")
            proto.require_contract_fields(a3_out)
            stage_outputs["A3_retry"] = a3_out
            next_input.update(a3_out)
            a4_stage_out = runners["A4"](next_input, output_dir=output_dir)
            out = proto.envelope_payload(a4_stage_out)
            out = proto.ensure_contract_fields(out, producer="workflows/trading-decision/A4")
            proto.require_contract_fields(out)
            stage_outputs["A4_retry"] = out
            next_input.update(out)

        if stage == "A5" and out.get("execution_status") == "FAIL" and retry_count < max_retries:
            retry_count += 1
            a4_stage_out = runners["A4"](next_input, output_dir=output_dir)
            a4_out = proto.envelope_payload(a4_stage_out)
            a4_out = proto.ensure_contract_fields(a4_out, producer="workflows/trading-decision/A4")
            proto.require_contract_fields(a4_out)
            stage_outputs["A4_recheck"] = a4_out
            next_input.update(a4_out)
            a5_stage_out = runners["A5"](next_input, output_dir=output_dir)
            out = proto.envelope_payload(a5_stage_out)
            out = proto.ensure_contract_fields(out, producer="workflows/trading-decision/A5")
            proto.require_contract_fields(out)
            stage_outputs["A5_retry"] = out
            next_input.update(out)

    # A5 -> A6: 执行结果通知情报环监控 (spec: A5 -> A6 event trigger)
    a6_input = {
        "trace_id": trace_id,
        "correlation_id": correlation_id,
        "alerts": [
            {
                "source": "execution",
                "severity": "info",
                "risk_score": 0.0,
                "regime_change": False,
            }
        ],
        "signal_shift": 0.0,
    }
    a6_stage_out = runners["A6"](a6_input, output_dir=output_dir)
    a6_out = proto.envelope_payload(a6_stage_out)
    a6_out = proto.ensure_contract_fields(a6_out, producer="workflows/trading-decision/A6")
    proto.require_contract_fields(a6_out)
    stage_outputs["A6"] = a6_out
    messages.append(
        _transition_message(proto, "A5", "A6", trace_id, correlation_id, stage_outputs.get("A5", {}))
    )

    # A9 exit
    a9_stage_out = runners["A9"](next_input, output_dir=output_dir)
    a9_out = proto.envelope_payload(a9_stage_out)
    a9_out = proto.ensure_contract_fields(a9_out, producer="workflows/trading-decision/A9")
    proto.require_contract_fields(a9_out)
    stage_outputs["A9"] = a9_out
    messages.append(_transition_message(proto, "A6", "A9", trace_id, correlation_id, stage_outputs.get("A6", {})))

    # A9 -> A7: 离场触发治理环实践记录 (spec: A9 -> A7 event trigger)
    messages.append(
        proto.build_envelope(
            source="A9",
            target="A7",
            message_type="EVENT",
            priority="MEDIUM",
            loop_type="governance",
            trace_id=trace_id,
            correlation_id=correlation_id,
            timeout_ms=300000,
            payload=a9_out,
        )
    )

    return {
        "trace_id": trace_id,
        "visited_stages": ["A1", "A2", "A3", "A4", "A5", "A6", "A9"],
        "stage_outputs": stage_outputs,
        "messages": messages,
    }
