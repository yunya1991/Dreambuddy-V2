import json
from pathlib import Path

from ops.nanoclaw.core_task1.flow.scripts.sync_web3_skill_snapshot import (
    _okx_alpha_vantage_items,
    _okx_cmc_okx_items,
    _okx_hyperliquid_analyzer_items,
    _okx_market_intel_items,
)


def test_source_snapshot_schema_has_required_fields() -> None:
    p = Path("ops/nanoclaw/core_task1/schema/source_snapshot_v1.schema.json")
    obj = json.loads(p.read_text(encoding="utf-8"))
    required = set(obj.get("required", []))
    assert {"schema", "asset", "asof_ts", "items", "execution_gate"} <= required


def test_okx_modes_generate_bindbase_items() -> None:
    raw = {
        "generated_at": "2026-04-08T00:00:00Z",
        "funding_rate_bps": 10,
        "oi_usd": 1000000,
        "spread_bps": 3,
        "social_heat_score": 72,
        "macro_event_pressure_score": 0.65,
        "whale_position_delta_usd": 1200000,
    }
    cmc = _okx_cmc_okx_items(raw)
    mi = _okx_market_intel_items(raw)
    av = _okx_alpha_vantage_items(raw)
    hl = _okx_hyperliquid_analyzer_items(raw)
    cmc_bases = {str(x.get("bindBase") or "") for x in cmc if isinstance(x, dict)}
    mi_bases = {str(x.get("bindBase") or "") for x in mi if isinstance(x, dict)}
    av_bases = {str(x.get("bindBase") or "") for x in av if isinstance(x, dict)}
    hl_bases = {str(x.get("bindBase") or "") for x in hl if isinstance(x, dict)}
    assert "funding_rate_bps__btc__okx__perp" in cmc_bases
    assert "social_heat_event_score__btc__okx__na" in mi_bases
    assert "macro_event_pressure_score__btc__macro__na" in av_bases
    assert "whale_position_delta_usd__btc__hyperliquid__perp" in hl_bases
