import importlib.util
from pathlib import Path


REPO_ROOT = Path("/Users/zhangjiangtao/WorkBuddy/dream-multiskill-v2")


def _load_module(rel_path: str):
    path = REPO_ROOT / rel_path
    spec = importlib.util.spec_from_file_location(path.stem, path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


def test_execution_orchestrator_runs_a1_to_a9_and_emits_messages(tmp_path: Path):
    mod = _load_module("workflows/trading-decision/orchestrator/execution_loop.py")
    out = mod.run_execution_loop(
        {
            "trace_id": "trace-exec-p0",
            "signals": ["macro"],
            "confidence": 0.8,
            "rsi": 52,
            "funding_rate": 0.0,
            "fgi": 55,
            "signal_score": 62,
            "volatility": 0.02,
            "market_regime": "trend",
            "max_drawdown_pct": 1.2,
            "position_ratio": 0.25,
            "stop_loss_pct": 1.5,
            "direction": "LONG",
            "entry_price": 65000,
            "leverage": 2,
            "unrealized_pnl_pct": 1.0,
            "risk_level": "low",
        },
        output_dir=tmp_path,
    )
    assert out["trace_id"] == "trace-exec-p0"
    assert out["visited_stages"][-1] == "A9"
    # Per spec: A5 -> A6 -> A9, so A6 must be in visited stages
    assert {"A1", "A2", "A3", "A4", "A5", "A6", "A9"}.issubset(set(out["stage_outputs"].keys()))
    assert len(out["messages"]) >= 6
    assert all("header" in m and "payload" in m for m in out["messages"])
    assert all("constraint_version" in s for s in out["stage_outputs"].values())
    # Verify A9 -> A7 governance transition message exists
    a9_to_a7 = [m for m in out["messages"] if m["header"]["source"] == "A9" and m["header"]["target"] == "A7"]
    assert len(a9_to_a7) == 1
    assert a9_to_a7[0]["header"]["loop_type"] == "governance"

