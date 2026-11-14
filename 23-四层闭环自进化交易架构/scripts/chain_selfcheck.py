#!/usr/bin/env python3
"""23 自进化全链路自检（M3）。

链路：signal → 特征 → 方向 → 风控 → 定容 → 22 下单 → 成交 → SL/TP → 结算 → 反思
逐段按日志/审计证据判定：任一段缺证据即 FAIL（退出码 1）。

用法:
  python 23-四层闭环自进化交易架构/scripts/chain_selfcheck.py
  python ... --log /home/luke/logs/yijing/trader.log --since-hours 24
  python ... --audit 22-执行引擎中心/audit/gateway.jsonl --out /tmp/23-chain.md
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_LOG_CANDIDATES = [
    REPO_ROOT / "11-易经推理系统" / "logs" / "trader.log",
    REPO_ROOT / "logs" / "yijing" / "trader.log",
    Path("/home/luke/logs/yijing/trader.log"),
]
DEFAULT_AUDIT = REPO_ROOT / "22-执行引擎中心" / "audit" / "gateway.jsonl"


@dataclass
class Stage:
    key: str
    name: str
    patterns: list[str]
    required: bool = True
    matches: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return bool(self.matches) if self.required else True


STAGES = [
    Stage("signal", "信号产出", [r"\[P2-S4b\].*(evolution_auto|BUILD|建仓)"]),
    Stage("feature", "特征/因子", [r"\[P2-S4b\]\[ATTR\].*bcrm=.*u_open="]),
    Stage("direction", "方向", [r"\[P2-S4b\]\[ATTR\].*signal_dir=(LONG|SHORT)"]),
    Stage("risk", "风控", [r"\[CONSTRAINT\]|\[P2-S4b\].*(拦截|拒绝|REJECT)"]),
    Stage("sizing", "定容", [r"\[P2-S4b\]\[ATTR\].*notional="]),
    Stage("fill", "成交", [r"建仓成功|\[P2-S4b\].*ord_id"]),
    Stage("sltp", "SL/TP", [r"SL/TP (兜底)?已设置|SL/TP 设置"]),
    Stage("settlement", "结算", [r"on_trade_settled|\[TradeSettlement\]|结算"]),
    Stage("reflection", "反思", [r"反思|reflection|\[L4-REFLECT\]|exit_engine"]),
]


def _pick_log(explicit: str | None) -> Path | None:
    if explicit:
        p = Path(explicit)
        return p if p.exists() else None
    for p in DEFAULT_LOG_CANDIDATES:
        if p.exists():
            return p
    return None


def _read_lines(path: Path, since_hours: float) -> list[str]:
    cutoff = datetime.now(timezone.utc) - timedelta(hours=since_hours)
    lines: list[str] = []
    with open(path, "r", encoding="utf-8", errors="ignore") as f:
        for line in f:
            ts = _parse_ts(line)
            if ts is not None and ts < cutoff:
                continue
            lines.append(line.rstrip("\n"))
    return lines


_TS_RE = re.compile(r"(\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}:\d{2})")


def _parse_ts(line: str) -> datetime | None:
    m = _TS_RE.search(line)
    if not m:
        return None
    try:
        dt = datetime.fromisoformat(m.group(1).replace("T", " "))
        return dt.replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def _scan_stages(lines: list[str], symbol: str | None) -> None:
    for st in STAGES:
        st.matches = []
        for pat in st.patterns:
            rx = re.compile(pat)
            for line in lines:
                if symbol and symbol.upper() not in line.upper():
                    continue
                if rx.search(line):
                    st.matches.append(line)
                    break


def _read_audit(path: Path, since_hours: float, symbol: str | None) -> list[dict]:
    if not path.exists():
        return []
    cutoff = datetime.now(timezone.utc) - timedelta(hours=since_hours)
    out: list[dict] = []
    with open(path, "r", encoding="utf-8", errors="ignore") as f:
        for line in f:
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            if rec.get("source") != "23-evolution":
                continue
            if symbol and symbol.upper() not in str(rec.get("symbol", "")).upper():
                continue
            ts = _parse_ts(str(rec.get("ts", "")))
            if ts is not None and ts < cutoff:
                continue
            out.append(rec)
    return out


def _render(
    log_path: Path | None,
    audit_path: Path,
    stages: list[Stage],
    audit: list[dict],
    since_hours: float,
    symbol: str | None,
) -> str:
    executed = [r for r in audit if r.get("executed")]
    rejected = [r for r in audit if not r.get("executed")]
    all_ok = all(s.ok for s in stages) and bool(executed)

    lines = [
        "# 23 自进化全链路自检报告",
        "",
        f"- 生成时间: {datetime.now(timezone.utc).isoformat()}",
        f"- 日志: {log_path if log_path else 'NOT FOUND'}",
        f"- 网关审计: {audit_path}",
        f"- 时间窗口: 最近 {since_hours:g}h" + (f" · 标的过滤={symbol}" if symbol else ""),
        f"- 结论: **{'PASS' if all_ok else 'FAIL'}**",
        "",
        "## 逐段证据",
        "",
        "| 段 | 状态 | 命中 | 样例 |",
        "|---|---|---|---|",
    ]
    for s in stages:
        sample = (s.matches[0][:160] + "…") if s.matches else "—"
        sample = sample.replace("|", "\\|")
        lines.append(f"| {s.name} | {'PASS' if s.ok else 'FAIL'} | {len(s.matches)} | {sample} |")

    lines += [
        "",
        "## 22 网关执行证据（source=23-evolution）",
        "",
        f"- 决策总数: {len(audit)} · 成交: {len(executed)} · 未执行: {len(rejected)}",
    ]
    if audit:
        lines += [
            "",
            "| decision_id | symbol | dir | action | executed | reason_code | notional |",
            "|---|---|---|---|---|---|---|",
        ]
        for r in audit[-20:]:
            lines.append(
                "| {did} | {sym} | {d} | {a} | {e} | {rc} | {n} |".format(
                    did=str(r.get("decision_id", "-"))[:42],
                    sym=r.get("symbol", "-"),
                    d=r.get("direction", "-"),
                    a=r.get("action", "-"),
                    e="Y" if r.get("executed") else "N",
                    rc=r.get("reason_code", "-"),
                    n=r.get("notional_usdt", "-"),
                )
            )
    else:
        lines.append("- 缺失：网关审计中未发现 source=23-evolution 记录（FAIL）")

    lines += [
        "",
        "## 判定规则",
        "",
        "- 任一段无证据 → 该段 FAIL；",
        "- 网关审计无 executed=true 的 23 决策 → 整链 FAIL；",
        "- 本报告由 chain_selfcheck.py 生成，禁止人工改写结论。",
    ]
    return "\n".join(lines) + "\n"


def main() -> int:
    ap = argparse.ArgumentParser(description="23 自进化全链路自检")
    ap.add_argument("--log", default=None, help="trader.log 路径")
    ap.add_argument("--audit", default=str(DEFAULT_AUDIT), help="22 网关审计 JSONL 路径")
    ap.add_argument("--out", default=None, help="报告输出路径")
    ap.add_argument("--since-hours", type=float, default=24.0)
    ap.add_argument("--symbol", default=None, help="仅检查指定标的，如 BTC")
    args = ap.parse_args()

    log_path = _pick_log(args.log)
    audit_path = Path(args.audit)
    lines = _read_lines(log_path, args.since_hours) if log_path else []
    _scan_stages(lines, args.symbol)
    # 下单证据以网关审计为准，日志侧补一条 order 段
    audit = _read_audit(audit_path, args.since_hours, args.symbol)
    order = Stage("order", "22 下单", [])
    order.matches = [json.dumps(r, ensure_ascii=False) for r in audit if r.get("executed")]
    stages = STAGES[:5] + [order] + STAGES[5:]

    report = _render(log_path, audit_path, stages, audit, args.since_hours, args.symbol)
    out = (
        Path(args.out)
        if args.out
        else (
            REPO_ROOT
            / ".trae"
            / "documents"
            / "review-reports"
            / f"{datetime.now(timezone.utc).strftime('%Y-%m-%d')}-23-chain.md"
        )
    )
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(report, encoding="utf-8")
    print(report)
    print(f"\n[report] {out}")

    all_ok = all(s.ok for s in stages) and any(r.get("executed") for r in audit)
    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())
