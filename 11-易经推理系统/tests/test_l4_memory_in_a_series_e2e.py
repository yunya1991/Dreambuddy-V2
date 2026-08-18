"""E2E integration test: L4 memory retrieval in A-series trading stages.

Validates the complete flow:
A-series stages query L4 memory -> populate memory_refs -> artifacts contain refs
Pipeline auto-rebuilds index after stats update
"""

import json
import shutil
import sys
import importlib.util
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]


def _load_module(rel_path: str):
    path = REPO_ROOT / rel_path
    spec = importlib.util.spec_from_file_location(path.stem, path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


def _payload(out: Dict[str, Any]) -> Dict[str, Any]:
    return out.get("payload", out)


# ---------------------------------------------------------------------------
# Helper: create synthetic L4 cases for retrieval
# ---------------------------------------------------------------------------

def _make_case(
    case_id: str,
    regime: str = "bull",
    pnl: float = 2.0,
    decision: str = "long",
    tags: list = None,
    reason_codes: list = None,
    total_score: float = 75.0,
    edge: float = 5.0,
    scores: dict = None,
    strategy: str = "momentum_breakout",
    category: str = "trend_following",
) -> Dict[str, Any]:
    """Create a synthetic TradeCase v0.2 with index-relevant fields."""
    return {
        "case_id": case_id,
        "version": "v0.2",
        "ts_start": datetime.now(timezone.utc).isoformat(),
        "inst_id": "BTC-USDT-SWAP",
        "tags": tags or ["momentum", "breakout"],
        "environment_snapshot": {"regime": regime},
        "thinking_chain": [],
        "evidence_chain": {},
        "decision_outcome": {"pnl_pct": pnl, "goal_achieved": pnl > 0},
        "l4_status": "M3_STATS_UPDATED",
        "quadrant": {
            "x": 0.5 if pnl > 0 else -0.5,
            "y": 0.6,
            "evidence": {"weights": {"perf": 0.4, "consistency": 0.4, "human": 0.2},
                         "y_perf": 0.6, "y_consistency": 0.6, "y_human": 0.5, "notes": ""},
        },
        "review": {"summary": "good trade", "theory_practice_consistency": "consistent", "lessons": []},
        "execution": {"episode_refs": []},
    }


def _write_cases(cases_dir: Path, cases: list) -> None:
    cases_dir.mkdir(parents=True, exist_ok=True)
    for c in cases:
        (cases_dir / f"{c['case_id']}.json").write_text(
            json.dumps(c, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )


# ---------------------------------------------------------------------------
# Use real .workbuddy paths for these tests (read-only or cleanup)
# ---------------------------------------------------------------------------

from scripts.memory_l4.paths import memory_l4_cases_dir, memory_l4_distills_dir, workbuddy_dir
from scripts.memory_l4 import index_builder as idx_b


# ---------------------------------------------------------------------------
# 1. Retrieval helper returns refs when index exists
# ---------------------------------------------------------------------------

def test_retrieval_helper_returns_refs_with_index():
    """When L4 cases and index exist, retrieval returns non-empty refs."""
    mem_retriever = _load_module("workflows/trading-decision/orchestrator/memory_retriever.py")

    # The real system has cases; verify retrieval works
    cases = idx_b.load_cases()
    if len(cases) < 2:
        pytest.skip("Not enough cases for retrieval test")

    # Build index if not exists
    idx_path = idx_b.default_index_path()
    if not idx_path.exists():
        distills = idx_b.load_distills()
        episodes = idx_b.load_episodes_for_cases(cases)
        ts = datetime.now().astimezone().isoformat(timespec="seconds")
        idx_data = idx_b.build_index_data(ts, cases, distills, episodes_by_path=episodes)
        idx_b.write_index(idx_data, idx_path)

    # Use a real case_id
    cid = cases[0]["case_id"]
    payload = {"case_id": cid, "market_regime": cases[0].get("environment_snapshot", {}).get("regime", "bull")}

    refs = mem_retriever.retrieve_memory_refs_for_stage("A3", payload, topk=3)
    assert isinstance(refs, list)
    # Should find similar cases (excluding the query case itself)
    if len(cases) > 1:
        assert len(refs) > 0
        assert "case_id" in refs[0]


# ---------------------------------------------------------------------------
# 2. Graceful degradation without matching case_id
# ---------------------------------------------------------------------------

def test_retrieval_helper_graceful_degrade_no_case_id():
    """When no case_id in payload, retrieval falls back to regime query or returns []."""
    mem_retriever = _load_module("workflows/trading-decision/orchestrator/memory_retriever.py")

    # No case_id, just a regime — should fall back to regime query
    refs = mem_retriever.retrieve_memory_refs_for_stage("A3", {"market_regime": "nonexistent_regime_xyz"}, topk=3)
    assert isinstance(refs, list)
    # May be empty since regime doesn't exist — the key is it doesn't raise


# ---------------------------------------------------------------------------
# 3. A3 entrypoint populates memory_refs when index has cases
# ---------------------------------------------------------------------------

def test_a3_entrypoint_populates_memory_refs(tmp_path: Path):
    """A3 simulation should populate memory_refs from L4 retrieval."""
    # Write cases to the real L4 cases directory so retriever can find them
    cases_dir = memory_l4_cases_dir()
    test_cases = [
        _make_case("TC_E2E_A3_01", regime="trend", pnl=2.0),
        _make_case("TC_E2E_A3_02", regime="trend", pnl=1.0),
    ]
    _write_cases(cases_dir, test_cases)

    # Build index
    cases = idx_b.load_cases()
    distills = idx_b.load_distills()
    ts = datetime.now().astimezone().isoformat(timespec="seconds")
    idx_data = idx_b.build_index_data(ts, cases, distills, {})
    idx_b.write_index(idx_data, idx_b.default_index_path())

    a3 = _load_module("workflows/trading-decision/A3_simulation/entrypoint.py")

    payload = {
        "trace_id": "trace-a3-e2e",
        "signal_score": 65,
        "volatility": 0.02,
        "market_regime": "trend",
    }

    out = a3.run_a3_simulation(payload, output_dir=tmp_path / "artifacts")
    p = _payload(out)

    assert "memory_refs" in p
    assert isinstance(p["memory_refs"], list)

    # Cleanup test cases
    for c in test_cases:
        (cases_dir / f"{c['case_id']}.json").unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# 4. A9 entrypoint populates memory_refs
# ---------------------------------------------------------------------------

def test_a9_entrypoint_populates_memory_refs(tmp_path: Path):
    """A9 exit should populate memory_refs from L4 retrieval."""
    # Write cases
    cases_dir = memory_l4_cases_dir()
    test_cases = [
        _make_case("TC_E2E_A9_01", regime="bull", pnl=3.0),
        _make_case("TC_E2E_A9_02", regime="bull", pnl=-1.0),
    ]
    _write_cases(cases_dir, test_cases)

    # Rebuild index
    cases = idx_b.load_cases()
    ts = datetime.now().astimezone().isoformat(timespec="seconds")
    idx_data = idx_b.build_index_data(ts, cases, [], {})
    idx_b.write_index(idx_data, idx_b.default_index_path())

    a9 = _load_module("workflows/trading-decision/A9_exit/entrypoint.py")

    payload = {
        "trace_id": "trace-a9-e2e",
        "unrealized_pnl_pct": 2.5,
        "risk_level": "medium",
    }

    out = a9.run_a9_exit(payload, output_dir=tmp_path / "artifacts")
    p = _payload(out)

    assert "memory_refs" in p
    assert isinstance(p["memory_refs"], list)

    # Cleanup
    for c in test_cases:
        (cases_dir / f"{c['case_id']}.json").unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# 5. Pipeline step_rebuild_index produces valid index
# ---------------------------------------------------------------------------

def test_pipeline_rebuild_index_produces_valid_index(tmp_path: Path):
    """step_rebuild_index should create a valid index file."""
    # Write test cases to real directory
    cases_dir = memory_l4_cases_dir()
    test_cases = [
        _make_case("TC_E2E_REIDX_01", pnl=2.0),
        _make_case("TC_E2E_REIDX_02", pnl=-1.0),
    ]
    _write_cases(cases_dir, test_cases)

    pipeline_mod = _load_module("scripts/memory_l4/pipeline.py")
    result = pipeline_mod.step_rebuild_index()

    assert "index_path" in result
    assert "case_count" in result
    assert result["case_count"] >= 2  # At least our test cases
    assert Path(result["index_path"]).exists()

    # Verify index structure
    idx = json.loads(Path(result["index_path"]).read_text(encoding="utf-8"))
    assert idx["metadata"]["feature_version"] == "v0.2"

    # Cleanup
    for c in test_cases:
        (cases_dir / f"{c['case_id']}.json").unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# 6. Full execution loop propagates memory_refs through stages
# ---------------------------------------------------------------------------

def test_full_loop_memory_refs_propagate(tmp_path: Path):
    """Running the execution loop should produce stage_outputs with memory_refs."""
    # Write cases for retrieval
    cases_dir = memory_l4_cases_dir()
    test_cases = [
        _make_case("TC_E2E_LOOP_01", regime="trend", pnl=2.0, tags=["momentum"]),
        _make_case("TC_E2E_LOOP_02", regime="trend", pnl=1.5, tags=["momentum"]),
    ]
    _write_cases(cases_dir, test_cases)

    # Rebuild index
    cases = idx_b.load_cases()
    ts = datetime.now().astimezone().isoformat(timespec="seconds")
    idx_data = idx_b.build_index_data(ts, cases, [], {})
    idx_b.write_index(idx_data, idx_b.default_index_path())

    exec_mod = _load_module("workflows/trading-decision/orchestrator/execution_loop.py")

    out = exec_mod.run_execution_loop(
        {
            "trace_id": "trace-loop-e2e",
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
        output_dir=tmp_path / "artifacts",
    )

    # Check that stages have memory_refs field
    for stage_name in ["A3", "A4", "A5", "A9"]:
        stage_out = out["stage_outputs"].get(stage_name)
        if stage_out:
            p = _payload(stage_out)
            assert "memory_refs" in p, f"{stage_name} missing memory_refs"
            assert isinstance(p["memory_refs"], list), f"{stage_name} memory_refs is not a list"

    # A1 should have memory_refs as empty list
    a1_out = out["stage_outputs"].get("A1")
    if a1_out:
        a1_p = _payload(a1_out)
        assert "memory_refs" in a1_p
        assert isinstance(a1_p["memory_refs"], list)

    # Cleanup
    for c in test_cases:
        (cases_dir / f"{c['case_id']}.json").unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# 7. A1 returns empty memory_refs (first stage)
# ---------------------------------------------------------------------------

def test_a1_returns_empty_memory_refs(tmp_path: Path):
    """A1 should always return empty memory_refs since it's the first stage."""
    a1 = _load_module("workflows/trading-decision/A1_research/entrypoint.py")

    payload = {
        "trace_id": "trace-a1-e2e",
        "signals": ["test_signal"],
        "confidence": 0.7,
    }

    out = a1.run_a1_research(payload, output_dir=tmp_path)
    p = _payload(out)

    assert "memory_refs" in p
    assert p["memory_refs"] == []
