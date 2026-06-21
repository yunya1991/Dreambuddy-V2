import json
from pathlib import Path

from ops.nanoclaw.core_task1.flow.scripts import regime_classifier as rc


def test_assess_data_quality_recovers_from_skill_snapshot(tmp_path, monkeypatch) -> None:
    out_dir = tmp_path / "outputs"
    out_dir.mkdir(parents=True, exist_ok=True)
    snap = {
        "items": [
            {"bindBase": "spot_etf_netflow_usd__btc__all__na", "value": 1.0, "quality": {"status": "suspect"}},
            {"bindBase": "stablecoin_usdt_exchange_inflow_usd__all__all__all", "value": 1.0, "quality": {"status": "suspect"}},
            {"bindBase": "cex_exchange_reserve_usd__all__all__all", "value": 1.0, "quality": {"status": "suspect"}},
            {"bindBase": "macro_event_pressure_score__btc__macro__na", "value": 0.6, "quality": {"status": "suspect"}},
            {"bindBase": "oi_usd__btc__coinglass__na", "value": 1000.0, "quality": {"status": "suspect"}},
            {"bindBase": "funding_rate_bps__btc__okx__perp", "value": 8.0, "quality": {"status": "suspect"}},
            {"bindBase": "whale_position_delta_usd__btc__hyperliquid__perp", "value": 120000.0, "quality": {"status": "suspect"}},
        ]
    }
    (out_dir / "web3_skill_snapshot_latest.json").write_text(json.dumps(snap, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr(rc, "OUTPUT_DIR", str(out_dir))

    layers = {
        "exogenous": {
            "etf_flow": {"timestamp": "2026-04-08T00:00:00Z", "btc_etf_net_inflow": None, "eth_etf_net_inflow": None, "error": "na"},
            "stablecoin": {"timestamp": "2026-04-08T00:00:00Z", "total_supply_usd": None, "error": "na"},
            "cex_reserves": {"timestamp": "2026-04-08T00:00:00Z", "total_reserve_usd": None, "error": "na"},
            "macro": {"timestamp": "2026-04-08T00:00:00Z", "dxy": None, "error": "na"},
            "binance_web3": {"timestamp": "2026-04-08T00:00:00Z", "market_rank": {"trending_tokens": []}, "smart_money_inflow": None, "error": None},
        },
        "leverage": {
            "coinglass": {"timestamp": "2026-04-08T00:00:00Z", "funding_rate": None, "open_interest": None, "liquidation_24h": None, "error": "na"},
            "binance": {"timestamp": "2026-04-08T00:00:00Z", "funding_rate": None, "error": "na"},
            "cme_oi": {"timestamp": "2026-04-08T00:00:00Z", "open_interest": None, "error": "na"},
            "bridge": {"timestamp": "2026-04-08T00:00:00Z", "netflow_usd": 0, "proxy_details": None, "error": "na"},
        },
        "onchain": {
            "etherscan": {"timestamp": "2026-04-08T00:00:00Z", "gas_price_gwei": None, "error": "na"},
            "glassnode": {"timestamp": "2026-04-08T00:00:00Z", "exchange_inflow_btc": None, "exchange_outflow_btc": None, "exchange_balance_btc": None, "error": "na"},
            "whale_alert": {"timestamp": "2026-04-08T00:00:00Z", "transactions": [], "error": "na"},
            "gate_address_tracker": {"timestamp": "2026-04-08T00:00:00Z", "address_profiles": [], "error": "na"},
        },
    }
    rep = rc.assess_data_quality(layers, freshness={})
    assert float(rep.get("coverage") or 0.0) >= 0.80
    critical = [str(x) for x in (rep.get("critical_missing_sources") or [])]
    assert "etf" not in critical
    assert "binance_funding" not in critical
    assert "etherscan_gas" not in critical
    assert "glassnode" not in critical
    assert "whale_alert" not in critical


def test_leverage_onchain_signal_use_snapshot_proxy(tmp_path, monkeypatch) -> None:
    out_dir = tmp_path / "outputs"
    out_dir.mkdir(parents=True, exist_ok=True)
    snap = {
        "items": [
            {"bindBase": "funding_rate_bps__btc__okx__perp", "value": 12.0, "quality": {"status": "suspect"}},
            {"bindBase": "oi_usd__btc__okx__perp", "value": 800000000.0, "quality": {"status": "suspect"}},
            {"bindBase": "whale_position_delta_usd__btc__hyperliquid__perp", "value": 2500000.0, "quality": {"status": "suspect"}},
            {"bindBase": "macro_event_pressure_score__btc__macro__na", "value": 0.4, "quality": {"status": "suspect"}},
        ]
    }
    (out_dir / "web3_skill_snapshot_latest.json").write_text(json.dumps(snap, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr(rc, "OUTPUT_DIR", str(out_dir))

    lev = rc.calculate_leverage_signal({
        "binance": {"timestamp": "2026-04-08T00:00:00Z", "funding_rate": None},
        "coinglass": {"open_interest": None, "liquidation_24h": None},
    })
    onc = rc.calculate_onchain_signal({
        "etherscan": {"gas_price_gwei": None},
        "glassnode": {"exchange_inflow_btc": None},
        "whale_alert": {"transactions": []},
        "gate_address_tracker": {"address_profiles": []},
    })
    assert abs(float(lev.get("score") or 0.0)) > 1e-6
    assert abs(float(onc.get("score") or 0.0)) > 1e-6


def test_run_regime_classification_reaches_native_coverage_with_sparse_layers(tmp_path, monkeypatch) -> None:
    out_dir = tmp_path / "outputs"
    out_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(rc, "OUTPUT_DIR", str(out_dir))

    layers = {
        "exogenous": {
            "etf_flow": {"timestamp": "2026-04-08T00:00:00Z", "btc_etf_net_inflow": None, "eth_etf_net_inflow": None, "btc_etf_total_btc": 1200000.0},
            "stablecoin": {"timestamp": "2026-04-08T00:00:00Z", "total_supply_usd": 300000000000.0},
            "cex_reserves": {"timestamp": "2026-04-08T00:00:00Z", "total_reserve_usd": 250000000000.0},
            "macro": {"timestamp": "2026-04-08T00:00:00Z", "dxy": None},
            "binance_web3": {"timestamp": "2026-04-08T00:00:00Z", "market_rank": {"trending_tokens": []}, "smart_money_inflow": None},
        },
        "leverage": {
            "coinglass": {"timestamp": "2026-04-08T00:00:00Z", "funding_rate": None, "open_interest": None, "liquidation_24h": None, "error": "na"},
            "binance": {"timestamp": "2026-04-08T00:00:00Z", "funding_rate": None, "error": "na"},
            "cme_oi": {"timestamp": "2026-04-08T00:00:00Z", "open_interest": 100000.0},
            "bridge": {"timestamp": "2026-04-08T00:00:00Z", "netflow_usd": 2100000000.0, "proxy_details": [{"chain": "Ethereum"}]},
        },
        "onchain": {
            "etherscan": {"timestamp": "2026-04-08T00:00:00Z", "gas_price_gwei": None, "exchange_addresses": ["binance_hot"]},
            "glassnode": {"timestamp": "2026-04-08T00:00:00Z", "exchange_inflow_btc": None, "exchange_outflow_btc": None, "exchange_balance_btc": None, "error": "na"},
            "whale_alert": {"timestamp": "2026-04-08T00:00:00Z", "transactions": [], "btc_large_transfers": 0, "error": "na"},
            "gate_address_tracker": {"timestamp": "2026-04-08T00:00:00Z", "address_profiles": [], "summary": {"deep_upgrades": 0}, "error": "na"},
        },
    }
    result = rc.run_regime_classification(collection_result=layers)
    assert float((result.get("quality") or {}).get("coverage") or 0.0) >= 0.80
