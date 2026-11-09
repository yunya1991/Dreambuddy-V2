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
    c = load_constraints(
        strategy_mapping_path=_strategy_mapping(tmp_path),
        strategic_extension_path=str(tmp_path / "missing_strategic.json"),
    )
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


def test_r1a_tier_constraint_fields(tmp_path):
    strat = tmp_path / "strategy_mapping.json"
    strat.write_text(
        json.dumps({"strategy_suggestion": {"position_band_pct": [0, 100]}}), encoding="utf-8"
    )
    ext = tmp_path / "strategic_extension_signal.json"
    ext.write_text(
        json.dumps(
            {
                "per_asset_class": {
                    "L1_anchor": {
                        "tier": "attack",
                        "leverage_cap": 5,
                        "asset_count_cap": 8,
                        "long_count_cap": 6,
                        "short_count_cap": 4,
                        "net_bias": 0.2,
                    },
                    "L2_anchor": {
                        "tier": "defend",
                        "leverage_cap": 3,
                        "asset_count_cap": 5,
                        "long_count_cap": 4,
                        "short_count_cap": 3,
                        "net_bias": 0.0,
                    },
                },
                "asset_groups": {"L1_anchor": ["L1_anchor"], "L2_anchor": ["L2_anchor"]},
            }
        ),
        encoding="utf-8",
    )
    c = load_constraints(strategy_mapping_path=str(strat), strategic_extension_path=str(ext))
    assert c["leverage_cap"] == 5
    assert c["asset_count_cap"] == 8
    assert c["long_count_cap"] == 6
    assert c["short_count_cap"] == 4
    # F5：net_bias 是方向字段，强制剥离，不进约束通道
    assert c["net_bias"] is None
    assert c["asset_groups"] == {"L1_anchor": ["L1_anchor"], "L2_anchor": ["L2_anchor"]}
    assert "direction_leak_check" in c["degraded"]
    assert c["direction_leak_check"]["passed"] is False


def test_r1a_full_freeze_zero_values_extracted(tmp_path):
    strat = tmp_path / "strategy_mapping.json"
    strat.write_text(
        json.dumps({"strategy_suggestion": {"position_band_pct": [0, 100]}}), encoding="utf-8"
    )
    ext = tmp_path / "strategic_extension_signal.json"
    ext.write_text(
        json.dumps(
            {
                "per_asset_class": {
                    "L1_anchor": {
                        "tier": "full_freeze",
                        "leverage_cap": 1,
                        "asset_count_cap": 0,
                        "long_count_cap": 0,
                        "short_count_cap": 0,
                        "net_bias": 0.0,
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    c = load_constraints(strategy_mapping_path=str(strat), strategic_extension_path=str(ext))
    assert c["leverage_cap"] == 1
    assert c["asset_count_cap"] == 0
    assert c["long_count_cap"] == 0
    assert c["short_count_cap"] == 0
    # F5：net_bias 方向字段强制剥离
    assert c["net_bias"] is None


# ---------- F5 direction_leak_check ----------


def test_f5_direction_fields_stripped_from_per_asset_class(tmp_path):
    """F5：direction/net_bias 等方向字段必须从 per_asset_class 中剥离。"""
    strat = tmp_path / "strategy_mapping.json"
    strat.write_text(
        json.dumps({"strategy_suggestion": {"position_band_pct": [0, 100]}}), encoding="utf-8"
    )
    ext = tmp_path / "strategic_extension_signal.json"
    ext.write_text(
        json.dumps(
            {
                "per_asset_class": {
                    "crypto_usdt": {
                        "direction": "long",
                        "net_bias": 0.8,
                        "sentiment": "bullish",
                        "leverage_cap": 3,
                        "position_band": [0, 30],
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    c = load_constraints(strategy_mapping_path=str(strat), strategic_extension_path=str(ext))
    pac = c["per_asset_class"]["crypto_usdt"]
    # 方向字段被剥离
    assert "direction" not in pac
    assert "net_bias" not in pac
    assert "sentiment" not in pac
    # 中性约束字段保留
    assert pac["leverage_cap"] == 3
    assert pac["position_band"] == [0, 30]
    # 审计字段
    assert c["direction_leak_check"]["passed"] is False
    assert len(c["direction_leak_check"]["stripped_fields"]) >= 3
    assert "direction_leak_check" in c["degraded"]


def test_f5_no_directional_fields_passes(tmp_path):
    """F5：无方向字段时 direction_leak_check 通过。"""
    strat = tmp_path / "strategy_mapping.json"
    strat.write_text(
        json.dumps({"strategy_suggestion": {"position_band_pct": [0, 100]}}), encoding="utf-8"
    )
    ext = tmp_path / "strategic_extension_signal.json"
    ext.write_text(
        json.dumps(
            {
                "per_asset_class": {
                    "crypto_usdt": {
                        "leverage_cap": 2,
                        "asset_count_cap": 5,
                        "position_band": [0, 20],
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    c = load_constraints(strategy_mapping_path=str(strat), strategic_extension_path=str(ext))
    assert c["direction_leak_check"]["passed"] is True
    assert c["direction_leak_check"]["stripped_fields"] == []
    assert "direction_leak_check" not in c["degraded"]


# ---------- F4 degraded_events ----------


def test_f4_degraded_event_written_on_missing_strategy(tmp_path, monkeypatch):
    """F4：strategy_mapping 缺失时应写入 degraded_events.jsonl。"""
    from pathlib import Path

    # 重定向 degraded_events 输出到临时目录
    repo_root = Path(__file__).resolve().parents[2]
    degraded_path = repo_root / "42-神经网络交易协调层" / "runtime" / "degraded_events.jsonl"
    backup = degraded_path.read_text(encoding="utf-8") if degraded_path.exists() else ""
    try:
        if degraded_path.exists():
            degraded_path.unlink()
        load_constraints(
            strategy_mapping_path=str(tmp_path / "missing.json"),
            strategic_extension_path=str(tmp_path / "missing2.json"),
        )
        assert degraded_path.exists(), "degraded_events.jsonl 应被创建"
        lines = degraded_path.read_text(encoding="utf-8").strip().split("\n")
        events = [json.loads(line) for line in lines if line.strip()]
        assert any(e["reason"] == "bridge_closed_using_defaults" for e in events)
        assert all(e["layer"] == "50" for e in events)
    finally:
        if backup:
            degraded_path.write_text(backup, encoding="utf-8")
        elif degraded_path.exists():
            degraded_path.unlink()
