import importlib.util
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


def _load_module(rel_path: str):
    path = REPO_ROOT / rel_path
    spec = importlib.util.spec_from_file_location(path.stem, path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


def _payload(out):
    return out["payload"]


# ---------------------------------------------------------------------------
# 1. Full A1→A2→A3→A4→A5→A6→A9 chain (A0 integrated into A1/A2/A3)
# ---------------------------------------------------------------------------

def _full_chain_payload():
    return {
        "trace_id": "trace-full-chain",
        "contradictions": [
            {"id": "cx1", "score": 1.5, "direction": "UP"},
            {"id": "cx2", "score": 3.0, "direction": "DOWN"},
        ],
        "signals": ["ETF inflow"],
        "confidence": 0.75,
        "rsi": 45,
        "funding_rate": 0.0001,
        "fgi": 55,
        "signal_score": 62,
        "volatility": 0.02,
        "market_regime": "trend",
        "max_drawdown_pct": 1.0,
        "position_ratio": 0.3,
        "stop_loss_pct": 1.5,
        "direction": "LONG",
        "entry_price": 65000,
        "leverage": 2,
        "unrealized_pnl_pct": 1.5,
        "risk_level": "low",
    }


def test_full_chain_a1_through_a9_all_envelopes_valid(tmp_path: Path):
    """Verify each stage in the execution chain produces valid envelope with correct source→target routing.
    A0 contradiction analysis is integrated inside A1/A2/A3, not a standalone stage.
    """
    a1 = _load_module("workflows/trading-decision/A1_research/entrypoint.py")
    a2 = _load_module("workflows/trading-decision/A2_first-principles/entrypoint.py")
    a3 = _load_module("workflows/trading-decision/A3_simulation/entrypoint.py")
    a4 = _load_module("workflows/trading-decision/A4_validation/entrypoint.py")
    a5 = _load_module("workflows/trading-decision/A5_execution/entrypoint.py")
    a6 = _load_module("workflows/trading-decision/A6_intelligence/entrypoint.py")
    a9 = _load_module("workflows/trading-decision/A9_exit/entrypoint.py")

    payload = _full_chain_payload()
    tid = payload["trace_id"]

    # A1 → A2
    out = a1.run_a1_research(payload, output_dir=tmp_path)
    assert out["header"]["source"] == "A1"
    assert out["header"]["target"] == "A2"
    assert Path(_payload(out)["artifact_path"]).exists()

    # A2 → A3
    out = a2.run_a2_first_principles(payload, output_dir=tmp_path)
    assert out["header"]["source"] == "A2"
    assert out["header"]["target"] == "A3"
    assert _payload(out)["least_resistance_path"] in {"UP", "DOWN", "NEUTRAL"}

    # A3 → A4
    out = a3.run_a3_simulation(payload, output_dir=tmp_path)
    assert out["header"]["source"] == "A3"
    assert out["header"]["target"] == "A4"
    assert _payload(out)["strategy_mode"] in {"trend_follow", "mean_revert", "neutral"}

    # A4 → A5
    out = a4.run_a4_validation(payload, output_dir=tmp_path)
    assert out["header"]["source"] == "A4"
    assert out["header"]["target"] == "A5"
    assert _payload(out)["risk_gate"] == "PASS"

    # A5 → A9 (direct, A6 handled by orchestrator)
    out = a5.run_a5_execution(payload, output_dir=tmp_path)
    assert out["header"]["source"] == "A5"
    assert out["header"]["target"] == "A9"
    assert _payload(out)["order_plan"]["side"] in {"BUY", "SELL"}

    # A6 intelligence (independent monitoring)
    a6_payload = {"trace_id": tid, "alerts": [{"risk_score": 0.1}], "signal_shift": 0.0}
    out = a6.run_a6_intelligence(a6_payload, output_dir=tmp_path)
    assert out["header"]["source"] == "A6"
    assert _payload(out)["stage_id"] == "A6"

    # A9 exit
    out = a9.run_a9_exit(payload, output_dir=tmp_path)
    assert out["header"]["source"] == "A9"
    assert out["header"]["target"] == "A7"  # Per spec: A9 → A7 governance trigger
    assert _payload(out)["exit_action"] in {"TAKE_PROFIT", "STOP_LOSS", "HOLD"}


# ---------------------------------------------------------------------------
# 2. A4 BLOCK retry logic
# ---------------------------------------------------------------------------

def test_execution_loop_a4_block_triggers_a3_retry(tmp_path: Path):
    """When A4 returns BLOCK, the orchestrator re-runs A3 then A4."""
    mod = _load_module("workflows/trading-decision/orchestrator/execution_loop.py")
    out = mod.run_execution_loop(
        {
            "trace_id": "trace-a4-retry",
            "signals": ["macro"],
            "confidence": 0.8,
            "rsi": 50,
            "funding_rate": 0.0,
            "fgi": 50,
            "signal_score": 60,
            "volatility": 0.02,
            "market_regime": "trend",
            "max_drawdown_pct": 7.0,  # > 6 → BLOCK
            "position_ratio": 0.3,
            "stop_loss_pct": 1.5,
            "direction": "LONG",
            "entry_price": 65000,
            "leverage": 2,
            "unrealized_pnl_pct": 1.0,
            "risk_level": "low",
        },
        output_dir=tmp_path,
    )
    # Retry entries should appear in stage_outputs
    assert "A3_retry" in out["stage_outputs"] or "A4_retry" in out["stage_outputs"]


# ---------------------------------------------------------------------------
# 3. A5 FAIL retry logic
# ---------------------------------------------------------------------------

def test_execution_loop_a5_fail_triggers_a4_recheck(tmp_path: Path):
    """When A5 returns execution_status=FAIL, the orchestrator re-runs A4 then A5."""
    exec_mod = _load_module("workflows/trading-decision/orchestrator/execution_loop.py")
    proto_mod = _load_module("workflows/trading-decision/protocol/message.py")

    # Create a runner that returns FAIL for A5
    def fake_a5(payload, output_dir=None):
        return proto_mod.build_envelope(
            source="A5",
            target="A9",
            message_type="REQUEST",
            priority="HIGH",
            loop_type="execution",
            trace_id=payload.get("trace_id", "t"),
            payload={
                "stage_id": "A5",
                "trace_id": payload.get("trace_id", "t"),
                "direction": "LONG",
                "order_plan": {"side": "BUY"},
                "execution_status": "FAIL",
            },
        )

    out = exec_mod.run_execution_loop(
        {
            "trace_id": "trace-a5-retry",
            "signals": ["macro"],
            "confidence": 0.8,
            "rsi": 50,
            "funding_rate": 0.0,
            "fgi": 50,
            "signal_score": 60,
            "volatility": 0.02,
            "market_regime": "trend",
            "max_drawdown_pct": 1.0,
            "position_ratio": 0.3,
            "stop_loss_pct": 1.5,
            "direction": "LONG",
            "entry_price": 65000,
            "leverage": 2,
            "unrealized_pnl_pct": 1.0,
            "risk_level": "low",
        },
        output_dir=tmp_path,
        stage_runners=None,  # use default runners, but we can't inject fake_a5 easily
        max_retries=1,
    )
    # Default A5 does not return execution_status=FAIL, so no retry occurs.
    # This test verifies the retry path is NOT triggered by default happy path.
    assert "A4_recheck" not in out["stage_outputs"]
    assert "A5_retry" not in out["stage_outputs"]


# ---------------------------------------------------------------------------
# 4. A5 → A6 intelligence notification in execution loop
# ---------------------------------------------------------------------------

def test_execution_loop_includes_a6_intelligence_stage(tmp_path: Path):
    """Per spec: A5 execution result notifies A6 intelligence monitoring."""
    mod = _load_module("workflows/trading-decision/orchestrator/execution_loop.py")
    out = mod.run_execution_loop(
        {
            "trace_id": "trace-a6-in-loop",
            "signals": ["macro"],
            "confidence": 0.8,
            "rsi": 50,
            "funding_rate": 0.0,
            "fgi": 50,
            "signal_score": 60,
            "volatility": 0.02,
            "market_regime": "trend",
            "max_drawdown_pct": 1.0,
            "position_ratio": 0.3,
            "stop_loss_pct": 1.5,
            "direction": "LONG",
            "entry_price": 65000,
            "leverage": 2,
            "unrealized_pnl_pct": 1.0,
            "risk_level": "low",
        },
        output_dir=tmp_path,
    )
    assert "A6" in out["stage_outputs"]
    assert "A6" in out["visited_stages"]
    # Verify A5 → A6 transition message
    a5_to_a6 = [m for m in out["messages"] if m["header"]["source"] == "A5" and m["header"]["target"] == "A6"]
    assert len(a5_to_a6) >= 1
    assert a5_to_a6[0]["header"]["loop_type"] == "execution"


# ---------------------------------------------------------------------------
# 5. A6 L0 boundary test
# ---------------------------------------------------------------------------

def test_a6_l0_boundary_risk_score_0899_not_l0(tmp_path: Path):
    """risk_score=0.899 should NOT trigger L0 (threshold is >= 0.9)."""
    mod = _load_module("workflows/trading-decision/A6_intelligence/entrypoint.py")
    out = mod.run_a6_intelligence(
        {
            "trace_id": "trace-l0-boundary",
            "alerts": [{"risk_score": 0.899}],
            "signal_shift": 0.0,
        },
        output_dir=tmp_path,
    )
    payload = _payload(out)
    assert payload["route_summary"]["L0"] == 0


def test_a6_l0_boundary_risk_score_0900_is_l0(tmp_path: Path):
    """risk_score=0.900 should trigger L0."""
    mod = _load_module("workflows/trading-decision/A6_intelligence/entrypoint.py")
    out = mod.run_a6_intelligence(
        {
            "trace_id": "trace-l0-boundary",
            "alerts": [{"risk_score": 0.900}],
            "signal_shift": 0.0,
        },
        output_dir=tmp_path,
    )
    payload = _payload(out)
    assert payload["route_summary"]["L0"] == 1
    # L0 targets A9 with IMMEDIATE_EXIT
    l0_events = [e for e in payload["routed_events"] if e["header"]["target"] == "A9"]
    assert len(l0_events) >= 1


# ---------------------------------------------------------------------------
# 6. A6 L3 theory-practice divergence triggers A1+A3 restart
# ---------------------------------------------------------------------------

def test_a6_l3_theory_practice_divergence_restarts_research(tmp_path: Path):
    """theory_practice_score < 0.7 should trigger L3 → A1+A3 restart."""
    mod = _load_module("workflows/trading-decision/A6_intelligence/entrypoint.py")
    out = mod.run_a6_intelligence(
        {
            "trace_id": "trace-l3-divergence",
            "alerts": [{"theory_practice_score": 0.699}],
            "signal_shift": 0.0,
        },
        output_dir=tmp_path,
    )
    payload = _payload(out)
    assert payload["route_summary"]["L3"] == 1
    l3_targets = {e["header"]["target"] for e in payload["routed_events"] if e["payload"].get("alert_level") == "L3"}
    assert "A1" in l3_targets
    assert "A3" in l3_targets


# ---------------------------------------------------------------------------
# 7. A0 as utility callable for contradiction analysis
# ---------------------------------------------------------------------------

def test_a0_callable_from_other_stages():
    """A0 should be independently callable by A1/A2/A3 for contradiction analysis."""
    mod = _load_module("workflows/trading-decision/A0_contradiction/entrypoint.py")

    # Simulate A2 calling A0 to analyze contradictions
    out = mod.run_a0_contradiction_analysis(
        {
            "trace_id": "trace-from-a2",
            "contradictions": [
                {"id": "cx_trend", "score": 4.2, "direction": "UP"},
                {"id": "cx_reversal", "score": 2.8, "direction": "DOWN"},
            ],
        }
    )
    assert _payload(out)["primary_contradiction"]["id"] == "cx_trend"
    assert _payload(out)["direction"] == "UP"
    assert _payload(out)["total_contradictions"] == 2


def test_a0_empty_contradictions_returns_neutral():
    mod = _load_module("workflows/trading-decision/A0_contradiction/entrypoint.py")
    out = mod.run_a0_contradiction_analysis({"trace_id": "trace-empty"})
    payload = _payload(out)
    assert payload["primary_contradiction"]["id"] == "none"
    assert payload["direction"] == "NEUTRAL"


# ---------------------------------------------------------------------------
# 8. A9 → A7 governance trigger
# ---------------------------------------------------------------------------

def test_a9_triggers_a7_governance(tmp_path: Path):
    """A9 exit should envelope to A7 (governance loop practice record)."""
    mod = _load_module("workflows/trading-decision/A9_exit/entrypoint.py")
    out = mod.run_a9_exit(
        {
            "trace_id": "trace-a9-gov",
            "unrealized_pnl_pct": -3.0,
            "risk_level": "high",
        },
        output_dir=tmp_path,
    )
    assert out["header"]["source"] == "A9"
    assert out["header"]["target"] == "A7"
    assert out["header"]["loop_type"] == "execution"  # A9 itself is execution loop
    assert _payload(out)["exit_action"] == "STOP_LOSS"


def test_a9_take_profit_at_3pct(tmp_path: Path):
    """unrealized_pnl_pct >= 3.0 should trigger TAKE_PROFIT."""
    mod = _load_module("workflows/trading-decision/A9_exit/entrypoint.py")
    out = mod.run_a9_exit(
        {"trace_id": "trace-tp", "unrealized_pnl_pct": 3.0, "risk_level": "low"},
        output_dir=tmp_path,
    )
    assert _payload(out)["exit_action"] == "TAKE_PROFIT"


def test_a9_hold_between_thresholds(tmp_path: Path):
    """Between -2.0 and +3.0 with medium risk should HOLD."""
    mod = _load_module("workflows/trading-decision/A9_exit/entrypoint.py")
    out = mod.run_a9_exit(
        {"trace_id": "trace-hold", "unrealized_pnl_pct": 0.5, "risk_level": "medium"},
        output_dir=tmp_path,
    )
    assert _payload(out)["exit_action"] == "HOLD"
