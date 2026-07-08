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


def test_a6_routes_levels_to_expected_targets(tmp_path: Path):
    mod = _load_module("workflows/trading-decision/A6_intelligence/entrypoint.py")
    out = mod.run_a6_intelligence(
        {
            "trace_id": "trace-a6-p0",
            "alerts": [
                {"risk_score": 0.95, "event_type": "BLACK_SWAN"},
                {"risk_score": 0.75},
                {"regime_change": True, "regime_name": "VOL_SPIKE"},
                {"risk_score": 0.55},
                {"theory_practice_score": 0.6},
            ],
            "signal_shift": 0.33,
        },
        output_dir=tmp_path,
    )
    payload = out["payload"]
    assert out["header"]["source"] == "A6"
    assert payload["alert_count"] == 5
    assert Path(payload["artifact_path"]).exists()
    assert payload["route_summary"]["L0"] >= 1
    assert payload["route_summary"]["L1"] >= 1
    assert payload["route_summary"]["L1.5"] >= 1
    assert payload["route_summary"]["L2"] >= 1
    assert payload["route_summary"]["L3"] >= 1

    targets = {event["header"]["target"] for event in payload["routed_events"]}
    assert {"A9", "A4", "A2", "A1", "A3"}.issubset(targets)
    assert all(event["header"]["loop_type"] == "intelligence" for event in payload["routed_events"])
