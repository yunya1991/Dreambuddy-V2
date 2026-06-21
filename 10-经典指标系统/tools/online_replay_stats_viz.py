#!/usr/bin/env python3
import argparse
import json
import os
from collections import Counter, defaultdict
from datetime import datetime
from urllib import parse, request

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt


def _load_events_from_file(path: str):
    if not path:
        return []
    if not os.path.exists(path):
        return []
    raw = json.load(open(path, "r", encoding="utf-8"))
    if isinstance(raw, dict):
        ev = raw.get("events")
        return ev if isinstance(ev, list) else []
    return raw if isinstance(raw, list) else []


def _fetch_events(base_url: str, limit: int):
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


def _stats(events, pair_prefix: str):
    selected = []
    for e in events:
        p = str(e.get("pair") or "")
        if pair_prefix and not p.startswith(pair_prefix):
            continue
        selected.append(e)
    dec = Counter()
    reason = Counter()
    n_take = Counter()
    fsid = Counter()
    model_cov_low = Counter()
    model_cov_seen = Counter()
    with_gate = 0
    zero_take = 0
    cov_events = 0
    cov_low_events = 0
    for e in selected:
        di = e.get("decision_info") or {}
        dec[di.get("decision") or e.get("decision") or "unknown"] += 1
        rr = di.get("reason") or e.get("trigger_block_reason") or e.get("reason")
        if rr:
            reason[str(rr)] += 1
        fsid[str(e.get("feature_set_id") or "NA")] += 1
        a = di.get("arena") or e.get("arena") or {}
        g = a.get("gate") if isinstance(a, dict) else None
        if isinstance(g, dict):
            with_gate += 1
            nt = g.get("n_take")
            n_take[str(nt)] += 1
            if nt == 0:
                zero_take += 1
        models = a.get("models") if isinstance(a, dict) else None
        if isinstance(models, dict) and models:
            has_cov = False
            low = False
            for mid, mv in models.items():
                if not isinstance(mv, dict):
                    continue
                if mv.get("feature_coverage") is not None:
                    has_cov = True
                    model_cov_seen[str(mid)] += 1
                    if mv.get("eligible_reason") == "feature_coverage_low":
                        model_cov_low[str(mid)] += 1
                        low = True
            if has_cov:
                cov_events += 1
            if low:
                cov_low_events += 1
    out = {
        "events": len(selected),
        "with_gate": with_gate,
        "zero_take": zero_take,
        "zero_take_rate": (zero_take / with_gate) if with_gate else None,
        "arena_no_taker_rate": (reason.get("arena_no_taker", 0) / len(selected)) if selected else None,
        "pc_below_threshold_rate": (reason.get("pc_below_threshold", 0) / len(selected)) if selected else None,
        "feature_cov_events": cov_events,
        "feature_cov_low_events": cov_low_events,
        "feature_cov_low_rate": (cov_low_events / cov_events) if cov_events else None,
        "decision_counts": dict(dec),
        "reason_counts": dict(reason),
        "n_take_counts": dict(n_take),
        "feature_set_counts": dict(fsid),
        "model_cov_low_rate": {
            mid: (model_cov_low[mid] / model_cov_seen[mid]) if model_cov_seen[mid] else None
            for mid in sorted(model_cov_seen.keys())
        },
    }
    return out


def _plot_counts(ax, counter_dict, title, top_n=10):
    items = sorted(counter_dict.items(), key=lambda x: x[1], reverse=True)[:top_n]
    labels = [k for k, _ in items]
    vals = [v for _, v in items]
    ax.bar(range(len(vals)), vals)
    ax.set_title(title)
    ax.set_xticks(range(len(vals)))
    ax.set_xticklabels(labels, rotation=35, ha="right", fontsize=8)


def _plot_rates(ax, stats):
    keys = ["zero_take_rate", "arena_no_taker_rate", "pc_below_threshold_rate", "feature_cov_low_rate"]
    vals = [stats.get(k) for k in keys]
    vals = [0.0 if v is None else float(v) for v in vals]
    ax.bar(range(len(vals)), vals)
    ax.set_ylim(0, 1)
    ax.set_title("Core Rates")
    ax.set_xticks(range(len(vals)))
    ax.set_xticklabels(keys, rotation=30, ha="right", fontsize=8)


def _plot_model_cov(ax, model_cov_low_rate):
    items = sorted(model_cov_low_rate.items(), key=lambda x: (x[1] is None, -(x[1] or 0.0)))
    items = [x for x in items if x[1] is not None][:10]
    labels = [k for k, _ in items]
    vals = [v for _, v in items]
    if not vals:
        labels = ["none"]
        vals = [0.0]
    ax.bar(range(len(vals)), vals)
    ax.set_ylim(0, 1)
    ax.set_title("Model feature_coverage_low rate")
    ax.set_xticks(range(len(vals)))
    ax.set_xticklabels(labels, rotation=30, ha="right", fontsize=8)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base-url", default="http://localhost:3001")
    ap.add_argument("--limit", type=int, default=400)
    ap.add_argument("--pair-prefix", default="BTC")
    ap.add_argument("--out-dir", default="user_data/replay_stats")
    ap.add_argument("--source-file", default="")
    args = ap.parse_args()

    os.makedirs(args.out_dir, exist_ok=True)
    events = []
    source_mode = "api"
    try:
        events = _fetch_events(args.base_url, args.limit)
    except Exception:
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
        events = _load_events_from_file(fp)
        source_mode = f"file:{fp}" if fp else source_mode
    stats = _stats(events, args.pair_prefix)

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    json_path = os.path.join(args.out_dir, f"replay_stats_{args.pair_prefix}_{ts}.json")
    png_path = os.path.join(args.out_dir, f"replay_stats_{args.pair_prefix}_{ts}.png")

    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(stats, f, ensure_ascii=False, indent=2)

    fig, axes = plt.subplots(2, 2, figsize=(14, 9))
    _plot_counts(axes[0][0], stats.get("n_take_counts", {}), "n_take distribution", top_n=8)
    _plot_counts(axes[0][1], stats.get("reason_counts", {}), "reason distribution", top_n=10)
    _plot_rates(axes[1][0], stats)
    _plot_model_cov(axes[1][1], stats.get("model_cov_low_rate", {}))
    fig.tight_layout()
    fig.savefig(png_path, dpi=140)
    plt.close(fig)

    print(json.dumps({
        "source_mode": source_mode,
        "events": stats.get("events"),
        "with_gate": stats.get("with_gate"),
        "zero_take_rate": stats.get("zero_take_rate"),
        "arena_no_taker_rate": stats.get("arena_no_taker_rate"),
        "pc_below_threshold_rate": stats.get("pc_below_threshold_rate"),
        "feature_cov_low_rate": stats.get("feature_cov_low_rate"),
        "json_path": json_path,
        "png_path": png_path,
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
