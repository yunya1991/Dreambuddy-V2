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


def test_trace_index_and_replay_summary():
    mod = _load_module("workflows/trading-decision/orchestrator/replay.py")
    events = [
        {"trace_id": "trace-r1", "stage_id": "A1", "timestamp": "2026-05-11T14:00:00+00:00"},
        {"trace_id": "trace-r1", "stage_id": "A2", "timestamp": "2026-05-11T14:00:01+00:00"},
        {"trace_id": "trace-r1", "stage_id": "A4", "timestamp": "2026-05-11T14:00:03+00:00", "retry": True},
    ]
    idx = mod.build_trace_index(events)
    assert "trace-r1" in idx

    summary = mod.replay_trace("trace-r1", idx)
    assert summary["trace_id"] == "trace-r1"
    assert summary["stage_count"] == 3
    assert summary["retry_count"] == 1
    assert summary["duration_ms"] >= 3000
