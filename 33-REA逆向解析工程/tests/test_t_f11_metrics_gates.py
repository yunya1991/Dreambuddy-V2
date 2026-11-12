"""SPEC-33-F T-F11：metrics 阈值门禁与历史趋势（RED）。"""

from __future__ import annotations

import json
import sys
from pathlib import Path

_REA_ROOT = Path(__file__).resolve().parents[1]
if str(_REA_ROOT) not in sys.path:
    sys.path.insert(0, str(_REA_ROOT))

from adapters.metrics_adapter import apply_metrics_policy  # noqa: E402


def _report() -> dict:
    return {
        "section": "metrics",
        "complexity": {"max_cc": 12.0, "avg_cc": 3.5, "top": []},
        "functions": [],
        "dead_code": [{"symbol": "unused"}, {"symbol": "dead"}],
        "duplication": {"ratio": 0.075, "blocks": 2, "lines": 20},
        "degraded": False,
        "evidence": [{"result": "metrics summary", "level": "observation"}],
        "known_gaps": [],
    }


def _config(tmp_path: Path, thresholds: dict[str, float]) -> str:
    path = tmp_path / "rea_metrics.json"
    path.write_text(json.dumps({"thresholds": thresholds}), encoding="utf-8")
    return str(path)


def _gate_evidence(report: dict) -> list[dict]:
    return [
        item
        for item in report["evidence"]
        if (item.get("provenance") or {}).get("analysis") == "metrics_gate"
    ]


def test_no_config_is_noop() -> None:
    report = _report()
    assert apply_metrics_policy(report) == report
    assert "gates" not in report
    assert "trend" not in report


def test_threshold_violations_emit_evidence(tmp_path: Path) -> None:
    config = _config(tmp_path, {"max_cc": 10, "dead_code": 1, "duplication_ratio": 0.05})
    report = apply_metrics_policy(_report(), config_path=config)

    assert report["gates"]["status"] == "fail"
    violations = {item["metric"]: item for item in report["gates"]["violations"]}
    assert violations["max_cc"] == {"metric": "max_cc", "value": 12.0, "threshold": 10.0}
    assert violations["dead_code"]["value"] == 2.0
    assert violations["duplication_ratio"]["value"] == 0.075
    evidence = _gate_evidence(report)
    assert len(evidence) == 3
    assert evidence[0]["level"] == "derivation"
    assert evidence[0]["provenance"]["metric"] == "max_cc"
    assert evidence[0]["provenance"]["value"] == 12.0
    assert evidence[0]["provenance"]["threshold"] == 10.0


def test_thresholds_pass_without_gate_evidence(tmp_path: Path) -> None:
    config = _config(tmp_path, {"max_cc": 20, "avg_cc": 4, "dead_code": 2})
    report = apply_metrics_policy(_report(), config_path=config)

    assert report["gates"] == {"status": "pass", "violations": []}
    assert _gate_evidence(report) == []


def test_history_trend_from_saved_snapshot(tmp_path: Path) -> None:
    previous = _report()
    previous["complexity"]["max_cc"] = 10.0
    previous["complexity"]["avg_cc"] = 4.0
    previous["dead_code"] = []
    previous["duplication"]["ratio"] = 0.075
    history = tmp_path / "previous_metrics.json"
    history.write_text(json.dumps({"report": previous}), encoding="utf-8")

    report = apply_metrics_policy(_report(), history_path=str(history))

    assert report["trend"]["max_cc"] == {
        "current": 12.0,
        "previous": 10.0,
        "delta": 2.0,
        "direction": "up",
    }
    assert report["trend"]["avg_cc"]["direction"] == "down"
    assert report["trend"]["dead_code"]["delta"] == 2.0
    assert report["trend"]["duplication_ratio"]["direction"] == "unchanged"


def test_missing_or_invalid_inputs_fail_open(tmp_path: Path) -> None:
    missing = apply_metrics_policy(
        _report(),
        config_path=str(tmp_path / "missing_config.json"),
        history_path=str(tmp_path / "missing_history.json"),
    )
    assert missing["degraded"] is True
    assert missing["gates"]["status"] == "unknown"
    assert not missing["trend"]
    assert len(missing["known_gaps"]) == 2

    invalid_config = tmp_path / "invalid.json"
    invalid_config.write_text("thresholds: [", encoding="utf-8")
    invalid_history = tmp_path / "invalid_history.json"
    invalid_history.write_text("{broken", encoding="utf-8")
    invalid = apply_metrics_policy(
        _report(), config_path=str(invalid_config), history_path=str(invalid_history)
    )
    assert invalid["degraded"] is True
    assert invalid["gates"]["status"] == "unknown"
    assert not invalid["trend"]
    assert len(invalid["known_gaps"]) == 2


def test_snapshot_metrics_config_and_history(tmp_path: Path) -> None:
    import dsh_nodes

    root = tmp_path / "project"
    root.mkdir()
    (root / "mod.py").write_text(
        "import os\n\ndef branchy(x):\n    if x:\n        return 1\n    return 0\n",
        encoding="utf-8",
    )
    config = _config(tmp_path, {"max_cc": 0})
    history = tmp_path / "history.json"
    history.write_text(json.dumps({"report": _report()}), encoding="utf-8")
    analyzed = dsh_nodes.S33_rea_analyze({"target": str(root), "force": True})

    out = dsh_nodes.get_rea_snapshot(
        {
            "snapshot_id": analyzed["result"]["snapshot_id"],
            "section": "metrics",
            "metrics_config": config,
            "metrics_history": str(history),
        }
    )

    assert out["ok"] is True, out
    report = out["result"]["report"]
    assert report["gates"]["status"] == "fail"
    assert report["trend"]["max_cc"]["previous"] == 12.0
    assert _gate_evidence(report)
