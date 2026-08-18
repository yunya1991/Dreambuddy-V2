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


def test_governance_loop_runs_a7_a8_and_routes_to_a3(tmp_path: Path):
    mod = _load_module("workflows/trading-decision/orchestrator/governance_loop.py")

    out = mod.run_governance_loop(
        {
            "trace_id": "trace-gov-1",
            "unrealized_pnl_pct": 1.2,
            "risk_level": "medium",
            "violations": [],
            "hypothesis_score": 0.95,
            "practice_score": 0.10,  # gap = 0.85 → A3
        },
        output_dir=tmp_path,
    )

    assert out["trace_id"] == "trace-gov-1"
    assert out["visited_stages"][:2] == ["A7", "A8"]
    assert out["visited_stages"][-1] == "A3"
    assert {"A7", "A8", "A3"}.issubset(set(out["stage_outputs"].keys()))
    assert any(m["header"]["loop_type"] == "governance" for m in out["messages"])


def test_governance_event_trigger_routes_by_gap(tmp_path: Path):
    mod = _load_module("workflows/trading-decision/orchestrator/governance_loop.py")
    out = mod.run_governance_loop(
        {
            "trace_id": "trace-gov-2",
            "unrealized_pnl_pct": 0.5,
            "risk_level": "low",
            "violations": [],
            "hypothesis_score": 0.88,
            "practice_score": 0.80,  # gap = 0.08 → A1
        },
        output_dir=tmp_path,
    )
    assert "A8" in out["visited_stages"]
    assert "A1" in out["visited_stages"]
    assert "reputation" in out


def test_governance_loop_always_runs_a8(tmp_path: Path):
    """Governance loop always runs A8 after A7 for 知行合一 check."""
    mod = _load_module("workflows/trading-decision/orchestrator/governance_loop.py")
    out = mod.run_governance_loop(
        {
            "trace_id": "trace-default-a8",
            "unrealized_pnl_pct": 0.3,
            "risk_level": "low",
            "violations": [],
        },
        output_dir=tmp_path,
    )
    assert "A8" in out["visited_stages"]
    assert "reputation" in out
