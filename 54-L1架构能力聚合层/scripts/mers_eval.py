"""MERS S3 真实数据验收执行器（#35）。

在真实 DAL 序列上跑固定 180 单元网格，汇总门禁/显著性/状态分布，并做第二轮
全量复跑验证幂等（registry 行数零增长）。

用法（云端）::

    PYTHONPATH=<54 根> python3 scripts/mers_eval.py \
        --db 19-数据访问层/data/dreambuddy_core.db \
        --registry data/mers/registry.db \
        --out acceptance_bundles/20261115_mers_real_data/mers_summary.json

只读 DAL；registry 为 54 自有产物（`data/` 已 gitignore），不写任何 `mm_*` 表。
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import sqlite3
from collections import Counter
from typing import Any, Dict, List, Optional, Sequence, Tuple

from l1agg import align
from l1agg.mers import RelationshipRegistry, evaluate_grid, load_grid

MIN_N = 250
DEFAULT_DB = "19-数据访问层/data/dreambuddy_core.db"
DEFAULT_REGISTRY = "data/mers/registry.db"

# 指标 → BTC 日线（sub_category, metric_name）
INDICATORS: Tuple[Tuple[str, str], ...] = (
    ("DGS10", "value"),
    ("NASDAQCOM", "value"),
    ("SP500", "value"),
    ("VIXCLS", "value"),
    ("T10Y2Y", "value"),
    ("DCOILWTICO", "value"),
    ("DTWEXBGS", "value"),
    ("crypto_fear_greed", "value"),
    ("funding_rate", "funding_rate_pct"),
)

BTC = "BTC/USDT"


def _daily_close(cur: sqlite3.Cursor, sub_category: str, metric_name: str) -> Dict[str, float]:
    rows = cur.execute(
        "SELECT timestamp, metric_value FROM mm_metrics "
        "WHERE sub_category=? AND metric_name=? ORDER BY timestamp",
        (sub_category, metric_name),
    ).fetchall()
    out: Dict[str, float] = {}
    for ts, value in rows:
        day = dt.datetime.fromtimestamp(int(ts), dt.timezone.utc).date().isoformat()
        out[day] = float(value)  # 同日多观测取最后一个（与 align.py 口径一致）
    return out


def _price_assets(cur: sqlite3.Cursor) -> List[str]:
    rows = cur.execute(
        "SELECT sub_category, COUNT(*) c FROM mm_metrics "
        "WHERE metric_name='close_1d' GROUP BY 1 ORDER BY c DESC"
    ).fetchall()
    return [str(r[0]) for r in rows]


def _build_jobs(db: str) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    try:
        cur = con.cursor()
        assets = _price_assets(cur)
        btc = _daily_close(cur, BTC, "close_1d")

        jobs: List[Dict[str, Any]] = []
        skipped: List[Dict[str, Any]] = []
        for asset in assets:
            series = _daily_close(cur, asset, "close_1d")
            days = sorted(series)
            if len(days) < MIN_N:
                skipped.append(
                    {
                        "dataset": "market",
                        "metric": "close_1d",
                        "target": asset,
                        "reason": "insufficient_samples",
                        "n": len(days),
                    }
                )
                continue
            jobs.append(
                {
                    "dataset": "market",
                    "metric": "close_1d",
                    "target": asset,
                    "n": len(days),
                    "signal": [series[d] for d in days],
                    "prices": [series[d] for d in days],
                }
            )

        for sub_category, metric_name in INDICATORS:
            factor = _daily_close(cur, sub_category, metric_name)
            if not factor:
                skipped.append(
                    {
                        "dataset": "macro",
                        "metric": sub_category,
                        "target": BTC,
                        "reason": "empty_series",
                        "n": 0,
                    }
                )
                continue
            try:
                aligned = align.align(factor, btc, min_n=MIN_N)
            except align.AlignError as exc:
                skipped.append(
                    {
                        "dataset": "macro",
                        "metric": sub_category,
                        "target": BTC,
                        "reason": str(exc),
                        "n": 0,
                    }
                )
                continue
            if aligned.n < MIN_N:
                skipped.append(
                    {
                        "dataset": "macro",
                        "metric": sub_category,
                        "target": BTC,
                        "reason": "insufficient_samples",
                        "n": aligned.n,
                    }
                )
                continue
            jobs.append(
                {
                    "dataset": "macro",
                    "metric": sub_category,
                    "target": BTC,
                    "n": aligned.n,
                    "signal": aligned.factor,
                    "prices": aligned.price,
                }
            )
        return jobs, skipped
    finally:
        con.close()


def _summarize(job: Dict[str, Any], records: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    passed = [r for r in records if r.get("gate_pass")]
    status = Counter(str(r.get("status")) for r in records)
    method_gate = Counter(str(r.get("method_gate")) for r in records)
    best = sorted(
        (r for r in records if r.get("p_adj") is not None),
        key=lambda r: float(r["p_adj"]),
    )[:3]
    return {
        "dataset": job["dataset"],
        "metric": job["metric"],
        "target": job["target"],
        "n": job["n"],
        "units": len(records),
        "gate_pass": len(passed),
        "status": dict(status),
        "method_gate": dict(method_gate),
        "top_p_adj": [
            {
                "transform": r.get("transform"),
                "method": r.get("method"),
                "horizon": r.get("horizon"),
                "p_adj": r.get("p_adj"),
                "rank_ic": r.get("rank_ic"),
                "gate_pass": r.get("gate_pass"),
            }
            for r in best
        ],
    }


def _pass(
    jobs: List[Dict[str, Any]], registry: RelationshipRegistry, run_id: str, data_version: str
) -> Tuple[List[Dict[str, Any]], int]:
    out: List[Dict[str, Any]] = []
    for job in jobs:
        records = evaluate_grid(
            registry=registry,
            dataset=job["dataset"],
            metric=job["metric"],
            signal=job["signal"],
            prices=job["prices"],
            target=job["target"],
            data_version=data_version,
            run_id=run_id,
        )
        out.append(_summarize(job, records))
    return out, registry.count_evals()


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="MERS S3 真实数据验收")
    parser.add_argument("--db", default=DEFAULT_DB)
    parser.add_argument("--registry", default=DEFAULT_REGISTRY)
    parser.add_argument("--out", default="")
    parser.add_argument("--run-id", default="mers-real-data")
    parser.add_argument("--data-version", default=dt.date.today().isoformat())
    parser.add_argument(
        "--prune-days",
        type=int,
        default=0,
        help="保留最近 N 天评估行（0=不清理）；relationship_state 始终保留",
    )
    args = parser.parse_args(argv)

    if not os.path.exists(args.db):
        print(f"[FAIL] db not found: {args.db}")
        return 2
    os.makedirs(os.path.dirname(args.registry) or ".", exist_ok=True)
    registry = RelationshipRegistry(args.registry)

    jobs, skipped = _build_jobs(args.db)
    first, rows_after_first = _pass(jobs, registry, args.run_id, args.data_version)
    second, rows_after_second = _pass(jobs, registry, args.run_id, args.data_version)

    totals = {
        "jobs": len(jobs),
        "units": sum(j["units"] for j in first),
        "gate_pass": sum(j["gate_pass"] for j in first),
        "skipped": len(skipped),
    }
    totals["gate_pass_rate"] = (
        round(totals["gate_pass"] / totals["units"], 4) if totals["units"] else None
    )
    status_total: Counter = Counter()
    for job in first:
        status_total.update(job["status"])
    significant = sum(
        1
        for job in first
        for row in job["top_p_adj"]
        if row["p_adj"] is not None and float(row["p_adj"]) < 0.05 and row["gate_pass"]
    )
    summary = {
        "run_id": args.run_id,
        "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "db": os.path.abspath(args.db),
        "grid_hash": load_grid()["grid_hash"],
        "data_version": args.data_version,
        "totals": totals,
        "status": dict(status_total),
        "significant_units_top3": significant,
        "idempotency": {
            "rows_after_first_pass": rows_after_first,
            "rows_after_second_pass": rows_after_second,
            "added": rows_after_second - rows_after_first,
        },
        "skipped": skipped,
        "jobs": first,
    }
    if second != first:
        summary["second_pass_mismatch"] = True

    retention: Dict[str, Any] = {"keep_days": args.prune_days, "pruned_rows": 0}
    if args.prune_days > 0:
        cutoff = (
            dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=int(args.prune_days))
        ).isoformat()
        retention["cutoff"] = cutoff
        retention["pruned_rows"] = registry.prune_before(cutoff)
        retention["rows_after_prune"] = registry.count_evals()
    summary["retention"] = retention

    text = json.dumps(summary, ensure_ascii=False, indent=2)
    if args.out:
        os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
        with open(args.out, "w", encoding="utf-8") as handle:
            handle.write(text + "\n")
    print(
        json.dumps({k: summary[k] for k in ("totals", "status", "idempotency")}, ensure_ascii=False)
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
