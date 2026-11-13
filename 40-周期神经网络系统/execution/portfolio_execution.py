#!/usr/bin/env python3
"""组合级执行记录（DEC-BCL-06 路径 C）。

X0 的 `execution_trades.jsonl` 是逐标的意图流；50 的决策是组合级（一个决策覆盖多腿，
历史事件 symbol 为 MULTI）。路径 C 在两者之间补一层"组合级执行记录"：
同一 decision_id 下的多腿聚合成一条 batch 记录，承载 notional_total / pnl_total / 成交进度。

红线：
- 只聚合已落盘事实，不推断成交；无 fill 时 status=planned、pnl_total=null；
- 幂等：同一 (intent_date, source, decision_id, 标的集合) 只写一条；
- fail-open：任何异常不阻断 X0 主流程。

CLI：
  python3 portfolio_execution.py --date 2026-11-13 --out /tmp/portfolio_executions.jsonl
"""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import date, datetime, timezone
from pathlib import Path

BASE = Path(__file__).resolve().parent
ROOT = BASE.parent
DEFAULT_TRADES = ROOT / "execution_trades.jsonl"
DEFAULT_OUT = ROOT / "portfolio_executions.jsonl"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _load_jsonl(path) -> list:
    p = Path(path)
    if not p.exists():
        return []
    rows = []
    with p.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(obj, dict):
                rows.append(obj)
    return rows


def _fill_id(record: dict):
    fill = record.get("fill")
    if isinstance(fill, dict):
        return fill.get("fill_id") or fill.get("id")
    return None


def _batch_key(intent_date: str, source: str, decision_id, symbols) -> str:
    raw = "|".join([intent_date or "", source or "", decision_id or "", ",".join(sorted(symbols))])
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def build_batches(records: list, intent_date: str) -> list:
    """同一决策下的成交腿聚合成组合级 batch（按 decision_id 分组，未关联归入 unlinked）。"""
    groups = {}
    for r in records:
        if str(r.get("intent_date") or "")[:10] != intent_date:
            continue
        intent = r.get("intent") or {}
        source = (r.get("signal_snapshot") or {}).get("source") or ""
        decision_id = r.get("decision_id")
        key = decision_id or f"unlinked:{source}"
        groups.setdefault(key, []).append((r, intent, source))

    batches = []
    for key, items in groups.items():
        legs = []
        for r, intent, _source in items:
            legs.append(
                {
                    "symbol": r.get("symbol"),
                    "direction": intent.get("direction"),
                    "notional_usdt": intent.get("notional_usdt"),
                    "decision_id": r.get("decision_id"),
                    "order_id": r.get("order_id"),
                    "fill_id": _fill_id(r),
                    "pnl": r.get("pnl"),
                }
            )
        fills = [leg for leg in legs if leg.get("fill_id")]
        if fills and len(fills) == len(legs):
            status = "filled"
        elif fills:
            status = "partially_filled"
        else:
            status = "planned"
        pnl_values = [leg.get("pnl") for leg in legs]
        pnl_total = (
            sum(pnl_values) if pnl_values and all(v is not None for v in pnl_values) else None
        )
        source = items[0][2]
        symbols = [leg["symbol"] for leg in legs if leg.get("symbol")]
        batches.append(
            {
                "ts": _now_iso(),
                "intent_date": intent_date,
                "source": source,
                "scope": "portfolio",
                "stage": items[0][0].get("stage") or "X0",
                "decision_id": None if key.startswith("unlinked:") else key,
                "batch_key": _batch_key(
                    intent_date, source, None if key.startswith("unlinked:") else key, symbols
                ),
                "legs": legs,
                "leg_count": len(legs),
                "notional_total": sum(leg.get("notional_usdt") or 0 for leg in legs),
                "fill_count": len(fills),
                "pnl_total": pnl_total,
                "status": status,
            }
        )
    return batches


def aggregate_day(date_str: str, trades_path=None, out_path=None, decisions_path=None) -> dict:
    """聚合指定日期为组合级执行记录；返回 {written, skipped, batches}。"""
    trades_path = Path(trades_path) if trades_path else DEFAULT_TRADES
    out_path = Path(out_path) if out_path else DEFAULT_OUT
    stats = {"written": 0, "skipped": 0, "batches": 0}
    try:
        batches = build_batches(_load_jsonl(trades_path), date_str)
    except OSError:
        return stats
    stats["batches"] = len(batches)
    if not batches:
        return stats

    existing = {row.get("batch_key") for row in _load_jsonl(out_path)}
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("a", encoding="utf-8") as f:
        for batch in batches:
            if batch["batch_key"] in existing:
                stats["skipped"] += 1
                continue
            f.write(json.dumps(batch, ensure_ascii=False, sort_keys=True) + "\n")
            existing.add(batch["batch_key"])
            stats["written"] += 1
    return stats


def main() -> None:
    parser = argparse.ArgumentParser(description="组合级执行记录聚合（DEC-BCL-06 路径 C）")
    parser.add_argument("--date", default=date.today().isoformat())
    parser.add_argument("--trades", default=str(DEFAULT_TRADES))
    parser.add_argument("--out", default=str(DEFAULT_OUT))
    parser.add_argument("--decisions", default=None)
    args = parser.parse_args()
    print(
        json.dumps(
            aggregate_day(args.date, args.trades, args.out, args.decisions),
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
