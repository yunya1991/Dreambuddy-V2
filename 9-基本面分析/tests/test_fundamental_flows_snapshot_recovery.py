import json
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path


def _load_embedded_service():
    p = Path("backend/src/_embedded_ml_trade_service_source.py").resolve()
    spec = spec_from_file_location("embedded_service_for_test_snapshot_recovery", str(p))
    assert spec is not None and spec.loader is not None
    mod = module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_flows_compact_recover_coverage_from_skill_snapshot(tmp_path, monkeypatch) -> None:
    svc = _load_embedded_service()
    snapshot = {
        "items": [
            {"bindBase": "spot_etf_netflow_usd__btc__all__na", "value": 12000000, "quality": {"status": "ok"}},
            {"bindBase": "funding_rate_bps__btc__okx__perp", "value": 9.5, "quality": {"status": "ok"}},
            {"bindBase": "whale_position_delta_usd__btc__hyperliquid__perp", "value": 2300000, "quality": {"status": "ok"}},
        ]
    }
    snapshot_file = tmp_path / "web3_skill_snapshot_latest.json"
    snapshot_file.write_text(json.dumps(snapshot, ensure_ascii=False), encoding="utf-8")

    monkeypatch.setattr(svc, "_fundamental_flows_skills_snapshot_file", lambda: snapshot_file)
    monkeypatch.setattr(svc, "_fundamental_flows_pick_layer_raw_file", lambda layer, tag: None)
    monkeypatch.setattr(svc, "_fundamental_flows_try_read_json", lambda path: {})
    monkeypatch.setattr(svc, "_fundamental_flows_prev_regime_record", lambda name: {})

    rec = {
        "timestamp": "2026-04-08T06:13:03Z",
        "composite": 0.0,
        "quality": {
            "coverage": 0.0769,
            "counts": {"ok": 1, "stale": 0, "missing": 12, "backfilled": 0, "suspect": 0},
            "critical_missing_sources": ["etf", "binance_funding", "whale_alert"],
        },
        "regime_output": {"filter": "disable", "risk_off": False},
    }
    compact = svc._fundamental_flows_compact_fields(rec, "flow_regime_20260408_0613.json")
    assert float(compact.get("coverage") or 0.0) >= 0.30
    missing = [str(x) for x in (compact.get("missing_data") or [])]
    assert "etf" not in missing
    assert "binance_funding" not in missing
    assert "whale_alert" not in missing
