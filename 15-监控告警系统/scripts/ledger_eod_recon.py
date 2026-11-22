#!/usr/bin/env python3
"""日终正式对账（SPEC-LEDGER-DOMAIN-ATTRIBUTION P2-6）。

控制总数三向核对：
  ① 交易所持仓快照（L0）
  ② 账户总账 positions（L1）
  ③ 域子账 domain_positions 与批次 position_lots（L2）

输出 Markdown + JSON；任一控制总数不平即非零退出，便于 systemd/cron 告警。
只读账本（不开写事务），不做任何账务修正——差异交 recon_breaks/janitor 处理。

用法：
  python3 scripts/ledger_eod_recon.py --positions-json /tmp/okx_positions.json --md
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, List

BASE_DIR = Path(__file__).resolve().parent.parent
REPO_ROOT = BASE_DIR.parent
_LEDGER_DIR = REPO_ROOT / "22-执行引擎中心"
if str(_LEDGER_DIR) not in sys.path:
    sys.path.insert(0, str(_LEDGER_DIR))

from position_ledger import PositionLedger  # noqa: E402

_EPS = 1e-9


def _load_positions(path: str) -> List[Dict[str, Any]]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if isinstance(data, dict):
        data = data.get("positions") or []
    out = []
    for p in data or []:
        out.append(
            {
                "inst_id": str(p.get("inst_id") or ""),
                "pos_side": str(p.get("pos_side") or "").lower(),
                "qty": float(p.get("qty") or p.get("pos") or 0.0),
                "avg_entry": float(p.get("avg_entry") or p.get("avg_px") or 0.0),
            }
        )
    return out


def build_report(ledger: PositionLedger, exchange: List[Dict[str, Any]]) -> Dict[str, Any]:
    l1 = {f"{r['inst_id']}:{r['pos_side']}": r for r in ledger.list_positions()}
    l2: Dict[str, Dict[str, float]] = {}
    for d in ledger.list_domain_positions(include_closed=False):
        k = f"{d['inst_id']}:{d['pos_side']}"
        slot = l2.setdefault(k, {"qty": 0.0, "notional": 0.0, "domains": []})
        slot["qty"] += float(d["qty"])
        slot["notional"] += float(d["qty"]) * float(d.get("avg_entry") or 0.0)
        slot["domains"].append({"domain": d["domain"], "qty": d["qty"]})
    lots: Dict[str, float] = {}
    for lot in ledger.list_lots(only_open=True):
        k = f"{lot['inst_id']}:{lot['pos_side']}"
        lots[k] = lots.get(k, 0.0) + float(lot.get("remaining_qty") or 0.0)
    ex = {f"{p['inst_id']}:{p['pos_side']}": p for p in exchange}

    rows = []
    for k in sorted(set(l1) | set(l2) | set(ex)):
        _l1 = float(l1.get(k, {}).get("qty") or 0.0)
        _l2 = float(l2.get(k, {}).get("qty") or 0.0)
        _lot = float(lots.get(k, 0.0))
        _ex = float(ex.get(k, {}).get("qty") or 0.0)
        rows.append(
            {
                "key": k,
                "exchange_qty": round(_ex, 9),
                "positions_qty": round(_l1, 9),
                "domain_qty": round(_l2, 9),
                "lots_qty": round(_lot, 9),
                "exchange_vs_l1": round(_ex - _l1, 9),
                "l1_vs_l2": round(_l1 - _l2, 9),
                "l2_vs_lots": round(_l2 - _lot, 9),
                "domains": l2.get(k, {}).get("domains", []),
                "balanced": all(abs(v) <= _EPS for v in (_ex - _l1, _l1 - _l2, _l2 - _lot)),
            }
        )

    l1_total = round(ledger.position_qty_sum(), 9)
    l2_total = round(ledger.domain_qty_sum(), 9)
    lot_total = round(sum(lots.values()), 9)
    ex_total = round(sum(p["qty"] for p in exchange), 9)
    open_breaks = {}
    for kind in (
        "missing_in_ledger",
        "orphan_in_ledger",
        "qty_drift",
        "price_drift",
        "stale_position",
        "over_close",
        "duplicate_open",
    ):
        open_breaks[kind] = len(ledger.list_breaks(state="OPEN", kind=kind, limit=500))
    balanced = (
        abs(l1_total - l2_total) <= _EPS
        and abs(l2_total - lot_total) <= _EPS
        and all(r["balanced"] for r in rows)
    )
    return {
        "db": str(ledger.path),
        "balanced": balanced,
        "totals": {
            "exchange_qty": ex_total,
            "positions_qty": l1_total,
            "domain_qty": l2_total,
            "lots_qty": lot_total,
            "positions_vs_domain": round(l1_total - l2_total, 9),
            "domain_vs_lots": round(l2_total - lot_total, 9),
        },
        "open_breaks": open_breaks,
        "rows": rows,
        "feed_state": ledger.get_feed_state(),
    }


def render_markdown(report: Dict[str, Any]) -> str:
    t = report["totals"]
    status = "PASS" if report["balanced"] else "FAIL"
    lines = [
        f"# 账本日终对账 {status}",
        "",
        f"- DB: `{report['db']}`",
        f"- feed_state: `{report['feed_state']}`",
        "",
        "## 控制总数",
        "| 口径 | 数量 |",
        "|---|---|",
        f"| 交易所 L0 | {t['exchange_qty']} |",
        f"| 总账 L1 | {t['positions_qty']} |",
        f"| 域子账 L2 | {t['domain_qty']} |",
        f"| 批次 lots | {t['lots_qty']} |",
        f"| L1-L2 | {t['positions_vs_domain']} |",
        f"| L2-lots | {t['domain_vs_lots']} |",
        "",
        "## 活跃工单",
        "| kind | OPEN |",
        "|---|---|",
    ]
    for k, v in report["open_breaks"].items():
        lines.append(f"| {k} | {v} |")
    lines += [
        "",
        "## 明细",
        "| 标的 | 交易所 | L1 | L2 | lots | L1-L2 | L2-lots | 域 | 平 |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for r in report["rows"]:
        doms = ",".join(f"{d['domain']}:{d['qty']}" for d in r["domains"]) or "-"
        lines.append(
            f"| {r['key']} | {r['exchange_qty']} | {r['positions_qty']} | {r['domain_qty']} |"
            f" {r['lots_qty']} | {r['l1_vs_l2']} | {r['l2_vs_lots']} | {doms} |"
            f" {'Y' if r['balanced'] else 'N'} |"
        )
    return "\n".join(lines)


def main(argv: List[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="账本日终对账（只读）")
    parser.add_argument("--db", default=os.getenv("POSITION_LEDGER_PATH"))
    parser.add_argument("--positions-json", help="交易所持仓快照 JSON")
    parser.add_argument("--okx", action="store_true", help="直接经 OKX 客户端拉取持仓（生产）")
    parser.add_argument("--md", action="store_true", help="输出 Markdown（默认 JSON）")
    parser.add_argument("--out", help="写入文件")
    args = parser.parse_args(argv)

    ledger = PositionLedger(args.db)
    try:
        if args.okx:
            from ledger_janitor import _fetch_okx_positions  # noqa: PLC0415

            exchange = [
                {
                    "inst_id": str(p.get("inst_id") or ""),
                    "pos_side": str(p.get("pos_side") or "").lower(),
                    "qty": float(p.get("pos") or p.get("qty") or 0.0),
                    "avg_entry": float(p.get("avg_px") or p.get("avg_entry") or 0.0),
                }
                for p in _fetch_okx_positions()
            ]
        elif args.positions_json:
            exchange = _load_positions(args.positions_json)
        else:
            exchange = []
    except (OSError, ValueError, RuntimeError, ImportError) as exc:
        print(json.dumps({"ok": False, "reason": f"positions_invalid: {exc}"}, ensure_ascii=False))
        return 2
    report = build_report(ledger, exchange)
    text = render_markdown(report) if args.md else json.dumps(report, ensure_ascii=False, indent=2)
    if args.out:
        Path(args.out).write_text(text, encoding="utf-8")
    print(text)
    return 0 if report["balanced"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
