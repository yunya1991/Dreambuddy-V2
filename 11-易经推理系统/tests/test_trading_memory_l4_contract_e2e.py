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


def test_trading_memory_l4_contract_flow_returns_standard_contract(tmp_path: Path):
    mod = _load_module("workflows/trading-decision/orchestrator/memory_l4_contract_bridge.py")
    out = mod.run_trading_memory_l4_contract(
        {
            "trace_id": "trace-l4-e2e-1",
            "stage_id": "A6",
            "constraint_version": "v0.1",
            "schema_version": "2.0",
            "memory_refs": ["mem-root"],
            "evidence_refs": ["artifacts/trading/a6.json"],
            "memory_events": [
                {
                    "agent_id": "A6",
                    "payload": {
                        "memory_id": "mem-001",
                        "kind": "alert",
                        "evidence_refs": ["artifacts/trading/a6.json"],
                    },
                }
            ],
            "risk_signals": [{"risk_signal_id": "rs-1", "confidence": 0.8}],
            "source_market": "CRYPTO",
            "target_market": "HK",
        },
        output_dir=tmp_path,
    )
    required = {
        "stage_id",
        "trace_id",
        "constraint_version",
        "memory_refs",
        "evidence_refs",
        "producer",
        "schema_version",
    }
    assert required.issubset(out.keys())
    assert out["trace_id"] == "trace-l4-e2e-1"
    assert isinstance(out["memory_refs"], list)
    assert isinstance(out["evidence_refs"], list)
    assert {"graph", "migration", "meta"}.issubset(out["l4_outputs"].keys())
