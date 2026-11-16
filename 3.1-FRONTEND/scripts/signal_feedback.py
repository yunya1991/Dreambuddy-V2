#!/usr/bin/env python3
"""signal_feedback.py — 信号反馈表（TASKS-20261116 T9-4）。

只读两份数据，不做任何新统计口径：
  1) `54-L1架构能力聚合层/data/signal_ledger.db::signal_journal`（T6-4 paper 记账）
  2) L0 日线收盘价（`l1agg.align.load_leader`）

对每条 `allowed` 信号，取信号日之后 h 个交易日的收益（`align.forward_returns` 同口径），
按 `(target, horizon)` 做**非重叠采样**（`align.overlap_free_indices` 的等价规则：
相邻入选信号至少间隔 h 个交易日），因此：
  - 展示分母 `n_eff` 就是实际参与计数的样本数（与表格行数一致，不放大）；
  - `hit_rate = hits / n_eff`，`base_rate` 为同向基准（上涨占比按方向对齐）；
  - `excess_hit = hit_rate - base_rate`，与 MERS G1 的「超额命中」同义。

FAIL-OPEN：库缺失 / 价格缺失 → 空结果 + reason，不伪造命中率。
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.normpath(os.path.join(_SCRIPT_DIR, "..", ".."))
_L1_DIR = os.path.join(_REPO_ROOT, "54-L1架构能力聚合层")
if _L1_DIR not in sys.path:
    sys.path.insert(0, _L1_DIR)

DB_PATH = os.environ.get("DREAMBUDDY_CORE_DB") or os.path.join(
    _REPO_ROOT, "19-数据访问层", "data", "dreambuddy_core.db"
)

HORIZONS = (5, 20)
MAX_JOURNAL = 2000
BUCKET_ORDER = ("strong", "medium", "weak", "unknown")


def _price_map(symbol: str, days: int) -> Dict[str, float]:
    from l1agg.align import AlignError, load_leader

    try:
        return load_leader(DB_PATH, symbol, days=days)
    except (AlignError, FileNotFoundError, KeyError, ValueError):
        return {}


def _select_non_overlapping(rows: List[Dict[str, Any]], dates: List[str], horizon: int):
    """按日期升序贪心选非重叠窗口：相邻入选信号索引差 >= horizon。"""
    index_of = {day: idx for idx, day in enumerate(dates)}
    picked = []
    last_idx = -(10**9)
    for row in sorted(rows, key=lambda item: str(item.get("as_of") or "")):
        as_of = str(row.get("as_of") or "")[:10]
        idx = index_of.get(as_of)
        if idx is None:
            continue
        if idx - last_idx < horizon:
            continue
        if idx + horizon >= len(dates):
            continue
        picked.append((row, idx))
        last_idx = idx
    return picked


def _summarize(
    rows: List[Dict[str, Any]], prices: Dict[str, float], horizon: int
) -> Optional[Dict[str, Any]]:
    dates = sorted(prices)
    if not dates:
        return None
    picked = _select_non_overlapping(rows, dates, horizon)
    if not picked:
        return {
            "n_raw": len(rows),
            "n_eff": 0,
            "hits": 0,
            "hit_rate": None,
            "base_rate": None,
            "excess_hit": None,
            "avg_forward": None,
        }
    hits = 0
    ups = 0
    fwd_sum = 0.0
    for row, idx in picked:
        entry = prices[dates[idx]]
        exit_ = prices[dates[idx + horizon]]
        if not entry:
            continue
        fwd = exit_ / entry - 1.0
        fwd_sum += fwd
        if fwd > 0:
            ups += 1
        direction = int(row.get("direction") or 0)
        if (fwd > 0 and direction > 0) or (fwd < 0 and direction < 0):
            hits += 1
    n_eff = len(picked)
    if n_eff == 0:
        return None
    up_rate = ups / n_eff
    long_share = sum(1 for row, _ in picked if int(row.get("direction") or 0) > 0) / n_eff
    base_rate = long_share * up_rate + (1 - long_share) * (1 - up_rate)
    hit_rate = hits / n_eff
    return {
        "n_raw": len(rows),
        "n_eff": n_eff,
        "hits": hits,
        "hit_rate": round(hit_rate, 4),
        "base_rate": round(base_rate, 4),
        "excess_hit": round(hit_rate - base_rate, 4),
        "avg_forward": round(fwd_sum / n_eff, 6),
    }


def build(*, horizons=HORIZONS, limit: int = MAX_JOURNAL) -> Dict[str, Any]:
    from l1agg.signal_ledger import LEDGER_FILE, read_journal

    journal = read_journal(decision="allowed", limit=limit)
    if not journal:
        return {
            "ok": True,
            "as_of": datetime.now(timezone.utc).date().isoformat(),
            "horizons": [],
            "answer": "信号账本暂无 allowed 记录：先让 D-K03 产出并通过门控，再回填后验收益。",
            "quality": {"status": "empty", "sample_n": 0, "degraded_reason": "empty_journal"},
            "source": {"ledger": os.path.basename(LEDGER_FILE), "entries": 0},
        }

    price_cache: Dict[str, Dict[str, float]] = {}
    out = []
    for horizon in horizons:
        subset = [row for row in journal if int(row.get("horizon") or 0) == horizon]
        targets: List[Dict[str, Any]] = []
        bucket_rows: Dict[str, Dict[str, Any]] = {}
        total = {"n_raw": 0, "n_eff": 0, "hits": 0}
        for target in sorted({str(row.get("target") or "") for row in subset if row.get("target")}):
            target_rows = [row for row in subset if str(row.get("target")) == target]
            prices = price_cache.get(target)
            if prices is None:
                prices = _price_map(target, 1600)
                price_cache[target] = prices
            stats = _summarize(target_rows, prices, horizon)
            if stats is None:
                continue
            stats["target"] = target
            targets.append(stats)
            total["n_raw"] += stats["n_raw"]
            total["n_eff"] += stats["n_eff"]
            total["hits"] += stats["hits"]
            # 分档：只做计数聚合，命中率仍按 n_eff 分母
            for strength in {str(row.get("strength") or "unknown") for row in target_rows}:
                bucket = bucket_rows.setdefault(
                    strength, {"strength": strength, "n_eff": 0, "hits": 0}
                )
                bucket_stats = _summarize(
                    [
                        row
                        for row in target_rows
                        if str(row.get("strength") or "unknown") == strength
                    ],
                    prices,
                    horizon,
                )
                if bucket_stats:
                    bucket["n_eff"] += bucket_stats["n_eff"]
                    bucket["hits"] += bucket_stats["hits"]

        buckets = []
        for strength in BUCKET_ORDER:
            bucket = bucket_rows.get(strength)
            if not bucket or bucket["n_eff"] == 0:
                continue
            buckets.append(
                {
                    "strength": strength,
                    "n_eff": bucket["n_eff"],
                    "hits": bucket["hits"],
                    "hit_rate": round(bucket["hits"] / bucket["n_eff"], 4),
                }
            )

        targets.sort(key=lambda item: (-(item["n_eff"] or 0), item["target"]))
        totals = {
            "n_raw": total["n_raw"],
            "n_eff": total["n_eff"],
            "hits": total["hits"],
            "hit_rate": round(total["hits"] / total["n_eff"], 4) if total["n_eff"] else None,
        }
        out.append({"horizon": horizon, "totals": totals, "targets": targets, "buckets": buckets})

    return {
        "ok": True,
        "as_of": datetime.now(timezone.utc).date().isoformat(),
        "horizons": out,
        "answer": "信号反馈按非重叠窗口统计：分母 n_eff 与展示样本一致，未对重叠收益放大。",
        "quality": {
            "status": "good" if any(item["totals"]["n_eff"] for item in out) else "empty",
            "sample_n": sum(item["totals"]["n_eff"] for item in out),
            "degraded_reason": (
                "" if any(item["totals"]["n_eff"] for item in out) else "no_resolved_signals"
            ),
        },
        "source": {"ledger": os.path.basename(LEDGER_FILE), "entries": len(journal)},
    }


def main(argv=None):
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--horizons", default="5,20")
    parser.add_argument("--limit", type=int, default=MAX_JOURNAL)
    args, _ = parser.parse_known_args(argv or sys.argv[1:])
    horizons = tuple(int(item) for item in args.horizons.split(",") if item.strip().isdigit())
    try:
        payload = build(horizons=horizons or HORIZONS, limit=max(1, int(args.limit)))
    except Exception as exc:  # FAIL-OPEN：脚本异常 → 前端降级空态
        payload = {
            "ok": False,
            "horizons": [],
            "degraded": True,
            "error": f"{type(exc).__name__}: {exc}",
        }
    sys.stdout.write(json.dumps(payload, ensure_ascii=False, default=str) + "\n")


if __name__ == "__main__":
    main()
