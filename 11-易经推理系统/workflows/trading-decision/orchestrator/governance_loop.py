from __future__ import annotations

import importlib.util
from datetime import datetime, timezone
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


def _load_state_module():
    path = Path(__file__).resolve().parent / "state_machine.py"
    return _load_module(path, "trading_state_machine")


def _default_stage_runners() -> Dict[str, StageRunner]:
    root = Path(__file__).resolve().parents[1]
    mapping = {
        "A1": ("A1_research/entrypoint.py", "run_a1_research"),
        "A2": ("A2_first-principles/entrypoint.py", "run_a2_first_principles"),
        "A3": ("A3_simulation/entrypoint.py", "run_a3_simulation"),
        "A7": ("A7_audit/entrypoint.py", "run_a7_audit"),
        "A8": ("A8_theory-practice/entrypoint.py", "run_a8_theory_practice"),
    }
    runners: Dict[str, StageRunner] = {}
    for stage, (rel_path, fn_name) in mapping.items():
        mod = _load_module(root / rel_path, f"trade_{stage.lower()}_entrypoint_gov")
        runners[stage] = getattr(mod, fn_name)
    return runners


def _to_dt(ts: str) -> datetime:
    return datetime.fromisoformat(ts.replace("Z", "+00:00"))


def should_trigger_a8(now_ts: str) -> bool:
    dt = _to_dt(now_ts)
    return dt.hour == 14 and dt.minute == 0


def _transition_message(proto, source: str, target: str, trace_id: str, correlation_id: Optional[str], payload: Dict[str, Any]):
    return proto.build_envelope(
        source=source,
        target=target,
        message_type="REQUEST",
        priority="MEDIUM",
        loop_type="governance",
        trace_id=trace_id,
        correlation_id=correlation_id,
        timeout_ms=300000,
        payload=payload,
    )


def run_governance_loop(
    payload: Dict[str, Any],
    output_dir: Optional[Path] = None,
    stage_runners: Optional[Dict[str, StageRunner]] = None,
    now_ts: Optional[str] = None,
) -> Dict[str, Any]:
    proto = _load_protocol_module()
    state_mod = _load_state_module()
    runners = stage_runners or _default_stage_runners()
    trace_id = str(payload.get("trace_id") or "trace-missing")
    correlation_id = payload.get("correlation_id")
    ledger = state_mod.ReputationLedger()

    stage_outputs: Dict[str, Dict[str, Any]] = {}
    messages = []
    visited_stages = []
    next_input = dict(payload)

    # A7: 实践记录 — 治理环入口，A9 离场触发
    a7_out = proto.envelope_payload(runners["A7"](next_input, output_dir=output_dir))
    a7_out = proto.ensure_contract_fields(a7_out, producer="workflows/trading-decision/A7")
    proto.require_contract_fields(a7_out)
    stage_outputs["A7"] = a7_out
    visited_stages.append("A7")
    messages.append(_transition_message(proto, "A7", "A8", trace_id, correlation_id, a7_out))
    next_input.update(a7_out)

    # A8: 理论验证 — 知行合一检查，根据 gap_score 路由到 A1/A2/A3
    a8_out = proto.envelope_payload(runners["A8"](next_input, output_dir=output_dir))
    a8_out = proto.ensure_contract_fields(a8_out, producer="workflows/trading-decision/A8")
    proto.require_contract_fields(a8_out)
    stage_outputs["A8"] = a8_out
    visited_stages.append("A8")
    next_input.update(a8_out)

    # 根据 gap_score 路由到不同修正阶段
    gap = float(a8_out.get("gap_score") or 0.0)
    if gap < 0.5:
        target = "A1"  # 严重背离，重启调研
    elif gap <= 0.7:
        target = "A2"  # 中度背离，重新分析
    else:
        target = "A3"  # 轻微背离，策略微调

    messages.append(_transition_message(proto, "A8", target, trace_id, correlation_id, a8_out))
    target_out = proto.envelope_payload(runners[target](next_input, output_dir=output_dir))
    target_out = proto.ensure_contract_fields(
        target_out,
        producer=f"workflows/trading-decision/{target}",
    )
    proto.require_contract_fields(target_out)
    stage_outputs[target] = target_out
    visited_stages.append(target)
    reputation = state_mod.apply_governance_feedback(
        ledger=ledger,
        a7_output=a7_out,
        a8_output=a8_out,
    )

    return {
        "trace_id": trace_id,
        "visited_stages": visited_stages,
        "stage_outputs": stage_outputs,
        "messages": messages,
        "reputation": reputation,
    }
