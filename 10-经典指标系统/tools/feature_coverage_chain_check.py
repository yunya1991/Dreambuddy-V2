#!/usr/bin/env python3
import argparse
import json
import os
from urllib import parse, request


def _read_json(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _fetch_recent(base_url, limit):
    q = {
        "limit": int(limit),
        "sort": "ingest",
        "include_shadow": 1,
        "include_stale": 1,
        "require_bar_closed": 1,
        "ab_owner": "strategy",
        "action": "open",
    }
    u = f"{base_url.rstrip('/')}/api/signals/recent?{parse.urlencode(q)}"
    txt = request.urlopen(u, timeout=20).read().decode("utf-8")
    raw = json.loads(txt)
    if isinstance(raw, dict):
        ev = raw.get("events")
        return ev if isinstance(ev, list) else []
    return raw if isinstance(raw, list) else []


def _load_recent_from_file(path):
    if not path:
        return []
    if not os.path.exists(path):
        return []
    raw = _read_json(path)
    if isinstance(raw, dict):
        ev = raw.get("events")
        return ev if isinstance(ev, list) else []
    return raw if isinstance(raw, list) else []


def _check_config(cfg):
    fsk = cfg.get("feature_set_keys") or {}
    fss = cfg.get("feature_subsets") or {}
    out = {}
    out["has_fsid_trend"] = "trend_4h_mtf_v1" in fsk
    out["has_fsid_breakout"] = "breakout_1h_v1" in fsk
    out["len_fsid_trend"] = len(fsk.get("trend_4h_mtf_v1") or [])
    out["len_fsid_breakout"] = len(fsk.get("breakout_1h_v1") or [])
    out["subset_lr_trend"] = len(((fss.get("lr") or {}).get("trend_4h_mtf_v1") or []))
    out["subset_rf_trend"] = len(((fss.get("rf") or {}).get("trend_4h_mtf_v1") or []))
    out["subset_xgb_breakout"] = len(((fss.get("xgb") or {}).get("breakout_1h_v1") or []))
    out["subset_nn_breakout"] = len(((fss.get("nn") or {}).get("breakout_1h_v1") or []))
    return out


def _check_runtime(events, pair_prefix):
    selected = [e for e in events if str(e.get("pair") or "").startswith(pair_prefix)]
    with_gate = 0
    zero_take = 0
    no_taker = 0
    pc_below = 0
    cov_events = 0
    cov_low_events = 0
    for e in selected:
        di = e.get("decision_info") or {}
        rr = di.get("reason") or e.get("trigger_block_reason") or e.get("reason")
        if rr == "arena_no_taker":
            no_taker += 1
        if rr == "pc_below_threshold":
            pc_below += 1
        a = di.get("arena") or e.get("arena") or {}
        g = a.get("gate") if isinstance(a, dict) else None
        if isinstance(g, dict):
            with_gate += 1
            if g.get("n_take") == 0:
                zero_take += 1
        m = a.get("models") if isinstance(a, dict) else None
        if isinstance(m, dict) and m:
            has_cov = False
            low = False
            for mv in m.values():
                if isinstance(mv, dict) and mv.get("feature_coverage") is not None:
                    has_cov = True
                    if mv.get("eligible_reason") == "feature_coverage_low":
                        low = True
            if has_cov:
                cov_events += 1
            if low:
                cov_low_events += 1
    return {
        "events": len(selected),
        "with_gate": with_gate,
        "zero_take_rate": (zero_take / with_gate) if with_gate else None,
        "arena_no_taker_rate": (no_taker / len(selected)) if selected else None,
        "pc_below_threshold_rate": (pc_below / len(selected)) if selected else None,
        "feature_cov_events": cov_events,
        "feature_cov_low_rate": (cov_low_events / cov_events) if cov_events else None,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default="user_data/ml_config.json")
    ap.add_argument("--base-url", default="http://localhost:3001")
    ap.add_argument("--limit", type=int, default=300)
    ap.add_argument("--pair-prefix", default="BTC")
    ap.add_argument("--source-file", default="")
    ap.add_argument("--out", default="user_data/replay_stats/chain_check_latest.json")
    args = ap.parse_args()

    cfg = _read_json(args.config)
    config_check = _check_config(cfg)
    source_mode = "api"
    try:
        events = _fetch_recent(args.base_url, args.limit)
    except Exception:
        events = []
        source_mode = "file"
    if not events:
        fp = args.source_file.strip()
        if not fp:
            cand = [
                "/tmp/signals_after_open100.json",
                "/tmp/signals_open_post200.json",
                "/tmp/signals_open_post.json",
                "/tmp/signals_open.json",
            ]
            fp = next((x for x in cand if os.path.exists(x)), "")
        events = _load_recent_from_file(fp)
        if fp:
            source_mode = f"file:{fp}"
    runtime_check = _check_runtime(events, args.pair_prefix)

    passed = (
        config_check["has_fsid_trend"]
        and config_check["has_fsid_breakout"]
        and config_check["len_fsid_trend"] >= 30
        and config_check["len_fsid_breakout"] >= 35
        and config_check["subset_lr_trend"] >= 6
        and runtime_check["events"] > 0
    )
    out = {
        "pass": bool(passed),
        "source_mode": source_mode,
        "config_check": config_check,
        "runtime_check": runtime_check,
    }
    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    print(json.dumps(out, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
