import argparse
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8", errors="replace"))


def _quality_obj(v: Any) -> Dict[str, Any]:
    if isinstance(v, dict):
        return {
            "status": str(v.get("status") or "unknown").strip() or "unknown",
            "reasons": [str(x) for x in (v.get("reasons") or []) if str(x or "").strip()],
            "error": str(v.get("error") or "").strip(),
        }
    s = str(v or "").strip().lower()
    if s in {"ok", "stale", "missing", "backfilled", "suspect", "unknown"}:
        return {"status": s, "reasons": [], "error": ""}
    return {"status": "unknown", "reasons": [], "error": ""}


def _to_num(v: Any) -> float | None:
    try:
        x = float(v)
    except Exception:
        return None
    if x != x:
        return None
    return x


def _get(obj: Any, paths: List[List[str]]) -> Any:
    for path in paths:
        cur = obj
        ok = True
        for key in path:
            if isinstance(cur, dict) and key in cur:
                cur = cur[key]
            else:
                ok = False
                break
        if ok:
            return cur
    return None


def _root_from_script() -> Path:
    return Path(__file__).resolve().parents[5]


def _schema_map(root: Path) -> Dict[str, str]:
    p = root / "shared" / "web3_flow_schema_map.json"
    obj = _load_json(p)
    rows = obj if isinstance(obj, list) else []
    out: Dict[str, str] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        k = str(row.get("key") or "").strip()
        b = str(row.get("bindBase") or "").strip()
        if k and b:
            out[k] = b
    return out


def _narrative_evidence_map(root: Path) -> Dict[str, Dict[str, str]]:
    p = root / "shared" / "narrative_evidence_map.json"
    try:
        obj = _load_json(p)
    except Exception:
        return {}
    rows = obj if isinstance(obj, list) else []
    out: Dict[str, Dict[str, str]] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        bind_base = str(row.get("bindBase") or "").strip()
        if not bind_base:
            continue
        out[bind_base] = {
            "affects": str(row.get("affects") or "").strip(),
            "path": str(row.get("path") or "").strip(),
            "gate": str(row.get("gate") or "").strip(),
        }
    return out


def _normalize_items(raw: Any, key_to_base: Dict[str, str]) -> List[Dict[str, Any]]:
    src_rows = []
    if isinstance(raw, dict) and isinstance(raw.get("items"), list):
        src_rows = raw.get("items") or []
    elif isinstance(raw, list):
        src_rows = raw
    out: List[Dict[str, Any]] = []
    for row in src_rows:
        if not isinstance(row, dict):
            continue
        bind_base = str(row.get("bindBase") or row.get("base") or "").strip()
        if not bind_base:
            k = str(row.get("key") or "").strip()
            bind_base = str(key_to_base.get(k) or "").strip()
        if not bind_base:
            continue
        out.append({
            "bindBase": bind_base,
            "value": row.get("value"),
            "source": str(row.get("source") or row.get("skill") or "").strip(),
            "latency_sec": row.get("latency_sec"),
            "revision": (row.get("revision") if isinstance(row.get("revision"), dict) else None),
            "quality": _quality_obj(row.get("quality")),
            "generated_at": str(row.get("generated_at") or _now_iso()),
        })
    return out


def _normalize_key(x: Any) -> str:
    s = str(x or "").strip().lower()
    return re.sub(r"[^a-z0-9]+", "", s)


def _iter_dict_nodes(obj: Any):
    if isinstance(obj, dict):
        yield obj
        for v in obj.values():
            yield from _iter_dict_nodes(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from _iter_dict_nodes(v)


def _search_numeric_by_aliases(obj: Any, aliases: List[str]) -> float | None:
    alias_set = {_normalize_key(a) for a in aliases if str(a or "").strip()}
    if not alias_set:
        return None
    for node in _iter_dict_nodes(obj):
        for k, v in node.items():
            if _normalize_key(k) not in alias_set:
                continue
            n = _to_num(v)
            if n is None:
                continue
            return n
    return None


def _search_text_by_aliases(obj: Any, aliases: List[str]) -> str:
    alias_set = {_normalize_key(a) for a in aliases if str(a or "").strip()}
    if not alias_set:
        return ""
    for node in _iter_dict_nodes(obj):
        for k, v in node.items():
            if _normalize_key(k) not in alias_set:
                continue
            s = str(v or "").strip()
            if s:
                return s
    return ""


def _gate_info_research_items(raw: Any) -> List[Dict[str, Any]]:
    obj = raw if isinstance(raw, dict) else {}
    generated_at = (
        _search_text_by_aliases(
            obj,
            [
                "generated_at",
                "data_time",
                "timestamp",
                "asof",
                "report_time",
                "updated_at",
            ],
        )
        or _now_iso()
    )
    rows = [
        ("stablecoin_usdt_exchange_inflow_usd__all__all__all", [
            "stablecoin_exchange_inflow_usd",
            "stablecoin_exchange_netflow_usd",
            "stablecoin_netflow_usd",
            "stablecoin_inflow_usd",
            "exchange_stablecoin_inflow_usd",
        ]),
        ("stablecoin_usdt_exchange_balance_usd__all__all__all", [
            "stablecoin_exchange_balance_usd",
            "exchange_stablecoin_balance_usd",
            "stablecoin_balance_on_exchange_usd",
            "stablecoin_cex_balance_usd",
        ]),
        ("spot_etf_netflow_usd__btc__all__na", [
            "btc_etf_netflow_usd",
            "bitcoin_etf_netflow_usd",
            "btc_spot_etf_netflow_usd",
            "spot_etf_btc_netflow_usd",
        ]),
        ("spot_etf_netflow_usd__eth__all__na", [
            "eth_etf_netflow_usd",
            "ethereum_etf_netflow_usd",
            "eth_spot_etf_netflow_usd",
            "spot_etf_eth_netflow_usd",
        ]),
        ("cex_exchange_reserve_usd__all__all__all", [
            "cex_exchange_reserve_usd",
            "exchange_reserve_usd",
            "cex_reserve_usd",
            "exchange_total_reserve_usd",
        ]),
    ]
    out: List[Dict[str, Any]] = []
    for bind_base, aliases in rows:
        val = _search_numeric_by_aliases(obj, aliases)
        if val is None:
            quality = {"status": "missing", "reasons": ["gate_info_research_field_missing"], "error": "value_unavailable"}
        else:
            quality = {"status": "ok", "reasons": [], "error": ""}
        out.append({
            "bindBase": bind_base,
            "value": val,
            "source": "gate-info-research",
            "latency_sec": None,
            "revision": {"provider_revision_ts": generated_at},
            "quality": quality,
            "generated_at": generated_at,
        })
    return out


def _coinanalysis_items(raw: Any) -> List[Dict[str, Any]]:
    obj = raw if isinstance(raw, dict) else {}
    market = _get(obj, [["market_snapshot"], ["data", "market_snapshot"], ["market"], ["report", "market_snapshot"]])
    social = _get(obj, [["social_sentiment"], ["data", "social_sentiment"], ["sentiment"], ["report", "social_sentiment"]])
    generated_at = str(_get(obj, [["generated_at"], ["ts"], ["timestamp"]]) or _now_iso())
    funding = _to_num(_get(market, [["funding_rate_bps"], ["funding_rate"], ["funding", "rate_bps"], ["funding", "rate"]]))
    if funding is not None and abs(funding) < 1.0:
        funding = funding * 10000.0
    oi_usd = _to_num(_get(market, [["oi_usd"], ["open_interest_usd"], ["open_interest"], ["oi"]]))
    spread_bps = _to_num(_get(market, [["spread_bps"], ["orderbook", "spread_bps"], ["micro", "spread_bps"]]))
    impact_cost_bps = _to_num(_get(market, [["impact_cost_bps"], ["orderbook", "impact_cost_bps"], ["micro", "impact_cost_bps"]]))
    slippage_proxy = _to_num(_get(market, [["slippage_proxy"], ["orderbook", "slippage_proxy"], ["micro", "slippage_proxy"]]))
    orderbook_depth_pct = _to_num(_get(market, [["orderbook_depth_pct"], ["orderbook", "depth_pct"], ["micro", "orderbook_depth_pct"]]))
    sentiment_score = _to_num(_get(social, [["sentiment_score"], ["score"], ["kol_sentiment_score"]]))
    discussion_level = _to_num(_get(social, [["discussion_volume"], ["discussion_level"]]))
    social_heat = sentiment_score if sentiment_score is not None else discussion_level
    rows = [
        ("funding_rate_bps__btc__binance__na", funding),
        ("oi_usd__btc__coinglass__na", oi_usd),
        ("spread_bps__btc__all__na", spread_bps),
        ("impact_cost_bps__btc__all__na", impact_cost_bps),
        ("slippage_proxy__btc__all__na", slippage_proxy),
        ("orderbook_depth_pct__btc__all__na", orderbook_depth_pct),
        ("social_heat_event_score__btc__all__na", social_heat),
    ]
    out: List[Dict[str, Any]] = []
    for bind_base, val in rows:
        if val is None:
            quality = {"status": "missing", "reasons": ["coinanalysis_field_missing"], "error": "value_unavailable"}
        else:
            quality = {"status": "ok", "reasons": [], "error": ""}
        out.append({
            "bindBase": bind_base,
            "value": val,
            "source": "gate-info-coinanalysis",
            "latency_sec": None,
            "revision": {"provider_revision_ts": generated_at},
            "quality": quality,
            "generated_at": generated_at,
        })
    return out


def _marketoverview_items(raw: Any) -> List[Dict[str, Any]]:
    obj = raw if isinstance(raw, dict) else {}
    generated_at = (
        _search_text_by_aliases(
            obj,
            [
                "generated_at",
                "data_time",
                "timestamp",
                "asof",
                "report_time",
                "updated_at",
            ],
        )
        or _now_iso()
    )
    rows = [
        ("market_breadth_score__all__all__na", [
            "market_breadth_score",
            "breadth_score",
            "gainer_loser_ratio",
            "adv_decline_ratio",
            "advance_decline_ratio",
            "market_width_score",
        ]),
        ("dominance_shift_score__btc__all__na", [
            "dominance_shift_score",
            "btc_dominance_change",
            "btc_dominance_delta",
            "dominance_delta",
            "dominance_shift",
        ]),
        ("defi_tvl_momentum_score__all__defi__na", [
            "defi_tvl_momentum_score",
            "defi_tvl_change_pct",
            "defi_tvl_growth",
            "tvl_momentum",
            "tvl_change_24h",
            "tvl_change_pct",
        ]),
        ("macro_event_pressure_score__all__all__na", [
            "macro_event_pressure_score",
            "macro_risk_score",
            "event_risk_score",
            "fear_greed_index",
            "fear_greed_score",
        ]),
    ]
    out: List[Dict[str, Any]] = []
    for bind_base, aliases in rows:
        val = _search_numeric_by_aliases(obj, aliases)
        if val is None:
            quality = {"status": "missing", "reasons": ["marketoverview_field_missing"], "error": "value_unavailable"}
        else:
            quality = {"status": "ok", "reasons": [], "error": ""}
        out.append({
            "bindBase": bind_base,
            "value": val,
            "source": "gate-info-marketoverview",
            "latency_sec": None,
            "revision": {"provider_revision_ts": generated_at},
            "quality": quality,
            "generated_at": generated_at,
        })
    return out


def _okx_generated_at(obj: Dict[str, Any]) -> str:
    return (
        _search_text_by_aliases(
            obj,
            [
                "generated_at",
                "data_time",
                "timestamp",
                "asof",
                "report_time",
                "updated_at",
            ],
        )
        or _now_iso()
    )


def _okx_items_from_rows(raw: Any, source: str, rows: List[tuple[str, List[str]]], missing_reason: str) -> List[Dict[str, Any]]:
    obj = raw if isinstance(raw, dict) else {}
    generated_at = _okx_generated_at(obj)
    out: List[Dict[str, Any]] = []
    for bind_base, aliases in rows:
        val = _search_numeric_by_aliases(obj, aliases)
        if val is None:
            quality = {"status": "missing", "reasons": [missing_reason], "error": "value_unavailable"}
        else:
            quality = {"status": "ok", "reasons": [], "error": ""}
        out.append({
            "bindBase": bind_base,
            "value": val,
            "source": source,
            "latency_sec": None,
            "revision": {"provider_revision_ts": generated_at},
            "quality": quality,
            "generated_at": generated_at,
        })
    return out


def _okx_cmc_okx_items(raw: Any) -> List[Dict[str, Any]]:
    rows = [
        ("funding_rate_bps__btc__okx__perp", ["funding_rate_bps", "funding_rate", "okx_funding_rate_bps", "okx_funding_rate"]),
        ("oi_usd__btc__okx__perp", ["oi_usd", "open_interest_usd", "okx_oi_usd", "okx_open_interest_usd"]),
        ("spread_bps__btc__okx__spot", ["spread_bps", "okx_spread_bps", "orderbook_spread_bps"]),
    ]
    return _okx_items_from_rows(raw, "okx:cmc-okx", rows, "okx_cmc_okx_field_missing")


def _okx_market_intel_items(raw: Any) -> List[Dict[str, Any]]:
    rows = [
        ("social_heat_event_score__btc__okx__na", ["social_heat_event_score", "social_heat_score", "market_intel_heat", "narrative_heat"]),
    ]
    return _okx_items_from_rows(raw, "okx:market-intel", rows, "okx_market_intel_field_missing")


def _okx_alpha_vantage_items(raw: Any) -> List[Dict[str, Any]]:
    rows = [
        ("macro_event_pressure_score__btc__macro__na", ["macro_event_pressure_score", "macro_risk_score", "alpha_vantage_macro_pressure", "event_risk_score"]),
    ]
    return _okx_items_from_rows(raw, "okx:alpha-vantage", rows, "okx_alpha_vantage_field_missing")


def _okx_hyperliquid_analyzer_items(raw: Any) -> List[Dict[str, Any]]:
    rows = [
        ("whale_position_delta_usd__btc__hyperliquid__perp", ["whale_position_delta_usd", "hyperliquid_whale_position_delta_usd", "whale_position_change_usd"]),
    ]
    return _okx_items_from_rows(raw, "okx:hyperliquid-analyzer", rows, "okx_hyperliquid_field_missing")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", default="")
    parser.add_argument(
        "--mode",
        default="items",
        choices=[
            "items",
            "coinanalysis",
            "gate-info-research",
            "gate-info-marketoverview",
            "okx-market-intel",
            "okx-cmc-okx",
            "okx-alpha-vantage",
            "okx-hyperliquid-analyzer",
        ],
    )
    args = parser.parse_args()
    input_path = Path(args.input).resolve()
    if not input_path.exists():
        raise SystemExit(f"input_not_found: {input_path}")
    root = _root_from_script()
    out_path = Path(args.output).resolve() if str(args.output).strip() else (root / "ops" / "nanoclaw" / "core_task1" / "flow" / "outputs" / "web3_skill_snapshot_latest.json")
    key_to_base = _schema_map(root)
    raw = _load_json(input_path)
    if str(args.mode) == "coinanalysis":
        items = _coinanalysis_items(raw)
    elif str(args.mode) == "gate-info-research":
        items = _gate_info_research_items(raw)
    elif str(args.mode) == "gate-info-marketoverview":
        items = _marketoverview_items(raw)
    elif str(args.mode) == "okx-market-intel":
        items = _okx_market_intel_items(raw)
    elif str(args.mode) == "okx-cmc-okx":
        items = _okx_cmc_okx_items(raw)
    elif str(args.mode) == "okx-alpha-vantage":
        items = _okx_alpha_vantage_items(raw)
    elif str(args.mode) == "okx-hyperliquid-analyzer":
        items = _okx_hyperliquid_analyzer_items(raw)
    else:
        items = _normalize_items(raw, key_to_base)
    explain_map = _narrative_evidence_map(root)
    if explain_map:
        for row in items:
            if not isinstance(row, dict):
                continue
            bind_base = str(row.get("bindBase") or "").strip()
            exp = explain_map.get(bind_base)
            if exp:
                row["narrative_explain"] = exp
    payload = {"generated_at": _now_iso(), "items": items}
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"ok": True, "input": str(input_path), "output": str(out_path), "count": len(items)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
