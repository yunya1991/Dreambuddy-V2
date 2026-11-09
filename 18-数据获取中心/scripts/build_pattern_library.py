"""模式库构建脚本 — SPEC-D1 §2.5（P3）。shadow 只读产物，FAIL-OPEN。

输入：backfill/events_d1.jsonl + 日 K（yfinance 长历史 + ccxt 快照日聚合）
产出：backfill/patterns_d1.jsonl（run_meta 首行 + 每 pattern 一行）
用法：python scripts/build_pattern_library.py [--n-boot 5000]
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from data_center.processing.pattern_library import build_patterns, save_patterns  # noqa: E402
from scripts.backfill_newsflash_events import (  # noqa: E402
    DB,
    load_ccxt_daily,
    load_yfinance_daily,
)

EVENTS = ROOT / "backfill" / "events_d1.jsonl"
OUT = ROOT / "backfill" / "patterns_d1.jsonl"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--n-boot", type=int, default=5000)
    ap.add_argument("--seed", type=int, default=42)
    args = ap.parse_args()

    conn = sqlite3.connect(DB)
    merged = load_yfinance_daily(conn)
    merged.update(load_ccxt_daily(conn))
    prices = sorted((ts, c) for ts, c in merged.items())
    print(f"prices: {len(prices)} days")

    events = []
    if EVENTS.exists():
        for line in EVENTS.open(encoding="utf-8"):
            line = line.strip()
            if line:
                try:
                    events.append(json.loads(line))
                except ValueError:
                    continue
    print(f"events: {len(events)}")

    result = build_patterns(events, prices, n_boot=args.n_boot, seed=args.seed)
    ok = save_patterns(result, OUT)

    print(
        f"trials_count={result['trials_count']} mu0={result['mu0']:.6f} skipped={result['skipped']}"
    )
    for etype, fam in result["families"].items():
        print(f"  family {etype}: pbo={fam['pbo']} status={fam['pbo_status']}")
    n_cand = sum(1 for p in result["patterns"] if p.get("status") == "candidate")
    n_ver = sum(1 for p in result["patterns"] if p.get("status") == "verified")
    print(f"patterns={len(result['patterns'])} candidate={n_cand} verified={n_ver}")
    for p in result["patterns"]:
        sig = p["significance"]
        print(
            f"  {p['pattern_id']}: n={p['n_events']} "
            f"mean={p['reaction_dist']['T+24h']['mean']:+.4f} "
            f"holm_p={sig['holm_p']} spa_p={sig['spa_p']} "
            f"stable={p['direction_stable']} status={p.get('status')}"
        )
    print(f"→ {OUT} (saved={ok})")


if __name__ == "__main__":
    main()
