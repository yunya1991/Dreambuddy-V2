"""R0-06: constraint_loader 测试（40/43 约束 → 钳位）。"""

from __future__ import annotations

import json

from adapters.constraint_loader import clamp_position, load_constraints


def _strategy_mapping(tmp_path):
    data = {
        "strategy_suggestion": {"position_band_pct": [30, 60]},
        "risk_guards": {
            "event_window": {"in_window": True},
            "effective_confidence": "medium",
        },
    }
    p = tmp_path / "strategy_mapping.json"
    p.write_text(json.dumps(data), encoding="utf-8")
    return str(p)


def test_load_40_constraints(tmp_path):
    c = load_constraints(strategy_mapping_path=_strategy_mapping(tmp_path))
    assert c["position_band"] == [30, 60]
    assert c["freeze"] is True
    assert c["degraded"] == ["strategic_extension_missing"]


def test_missing_40_fails_open(tmp_path):
    c = load_constraints(strategy_mapping_path=str(tmp_path / "x.json"))
    assert c["position_band"] == [0, 100]
    assert c["freeze"] is False
    assert "strategy_mapping_missing" in c["degraded"]


def test_clamp_position_within_band():
    c = {"position_band": [30, 60]}
    assert clamp_position(c, 45, "L1_anchor") == 45.0


def test_clamp_position_beyond_band():
    c = {"position_band": [30, 60]}
    assert clamp_position(c, 80, "L1_anchor") == 60.0
    assert clamp_position(c, 10, "L1_anchor") == 30.0


def test_asset_override_from_43(tmp_path):
    strat = tmp_path / "strategy_mapping.json"
    strat.write_text(
        json.dumps({"strategy_suggestion": {"position_band_pct": [0, 100]}}), encoding="utf-8"
    )
    ext = tmp_path / "strategic_extension_signal.json"
    ext.write_text(
        json.dumps({"per_asset_class": {"L1_anchor": {"position_band": [10, 20]}}}),
        encoding="utf-8",
    )
    c = load_constraints(strategy_mapping_path=str(strat), strategic_extension_path=str(ext))
    assert clamp_position(c, 50, "L1_anchor") == 20.0
