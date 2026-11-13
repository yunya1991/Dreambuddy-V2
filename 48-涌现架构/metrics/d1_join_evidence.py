#!/usr/bin/env python3
"""D1 交易证据链 join 证据生成器（Phase 1 / T1-1）。

职责：
  1. 按 SPEC §12.1 的 G-BCL-1 口径，产出 `decision_id → order_id → fill_id → pnl → training_event_id`
     的逐条证据，供 `bcl_gate_check.py --training-events` 判定；
  2. 显式记录每条事件的匹配方式与缺口原因，禁止用模糊匹配冒充精确 join。

匹配优先级（严格降级，且必须标注）：
  decision_id   执行记录回写了 decision_id 时精确匹配（当前主路径：22 纸面成交账本）
  symbol_window 标的归一化 + intent_date 与决策时间相差 ≤ WINDOW_DAYS
  none          无任何匹配

执行事实来源（DEC-BCL-07）：40 是意图/验证场，**执行层是 22**；
默认执行源为 `22-执行引擎中心/audit/x1_paper_fills.jsonl`（venue=paper）。

纪律：
  - 只读 22/40/50 数据，不写任何生产文件；
  - MULTI 决策没有单一标的，不得用任意标的凑匹配，直接记 `multi_symbol_no_symbol`；
  - pnl 缺失即缺失，不得由外部行情估算填充；
  - 被拒绝/取价失败的执行记录不参与 join（无 order/fill 事实）。

输出：
  <out>/d1_join_evidence.jsonl   每行 {decision_id, order_id, fill_id, pnl, training_event_id, matched_by, gap_reason}
  <out>/d1_join_report.json      汇总统计
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timedelta
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_EVENTS = (
    _REPO_ROOT / "48-涌现架构" / "events" / "training_events" / "train_50_decisions.jsonl"
)
DEFAULT_EXEC = _REPO_ROOT / "22-执行引擎中心" / "audit" / "x1_paper_fills.jsonl"
DEFAULT_OUT = _REPO_ROOT / "48-涌现架构" / "metrics" / "artifacts"

WINDOW_DAYS = 3


def _parse_ts(value):
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None


def _norm_symbol(symbol):
    """BTC/USDT / BTC-USDT-SWAP / BTCUSDT → BTC；MULTI 返回 None。"""
    if not symbol or str(symbol).upper() == "MULTI":
        return None
    s = str(symbol).upper().replace("/", "-").replace("_", "-")
    for sep in ("-USDT-SWAP", "-USDT", "USDT"):
        if s.endswith(sep):
            return s[: -len(sep)] if s != sep else s
    return s


def _load_jsonl(path: Path):
    out = []
    if not path.exists():
        return out
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return out


def _exec_usable(rec):
    """执行记录是否构成成交事实（22 纸面账本：rejected/no_price 不算）。"""
    status = str(rec.get("status") or "")
    if status in ("rejected", "no_price", "close_failed"):
        return False
    return bool(rec.get("order_id") or (rec.get("fill") or {}).get("fill_id"))


def _exec_symbol(rec):
    if rec.get("symbol"):
        return rec["symbol"]
    return (rec.get("intent") or {}).get("symbol")


def _exec_day(rec):
    if rec.get("intent_date"):
        return str(rec["intent_date"])[:10]
    return str(rec.get("ts") or "")[:10]


def _index_execs(execs):
    """构建两类索引：decision_id 精确索引 + (symbol, date) 索引。"""
    by_decision = {}
    by_symbol_date = {}
    for rec in execs:
        if not _exec_usable(rec):
            continue
        did = rec.get("decision_id")
        if did:
            prev = by_decision.get(did)
            # 同一决策可能先落 open（pnl=None）后落 closed；优先取有 pnl 的成交
            if prev is None or (prev.get("pnl") is None and rec.get("pnl") is not None):
                by_decision[did] = rec
        sym = _norm_symbol(_exec_symbol(rec))
        day = _exec_day(rec)
        if sym and day:
            by_symbol_date.setdefault((sym, day), []).append(rec)
    return by_decision, by_symbol_date


def build_evidence(events_path: Path, exec_path: Path):
    events = _load_jsonl(events_path)
    execs = _load_jsonl(exec_path)
    by_decision, by_symbol_date = _index_execs(execs)

    evidence = []
    stats = {
        "events_total": len(events),
        "exec_records": len(execs),
        "exec_usable_records": sum(1 for r in execs if _exec_usable(r)),
        "exec_venue": {
            str(v): sum(1 for r in execs if str(r.get("venue") or "") == str(v))
            for v in {str(r.get("venue") or "unknown") for r in execs}
        },
        "matched_by_decision_id": 0,
        "matched_by_symbol_window": 0,
        "unmatched": 0,
        "gap_reason": {},
        "exec_without_decision_id": sum(1 for r in execs if not r.get("decision_id")),
    }

    for ev in events:
        did = ev.get("decision_id")
        exec_block = ev.get("execution") or {}
        matched = None
        matched_by = "none"
        gap_reason = ""

        # 1) 事件自身已带执行结果（历史回填）
        if exec_block.get("order_id") or exec_block.get("fill"):
            matched = {
                "order_id": exec_block.get("order_id"),
                "fill": exec_block.get("fill"),
                "pnl": (ev.get("pnl") or {}).get("value"),
            }
            matched_by = "event_prefilled"
        # 2) 40 域回写 decision_id → 精确匹配
        elif did and did in by_decision:
            matched = by_decision[did]
            matched_by = "decision_id"
        # 3) 标的 + 日期窗
        else:
            sym = _norm_symbol(ev.get("symbol"))
            ts = _parse_ts(ev.get("ts"))
            if ev.get("symbol") == "MULTI" or sym is None:
                gap_reason = "multi_symbol_no_symbol"
            elif not ts:
                gap_reason = "event_ts_unparseable"
            else:
                candidates = []
                for offset in range(-WINDOW_DAYS, WINDOW_DAYS + 1):
                    day = (ts + timedelta(days=offset)).date().isoformat()
                    candidates.extend(by_symbol_date.get((sym, day), []))
                if candidates:
                    matched = candidates[0]
                    matched_by = "symbol_window"
                else:
                    gap_reason = "no_exec_record_in_window"

        order_id = fill_id = pnl = None
        if matched:
            order_id = matched.get("order_id")
            fill_id = matched.get("fill_id")
            fill = matched.get("fill")
            if not fill_id and isinstance(fill, dict):
                fill_id = fill.get("fill_id") or fill.get("id")
            elif not fill_id and fill:
                fill_id = str(fill)
            pnl = matched.get("pnl")
            if pnl is None and str(matched.get("status") or "") == "open":
                gap_reason = "position_still_open"
            elif pnl is None and matched.get("order_placed") is False:
                gap_reason = "order_not_placed"

        if matched_by == "decision_id":
            stats["matched_by_decision_id"] += 1
        elif matched_by in ("symbol_window", "event_prefilled"):
            stats["matched_by_symbol_window"] += 1
        else:
            stats["unmatched"] += 1

        if not order_id and not gap_reason:
            gap_reason = "exec_has_no_order_id"
        if order_id and not fill_id and not gap_reason:
            gap_reason = "order_without_fill"
        if fill_id and pnl is None and not gap_reason:
            gap_reason = "fill_without_pnl"

        if gap_reason:
            stats["gap_reason"][gap_reason] = stats["gap_reason"].get(gap_reason, 0) + 1

        evidence.append(
            {
                "decision_id": did,
                "order_id": order_id,
                "fill_id": fill_id,
                "pnl": pnl,
                "training_event_id": ev.get("event_id"),
                "matched_by": matched_by,
                "gap_reason": gap_reason,
            }
        )

    stats["both_decision_and_order"] = sum(
        1 for e in evidence if e["decision_id"] and e["order_id"]
    )
    stats["full_chain_rows"] = sum(
        1
        for e in evidence
        if e["decision_id"]
        and e["order_id"]
        and e["fill_id"]
        and e["pnl"] is not None
        and e["training_event_id"]
    )
    stats["join_coverage_strict"] = (
        round(stats["full_chain_rows"] / len(evidence), 6) if evidence else 0.0
    )
    return evidence, stats


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="D1 join 证据生成")
    ap.add_argument("--events", default=str(DEFAULT_EVENTS))
    ap.add_argument("--executions", default=str(DEFAULT_EXEC))
    ap.add_argument("--out", default=str(DEFAULT_OUT))
    args = ap.parse_args(argv)

    events_path = Path(args.events)
    exec_path = Path(args.executions)
    for p in (events_path, exec_path):
        if not p.exists():
            print(json.dumps({"ok": False, "error": f"missing: {p}"}, ensure_ascii=False))
            return 2

    evidence, stats = build_evidence(events_path, exec_path)

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    evidence_path = out_dir / "d1_join_evidence.jsonl"
    report_path = out_dir / "d1_join_report.json"

    evidence_path.write_text(
        "\n".join(json.dumps(e, ensure_ascii=False) for e in evidence) + "\n",
        encoding="utf-8",
    )
    report = {
        "spec_ref": "1-ARCHITECTURE/SPEC-20261113-THREE-BUSINESS-CLOSED-LOOPS.md@v0.3.2",
        "events": str(events_path),
        "executions": str(exec_path),
        "evidence": str(evidence_path),
        "stats": stats,
    }
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
