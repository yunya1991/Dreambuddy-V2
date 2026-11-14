"""40+43 宏观弹性约束合并视图测试。"""

import json
from datetime import datetime, timedelta, timezone

from dreambuddy_evolution.adapters import subsystem_bridge as sb


def _iso(hours_ago: float) -> str:
    return (datetime.now(timezone.utc) - timedelta(hours=hours_ago)).isoformat()


def _write(path, payload):
    path.write_text(json.dumps(payload), encoding="utf-8")


def _patch_paths(monkeypatch, tmp_path, m40=None, sig43=None):
    p40 = tmp_path / "strategy_mapping.json"
    p43 = tmp_path / "strategic_extension_signal.json"
    pbus = tmp_path / "bus_state.json"
    if m40 is not None:
        _write(p40, m40)
    if sig43 is not None:
        _write(p43, sig43)
    monkeypatch.setattr(sb, "_40_STRATEGY_MAPPING_PATH", p40)
    monkeypatch.setattr(sb, "_43_STRATEGIC_PATH", p43)
    monkeypatch.setattr(sb, "_42_BUS_STATE_PATH", pbus)


def test_merge_reads_band_allocation_and_bias(monkeypatch, tmp_path):
    _patch_paths(
        monkeypatch,
        tmp_path,
        m40={
            "generated_at": _iso(1),
            "strategy_suggestion": {"position_band_pct": [25, 55]},
            "risk_guards": {"effective_confidence": "medium"},
        },
        sig43={
            "ts": _iso(1),
            "expires_at": _iso(-20),
            "payload": {
                "strategic_elements": {
                    "strategic_view": {
                        "asset_allocation": {
                            "allocation": {
                                "crypto_usdt": 0.5,
                                "us_stock": 0.3,
                                "precious_metal": 0.2,
                            }
                        },
                        "direction_bias": {
                            "per_class": {
                                "crypto_usdt": {
                                    "long": 0.7,
                                    "short": 0.0,
                                    "neutral": 0.3,
                                    "dominant": "long",
                                }
                            }
                        },
                        "capital_posture": {"exposure_hint": 0.8},
                    }
                },
                "per_asset_class": {"crypto_usdt": {"war_state": "ACTIVE"}},
            },
        },
    )
    out = sb.SubSystemBridge().get_macro_elastic_constraint("crypto_usdt")
    assert out["source"] == "merged"
    assert out["band_upper_pct"] == 55.0
    assert out["exposure_hint"] == 0.8
    assert out["allocation"]["crypto_usdt"] == 0.5
    assert out["direction_bias"]["crypto_usdt"]["dominant"] == "long"
    assert out["war_state"] == "ACTIVE"
    assert out["stale"] is False


def test_expired_43_marks_stale_but_keeps_constraint(monkeypatch, tmp_path):
    _patch_paths(
        monkeypatch,
        tmp_path,
        m40={
            "generated_at": _iso(1),
            "strategy_suggestion": {"position_band_pct": [0, 20]},
            "risk_guards": {"effective_confidence": "low"},
        },
        sig43={"ts": _iso(100), "expires_at": _iso(50), "payload": {}},
    )
    out = sb.SubSystemBridge().get_macro_elastic_constraint("crypto_usdt")
    assert out["stale"] is True
    assert "43_stale" in out["degraded"]
    assert out["band_upper_pct"] == 20.0
    assert out["exposure_hint"] == 0.5


def test_missing_sources_returns_empty(monkeypatch, tmp_path):
    _patch_paths(monkeypatch, tmp_path)
    assert sb.SubSystemBridge().get_macro_elastic_constraint("crypto_usdt") == {}
