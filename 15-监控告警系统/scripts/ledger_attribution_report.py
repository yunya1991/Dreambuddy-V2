#!/usr/bin/env python3
"""持仓标签日巡检（22/23/50 域归属汇总）。

每日汇总三类事实并出报告：
  ① 各域活跃持仓（domain_positions）：数量/张数/名义，识别 22/23/50 归属；
  ② 近 24h 成交标签覆盖率：source→domain 是否落标（空标签=漏标）；
  ③ 一致性告警：L1 有仓但无域归属、L1/L2 张数漂移、未知域编码。

只读账本，不做账务修正；有告警即非零退出，供 systemd/timer 告警。

用法：
  python3 scripts/ledger_attribution_report.py --since-hours 24 --md
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List

BASE_DIR = Path(__file__).resolve().parent.parent
REPO_ROOT = BASE_DIR.parent
_LEDGER_DIR = REPO_ROOT / "22-执行引擎中心"
if str(_LEDGER_DIR) not in sys.path:
    sys.path.insert(0, str(_LEDGER_DIR))

from position_ledger import PositionLedger  # noqa: E402

_EPS = 1e-9
_KNOWN_DOMAINS = {"11", "22", "23", "50", "6", "legacy"}
_REPORT_DIR = BASE_DIR / "runtime" / "reports"


def _parse_ts(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def build_report(ledger: PositionLedger, since_hours: float = 24.0) -> Dict[str, Any]:
    cutoff = datetime.now(timezone.utc) - timedelta(hours=max(0.1, float(since_hours)))

    l1 = [r for r in ledger.list_positions() if abs(float(r.get("qty") or 0)) > _EPS]
    l2 = [
        d
        for d in ledger.list_domain_positions(include_closed=False)
        if float(d.get("qty") or 0) > _EPS
    ]

    l2_by_key: Dict[str, float] = {}
    domains: Dict[str, Dict[str, float]] = {}
    for d in l2:
        key = f"{d['inst_id']}:{d['pos_side']}"
        l2_by_key[key] = l2_by_key.get(key, 0.0) + float(d["qty"])
        dom = str(d.get("domain") or "").lower() or "unknown"
        slot = domains.setdefault(dom, {"positions": 0, "qty": 0.0, "notional": 0.0})
        slot["positions"] += 1
        slot["qty"] += float(d["qty"])
        slot["notional"] += float(d["qty"]) * float(d.get("avg_entry") or 0.0)

    fills: List[Dict[str, Any]] = []
    for f in ledger.recent_fills(2000):
        ts = _parse_ts(f.get("ts"))
        if ts is not None and ts >= cutoff:
            fills.append(f)

    fill_stats: Dict[str, int] = {}
    sources: Dict[str, int] = {}
    unlabeled_fills = 0
    for f in fills:
        dom = str(f.get("domain") or "").lower()
        if not dom:
            unlabeled_fills += 1
            dom = "unknown"
        fill_stats[dom] = fill_stats.get(dom, 0) + 1
        src = str(f.get("source") or "") or "unknown"
        sources[src] = sources.get(src, 0) + 1

    alerts: List[str] = []
    unlabeled_positions: List[str] = []
    drift: List[Dict[str, Any]] = []
    for row in l1:
        key = f"{row['inst_id']}:{row['pos_side']}"
        l2_qty = l2_by_key.get(key)
        if l2_qty is None:
            unlabeled_positions.append(key)
        elif abs(float(row["qty"]) - l2_qty) > 1e-6:
            drift.append({"key": key, "l1_qty": float(row["qty"]), "l2_qty": round(l2_qty, 8)})
    if unlabeled_positions:
        alerts.append(
            f"未打域标签的持仓 {len(unlabeled_positions)} 个：{', '.join(unlabeled_positions[:5])}"
        )
    if drift:
        alerts.append(f"L1/L2 张数漂移 {len(drift)} 个：{', '.join(d['key'] for d in drift[:5])}")
    if unlabeled_fills:
        alerts.append(f"近 {since_hours:g}h 有 {unlabeled_fills} 笔成交缺 domain 标签")
    unknown_domains = sorted(
        {str(d.get("domain") or "").lower() for d in l2} - _KNOWN_DOMAINS - {""}
    )
    if unknown_domains:
        alerts.append(f"出现未知域编码：{', '.join(unknown_domains)}")

    # 三个受监控域始终展示（无仓也显式记 0，避免"没出现=漏监控"的歧义）
    for _d in ("22", "23", "50"):
        domains.setdefault(_d, {"positions": 0, "qty": 0.0, "notional": 0.0})
        fill_stats.setdefault(_d, 0)

    return {
        "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "since_hours": float(since_hours),
        "domains": domains,
        "fills_by_domain": fill_stats,
        "fills_by_source": sources,
        "unlabeled_fills": unlabeled_fills,
        "unlabeled_positions": unlabeled_positions,
        "drift": drift,
        "alerts": alerts,
        "ok": not alerts,
    }


def render_markdown(report: Dict[str, Any]) -> str:
    lines = [
        f"# 持仓标签日巡检（近 {report['since_hours']:g}h）",
        "",
        f"- 生成时间：{report['generated_at']}",
        f"- 结论：{'✅ 正常' if report['ok'] else '⚠️ 有告警'}",
        "",
        "## 各域活跃持仓",
        "",
        "| 域 | 持仓条目 | 张数 | 名义(USDT) |",
        "|---|---:|---:|---:|",
    ]
    for dom in sorted(report["domains"], key=lambda x: (x != "22", x != "23", x != "50", x)):
        d = report["domains"][dom]
        lines.append(f"| {dom} | {d['positions']} | {d['qty']:.4f} | {d['notional']:.2f} |")

    lines += [
        "",
        "## 近周期成交标签",
        "",
        "| 域 | 成交笔数 |",
        "|---|---:|",
    ]
    for dom, n in sorted(report["fills_by_domain"].items()):
        lines.append(f"| {dom} | {n} |")

    if report["fills_by_source"]:
        lines += [
            "",
            "来源明细："
            + "，".join(f"{k}={v}" for k, v in sorted(report["fills_by_source"].items())),
        ]

    lines += ["", "## 告警", ""]
    lines += [f"- {a}" for a in report["alerts"]] or ["- 无"]
    return "\n".join(lines) + "\n"


def main(argv: List[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="22/23/50 持仓标签日巡检")
    parser.add_argument("--since-hours", type=float, default=24.0)
    parser.add_argument("--db", default=os.getenv("POSITION_LEDGER_PATH", ""))
    parser.add_argument("--md", action="store_true", help="输出 Markdown 报告文件")
    parser.add_argument("--json", action="store_true", help="输出 JSON 报告文件")
    parser.add_argument("--out-dir", default=str(_REPORT_DIR), help="报告输出目录")
    args = parser.parse_args(argv)

    ledger = PositionLedger(args.db or None)
    report = build_report(ledger, args.since_hours)
    md = render_markdown(report)

    if args.md or args.json:
        out_dir = Path(args.out_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d")
        if args.md:
            (out_dir / f"ledger_attribution_{stamp}.md").write_text(md, encoding="utf-8")
            (out_dir / "latest.md").write_text(md, encoding="utf-8")
        if args.json:
            payload = json.dumps(report, ensure_ascii=False, indent=2)
            (out_dir / f"ledger_attribution_{stamp}.json").write_text(payload, encoding="utf-8")
            (out_dir / "latest.json").write_text(payload, encoding="utf-8")
    print(md)
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
