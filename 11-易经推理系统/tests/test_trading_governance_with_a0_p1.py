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


# ---------------------------------------------------------------------------
# 1. Governance loop A7→A8→A1/A2/A3 full chain
# ---------------------------------------------------------------------------

def test_governance_loop_runs_a7_then_a8_then_a1(tmp_path: Path):
    """Per spec: governance loop starts with A7(practice), then A8(verification), then routes based on gap_score."""
    mod = _load_module("workflows/trading-decision/orchestrator/governance_loop.py")
    out = mod.run_governance_loop(
        {
            "trace_id": "trace-gov-a1",
            "unrealized_pnl_pct": 1.2,
            "risk_level": "medium",
            "violations": [],
            "hypothesis_score": 0.95,
            "practice_score": 0.40,  # gap = 0.55 → A2 (中度背离)
        },
        output_dir=tmp_path,
    )
    # A7 must be the first visited stage
    assert out["visited_stages"][0] == "A7"
    assert "A7" in out["stage_outputs"]


# ---------------------------------------------------------------------------
# 2. Knowledge-synthesis routing: gap_score → A1/A2/A3
# ---------------------------------------------------------------------------

def test_gap_score_055_routes_to_a2(tmp_path: Path):
    """gap_score 0.5-0.7 should route to A2 (重新分析)."""
    mod = _load_module("workflows/trading-decision/orchestrator/governance_loop.py")
    out = mod.run_governance_loop(
        {
            "trace_id": "trace-gap-a2",
            "unrealized_pnl_pct": 0.5,
            "risk_level": "low",
            "violations": [],
            "hypothesis_score": 0.95,
            "practice_score": 0.40,  # gap = 0.55
        },
        output_dir=tmp_path,
    )
    assert "A2" in out["visited_stages"]


def test_gap_score_080_routes_to_a3(tmp_path: Path):
    """gap_score > 0.7 should route to A3 (策略微调)."""
    mod = _load_module("workflows/trading-decision/orchestrator/governance_loop.py")
    out = mod.run_governance_loop(
        {
            "trace_id": "trace-gap-a3",
            "unrealized_pnl_pct": 0.5,
            "risk_level": "low",
            "violations": [],
            "hypothesis_score": 0.95,
            "practice_score": 0.15,  # gap = 0.80
        },
        output_dir=tmp_path,
    )
    assert "A3" in out["visited_stages"]


def test_gap_score_030_routes_to_a1(tmp_path: Path):
    """gap_score < 0.5 should route to A1 (重启调研)."""
    mod = _load_module("workflows/trading-decision/orchestrator/governance_loop.py")
    out = mod.run_governance_loop(
        {
            "trace_id": "trace-gap-a1",
            "unrealized_pnl_pct": 0.5,
            "risk_level": "low",
            "violations": [],
            "hypothesis_score": 0.90,
            "practice_score": 0.50,  # gap = 0.40
        },
        output_dir=tmp_path,
    )
    assert "A1" in out["visited_stages"]


# ---------------------------------------------------------------------------
# 3. ReputationLedger cumulative penalty
# ---------------------------------------------------------------------------

def test_reputation_cumulative_penalty(tmp_path: Path):
    """Consecutive failures should continuously decrease reputation score."""
    state_mod = _load_module("workflows/trading-decision/orchestrator/state_machine.py")
    ledger = state_mod.ReputationLedger()

    # First failure: A7 REVIEW + gap 0.35
    state_mod.apply_governance_feedback(
        ledger=ledger,
        a7_output={"audit_status": "REVIEW", "violations": [{"id": "v1"}]},
        a8_output={"gap_score": 0.35},
    )
    score_after_1 = ledger.score("A7")

    # Second failure: A7 REVIEW + gap 0.50
    state_mod.apply_governance_feedback(
        ledger=ledger,
        a7_output={"audit_status": "REVIEW", "violations": [{"id": "v2"}]},
        a8_output={"gap_score": 0.50},
    )
    score_after_2 = ledger.score("A7")

    assert score_after_2 < score_after_1


def test_reputation_recovery_after_success(tmp_path: Path):
    """Successful governance should recover reputation score."""
    state_mod = _load_module("workflows/trading-decision/orchestrator/state_machine.py")
    ledger = state_mod.ReputationLedger()

    # Fail first
    state_mod.apply_governance_feedback(
        ledger=ledger,
        a7_output={"audit_status": "REVIEW", "violations": [{"id": "v1"}]},
        a8_output={"gap_score": 0.40},
    )
    score_low = ledger.score("A7")
    assert score_low < 100

    # Then succeed
    state_mod.apply_governance_feedback(
        ledger=ledger,
        a7_output={"audit_status": "PASS", "violations": []},
        a8_output={"gap_score": 0.02},
    )
    score_high = ledger.score("A7")
    assert score_high > score_low
