#!/usr/bin/env python3
import argparse
import json
import math
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


def _float_or_none(x: Any) -> Optional[float]:
    try:
        v = float(x)
        if not math.isfinite(v):
            return None
        return float(v)
    except Exception:
        return None


def _int_or_none(x: Any) -> Optional[int]:
    try:
        return int(x)
    except Exception:
        return None


def _validate_weights(row: Dict[str, Any], cfg_weights: Tuple[float, float], tol: float) -> List[str]:
    errs: List[str] = []
    ws = row.get("input_weights") if isinstance(row.get("input_weights"), dict) else {}
    wb = _float_or_none(ws.get("btc"))
    we = _float_or_none(ws.get("eth"))
    if wb is None or we is None:
        errs.append("input_weights_missing")
        return errs
    if wb < 0.0 or we < 0.0:
        errs.append("input_weights_negative")
    s = wb + we
    if abs(float(s) - 1.0) > float(tol):
        errs.append("input_weights_not_normalized")
    exp_b, exp_e = cfg_weights
    if abs(float(wb) - float(exp_b)) > float(tol) or abs(float(we) - float(exp_e)) > float(tol):
        errs.append("input_weights_not_match_config")
    return errs


def _validate_rule_a34(row: Dict[str, Any], tol: float) -> List[str]:
    errs: List[str] = []
    rid = str(row.get("rule_id") or "")
    tier = str(row.get("risk_budget_tier") or "")
    ap = str(row.get("addon_pacing") or "")
    allow_open = bool(row.get("allow_open"))
    allow_addon = bool(row.get("allow_addon"))
    crash_switch = bool(row.get("crash_switch"))
    input_source = str(row.get("input_source") or "")
    risk_d = _float_or_none(row.get("risk_d"))
    risk_1h = _float_or_none(row.get("risk_1h"))
    risk_high = _float_or_none(row.get("risk_high"))
    crash_risk1h_thr = _float_or_none(row.get("crash_risk1h_thr"))

    if input_source != "btceth_weighted":
        errs.append("input_source_not_weighted")

    if rid == "R-A1":
        if tier != "risk_on":
            errs.append("ra1_tier")
        if ap != "normal":
            errs.append("ra1_pacing")
        if not allow_open:
            errs.append("ra1_allow_open")
    elif rid == "R-A2":
        if tier != "neutral":
            errs.append("ra2_tier")
        if ap != "tight":
            errs.append("ra2_pacing")
        if not allow_open:
            errs.append("ra2_allow_open")
        if allow_addon:
            errs.append("ra2_allow_addon")
    elif rid == "R-A3":
        if tier != "risk_off_pre":
            errs.append("ra3_tier")
        if ap != "pause":
            errs.append("ra3_pacing")
        if allow_open:
            errs.append("ra3_allow_open")
        if allow_addon:
            errs.append("ra3_allow_addon")
    elif rid == "R-A4":
        if tier != "risk_off":
            errs.append("ra4_tier")
        if ap != "pause":
            errs.append("ra4_pacing")
        if allow_open:
            errs.append("ra4_allow_open")
        if allow_addon:
            errs.append("ra4_allow_addon")
        if crash_switch:
            pass
        elif risk_d is not None and risk_high is not None and float(risk_d) >= float(risk_high) - float(tol):
            pass
        elif risk_1h is not None and crash_risk1h_thr is not None and float(risk_1h) >= float(crash_risk1h_thr) - float(tol):
            pass
        else:
            errs.append("ra4_no_extreme_trigger")
    elif rid == "R-A0":
        pass
    else:
        errs.append("unknown_rule_id")
    return errs


def _resolve_cfg_weights(svc: Any) -> Tuple[float, float]:
    wb = _float_or_none(svc.CONFIG.get("quant_pairs_macro_input_w_btc"))
    we = _float_or_none(svc.CONFIG.get("quant_pairs_macro_input_w_eth"))
    if wb is None:
        wb = _float_or_none(svc.CONFIG.get("entry_macro_btceth_shape_w_btc"))
    if we is None:
        we = _float_or_none(svc.CONFIG.get("entry_macro_btceth_shape_w_eth"))
    if wb is None:
        wb = 0.70
    if we is None:
        we = 0.30
    wb = max(0.0, float(wb))
    we = max(0.0, float(we))
    s = wb + we
    if s <= 1e-12:
        return 0.70, 0.30
    return float(wb / s), float(we / s)


def _collect_history(
    svc: Any,
    lookback_hours: int,
    step_hours: int,
    timeframe: str,
    horizon_h: int,
    short_n: int,
) -> List[Dict[str, Any]]:
    now_ms = int(svc._now_ms())
    out: List[Dict[str, Any]] = []
    st = int(max(1, step_hours)) * 3_600_000
    total = int(max(1, lookback_hours // max(1, step_hours))) + 1
    orig_now = svc._now_ms
    try:
        for i in range(total):
            ts = int(now_ms - i * st)
            svc._now_ms = (lambda t=ts: int(t))
            snap = svc._macro_btc_dir_snapshot(timeframe=str(timeframe), horizon_h=int(horizon_h), short_n=int(short_n))
            if not isinstance(snap, dict):
                snap = {"ok": False, "error": "invalid_snapshot_type"}
            row = {
                "ts": int(ts),
                "ok": bool(snap.get("ok")),
                "error": snap.get("error"),
                "rule_id": snap.get("rule_id"),
                "addon_pacing": snap.get("addon_pacing"),
                "input_source": snap.get("input_source"),
                "input_weights": snap.get("input_weights"),
                "risk_budget_tier": snap.get("risk_budget_tier"),
                "allow_open": snap.get("allow_open"),
                "allow_addon": snap.get("allow_addon"),
                "crash_switch": snap.get("crash_switch"),
                "risk_d": snap.get("risk_d"),
                "risk_1h": snap.get("risk_1h"),
                "dir_w": snap.get("dir_w"),
                "dir_d": snap.get("dir_d"),
                "dir_short": snap.get("dir_short"),
                "target_net_bias": snap.get("target_net_bias"),
                "max_net_exposure": snap.get("max_net_exposure"),
            }
            out.append(row)
    finally:
        svc._now_ms = orig_now
    out.reverse()
    return out


def _summarize(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    rule_dist: Dict[str, int] = {}
    pacing_dist: Dict[str, int] = {}
    for r in rows:
        rid = str(r.get("rule_id") or "UNKNOWN")
        ap = str(r.get("addon_pacing") or "UNKNOWN")
        rule_dist[rid] = int(rule_dist.get(rid, 0)) + 1
        pacing_dist[ap] = int(pacing_dist.get(ap, 0)) + 1
    return {
        "samples": int(len(rows)),
        "rule_distribution": dict(sorted(rule_dist.items(), key=lambda kv: kv[0])),
        "addon_pacing_distribution": dict(sorted(pacing_dist.items(), key=lambda kv: kv[0])),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", default=str(Path(__file__).resolve().parents[1]))
    parser.add_argument("--lookback-hours", type=int, default=24 * 90)
    parser.add_argument("--step-hours", type=int, default=1)
    parser.add_argument("--timeframe", default="1h")
    parser.add_argument("--horizon-h", type=int, default=12)
    parser.add_argument("--short-n", type=int, default=3)
    parser.add_argument("--tol", type=float, default=1e-6)
    parser.add_argument("--export-json", default="")
    args = parser.parse_args()

    repo_root = Path(args.repo_root).resolve()
    if str(repo_root) not in sys.path:
        sys.path.insert(0, str(repo_root))
    import ml_trade_service as svc

    risk_high = _float_or_none(svc.CONFIG.get("quant_pairs_macro_riskd_high_thr"))
    if risk_high is None:
        risk_high = 0.80
    crash_risk1h_thr = _float_or_none(svc.CONFIG.get("quant_pairs_macro_crash_risk1h_thr"))
    if crash_risk1h_thr is None:
        crash_risk1h_thr = 0.90
    cfg_weights = _resolve_cfg_weights(svc)

    rows = _collect_history(
        svc=svc,
        lookback_hours=int(max(1, args.lookback_hours)),
        step_hours=int(max(1, args.step_hours)),
        timeframe=str(args.timeframe),
        horizon_h=int(args.horizon_h),
        short_n=int(args.short_n),
    )
    for r in rows:
        r["risk_high"] = float(risk_high)
        r["crash_risk1h_thr"] = float(crash_risk1h_thr)

    violations: List[Dict[str, Any]] = []
    for r in rows:
        errs: List[str] = []
        errs.extend(_validate_weights(r, cfg_weights=cfg_weights, tol=float(args.tol)))
        errs.extend(_validate_rule_a34(r, tol=float(args.tol)))
        if errs:
            violations.append(
                {
                    "ts": int(r.get("ts") or 0),
                    "rule_id": r.get("rule_id"),
                    "addon_pacing": r.get("addon_pacing"),
                    "risk_budget_tier": r.get("risk_budget_tier"),
                    "allow_open": r.get("allow_open"),
                    "allow_addon": r.get("allow_addon"),
                    "errors": errs,
                }
            )

    summary = _summarize(rows)
    ok = len(violations) == 0
    out = {
        "ok": bool(ok),
        "summary": summary,
        "config": {
            "lookback_hours": int(args.lookback_hours),
            "step_hours": int(args.step_hours),
            "timeframe": str(args.timeframe),
            "horizon_h": int(args.horizon_h),
            "short_n": int(args.short_n),
            "weights_expected": {"btc": float(cfg_weights[0]), "eth": float(cfg_weights[1])},
            "risk_high": float(risk_high),
            "crash_risk1h_thr": float(crash_risk1h_thr),
        },
        "violations_count": int(len(violations)),
        "violations": violations[:200],
    }
    if str(args.export_json).strip():
        p = Path(str(args.export_json)).expanduser().resolve()
        p.parent.mkdir(parents=True, exist_ok=True)
        payload = dict(out)
        payload["rows"] = rows
        p.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        out["export_json"] = str(p)

    print("PASS" if ok else "FAIL")
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
