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


def test_system_loop_runs_three_loops_and_collects_metrics(tmp_path: Path):
    mod = _load_module("workflows/trading-decision/orchestrator/system_loop.py")
    tmod = _load_module("workflows/trading-decision/transports/adapters.py")
    transport = tmod.MockTransport()

    def fake_execution(payload, output_dir=None):
        return {
            "trace_id": payload["trace_id"],
            "visited_stages": ["A1", "A2", "A3", "A4", "A5", "A9"],
            "stage_outputs": {"A9": {"stage_id": "A9", "trace_id": payload["trace_id"]}},
            "messages": [{"header": {"loop_type": "execution"}, "payload": {"stage_id": "A9"}}],
        }

    def fake_intelligence(payload, output_dir=None):
        return {
            "trace_id": payload["trace_id"],
            "route_level": "L1",
            "messages": [{"header": {"loop_type": "intelligence"}, "payload": {"stage_id": "A6"}}],
        }

    def fake_governance(payload, output_dir=None, now_ts=None):
        return {
            "trace_id": payload["trace_id"],
            "visited_stages": ["A7", "A8", "A3"],
            "stage_outputs": {"A8": {"stage_id": "A8", "trace_id": payload["trace_id"]}},
            "messages": [{"header": {"loop_type": "governance"}, "payload": {"stage_id": "A8"}}],
        }

    out = mod.run_system_loop(
        {"trace_id": "trace-sys-1"},
        output_dir=tmp_path,
        transport=transport,
        execution_runner=fake_execution,
        intelligence_runner=fake_intelligence,
        governance_runner=fake_governance,
    )

    assert out["trace_id"] == "trace-sys-1"
    assert set(out["loops"].keys()) == {"execution", "intelligence", "governance"}
    assert out["metrics"]["message_count"] >= 3
    assert out["metrics"]["loop_count"] == 3
    assert "success_rate" in out["metrics"]
    assert "avg_duration_ms" in out["metrics"]
    assert "retry_rate" in out["metrics"]
    assert "failure_distribution" in out["metrics"]
    assert Path(out["metrics_artifact_path"]).exists()
