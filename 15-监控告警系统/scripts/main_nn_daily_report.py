#!/usr/bin/env python3
"""main-nn 每日复盘与观察期 SLO / 误报统计（TD §14.7 / §14.9 P3）。

按 Asia/Shanghai 自然日聚合 main-nn 链路证据，输出：
  ① SLO：链路完整率(M6→M13)、WAIT 可归因率、wait_vs_broken、
     决策→成交 join、SL/TP 附带率、单出口违约；
  ② 链路：M0–M14 事件计数、缺失阶段、WAIT 原因 Top；
  ③ 告警：Prometheus `query_range` 统计当日 MainNN* firing 段数（不可达则 fail-open 跳过）；
  ④ 误报台账：`fp_ledger.json`，支持 `--mark-fp/--note/--list-fp`。

只读业务产物（chain_events / decisions / outbox / fills），不做任何修正。
口径尽量与 `exporter/business_metrics_exporter.py::main_nn_metrics()` 对齐，
避免看板与日报各说各话。

用法：
  python3 scripts/main_nn_daily_report.py                    # 今日报告
  python3 scripts/main_nn_daily_report.py --date 2026-11-26
  python3 scripts/main_nn_daily_report.py --mark-fp MainNNConstraintDegraded --note "样本不足"
  python3 scripts/main_nn_daily_report.py --list-fp
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta, timezone
from datetime import time as dtime
from pathlib import Path
from typing import Any, Dict, Iterator, List

BASE_DIR = Path(__file__).resolve().parent.parent
DEFAULT_REPO_ROOT = BASE_DIR.parent
DEFAULT_OUT_DIR = BASE_DIR / "runtime" / "reports"
DEFAULT_PROMETHEUS = os.getenv("MAIN_NN_PROMETHEUS", "http://127.0.0.1:9090")
CST = timezone(timedelta(hours=8))
SOURCE = "main-nn"
CHAIN_DIRS = (
    "50-NN主矛盾评估器/runtime",
    "22-执行引擎中心/runtime",
    "43-战略承接推演层/runtime",
    "42-神经网络交易协调层/runtime",
    "40-周期神经网络系统/runtime",
)
CHAIN_REQUIRED_STAGE = "M6"
CHAIN_COMPLETE_STAGES = ("M12", "M13")
ALERT_QUERY = 'ALERTS{alertstate="firing",alertname=~"MainNN.+"}'
ALERT_STEP_SECONDS = 300
LIMITS = {
    "chain_completion": 0.99,
    "wait_attributable": 0.95,
    "wait_vs_broken": 0.05,
    "decision_fill_join": 0.95,
    "sltp_attach": 1.0,
    "single_exit_violation": 0,
}


# ------------------------------ 基础工具 ------------------------------
def _iso_ts(value: Any) -> float:
    if not value:
        return 0.0
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).timestamp()
    except (TypeError, ValueError):
        return 0.0


def _iso(ts: float) -> str:
    return datetime.fromtimestamp(ts, timezone.utc).isoformat().replace("+00:00", "Z")


def _rec_ts(rec: Dict[str, Any]) -> float:
    for key in ("ts", "timestamp", "generated_at"):
        ts = _iso_ts(rec.get(key))
        if ts:
            return ts
    return 0.0


def _iter_jsonl(path: Path) -> Iterator[Dict[str, Any]]:
    try:
        handle = path.open("r", encoding="utf-8", errors="ignore")
    except OSError:
        return
    with handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except ValueError:
                continue
            if isinstance(rec, dict):
                yield rec


def _iter_jsonl_window(
    path: Path,
    start_ts: float,
    end_ts: float,
    initial_bytes: int = 4 << 20,
    max_bytes: int = 64 << 20,
) -> Iterator[Dict[str, Any]]:
    """按时间窗读取 JSONL；大文件从尾部按块扩张，避免整份解析 80MB+ 的 decisions。"""
    try:
        size = path.stat().st_size
    except OSError:
        return
    if size <= initial_bytes:
        for rec in _iter_jsonl(path):
            if start_ts <= _rec_ts(rec) < end_ts:
                yield rec
        return

    block = initial_bytes
    while True:
        block = min(block, size)
        try:
            with path.open("rb") as handle:
                handle.seek(size - block)
                chunk = handle.read().decode("utf-8", errors="ignore")
        except OSError:
            return
        lines = chunk.splitlines()
        if block < size:
            lines = lines[1:]  # 丢弃被块边界截断的首行
        rows: List[Dict[str, Any]] = []
        for line in lines:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except ValueError:
                continue
            if isinstance(rec, dict):
                rows.append(rec)
        reached_start = block >= size or any(_rec_ts(r) < start_ts for r in rows)
        if reached_start or block >= max_bytes:
            for rec in rows:
                if start_ts <= _rec_ts(rec) < end_ts:
                    yield rec
            return
        block *= 2


def _ratio(num: float, den: float) -> float | None:
    return round(num / den, 4) if den else None


def _read_json(path: Path) -> Dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _http_json(url: str, timeout: float = 6.0) -> Dict[str, Any]:
    with urllib.request.urlopen(url, timeout=timeout) as resp:  # noqa: S310 (内网只读 GET)
        return json.loads(resp.read().decode("utf-8"))


# ------------------------------ 链路证据 ------------------------------
def collect_chain(repo: Path, start_ts: float, end_ts: float) -> Dict[str, Any]:
    stage_counts: Dict[tuple[str, str], int] = {}
    chains: Dict[str, set[str]] = {}
    wait_reasons: Dict[str, int] = {}
    wait_total = wait_broken = events = 0

    for rel in CHAIN_DIRS:
        folder = repo / rel
        if not folder.is_dir():
            continue
        for path in sorted(folder.glob("chain_events-*.jsonl")):
            try:
                if path.stat().st_mtime < start_ts:
                    continue  # 窗口开始前就已停写，不可能含窗口内记录
            except OSError:
                continue
            for rec in _iter_jsonl_window(path, start_ts, end_ts):
                if str(rec.get("source") or "") != SOURCE:
                    continue
                events += 1
                stage = str(rec.get("stage") or "?")
                status = str(rec.get("status") or "?")
                stage_counts[(stage, status)] = stage_counts.get((stage, status), 0) + 1

                cid = str(
                    rec.get("chain_id") or rec.get("trace_id") or rec.get("decision_id") or ""
                )
                if cid:
                    chains.setdefault(cid, set()).add(stage)

                if status == "skip":
                    wait_total += 1
                    data = rec.get("data") if isinstance(rec.get("data"), dict) else {}
                    reason = str(
                        rec.get("reason_category") or data.get("reason_category") or ""
                    ).strip()
                    if reason:
                        wait_reasons[reason] = wait_reasons.get(reason, 0) + 1
                    else:
                        wait_broken += 1

    signal_chains = [stages for stages in chains.values() if CHAIN_REQUIRED_STAGE in stages]
    complete = sum(1 for stages in signal_chains if set(CHAIN_COMPLETE_STAGES) <= stages)
    missing = {
        stage: sum(1 for stages in signal_chains if stage not in stages)
        for stage in ("M7", "M11", "M13")
    }
    return {
        "events": events,
        "chains": len(chains),
        "signal_chains": len(signal_chains),
        "complete_chains": complete,
        "completion_ratio": _ratio(complete, len(signal_chains)),
        "missing_stage": missing,
        "stage_status": [
            {"stage": stage, "status": status, "count": n}
            for (stage, status), n in sorted(stage_counts.items())
        ],
        "wait_total": wait_total,
        "wait_broken": wait_broken,
        "wait_attributable_ratio": (
            None if not wait_total else round(1 - wait_broken / wait_total, 4)
        ),
        "wait_vs_broken_ratio": _ratio(wait_broken, wait_total),
        "wait_reasons": dict(sorted(wait_reasons.items(), key=lambda kv: -kv[1])),
    }


# ------------------------------ 执行证据 ------------------------------
def collect_execution(repo: Path, start_ts: float, end_ts: float) -> Dict[str, Any]:
    live_ids: set[str] = set()
    dec_path = repo / "50-NN主矛盾评估器/runtime/decisions.jsonl"
    for rec in _iter_jsonl_window(dec_path, start_ts, end_ts):
        payload = rec.get("payload") if isinstance(rec.get("payload"), dict) else {}
        mode = str(rec.get("mode") or payload.get("mode") or "")
        if mode == "live" and rec.get("decision_id"):
            live_ids.add(str(rec["decision_id"]))

    placed = attached = 0
    filled_ids: set[str] = set()
    fills_path = repo / "22-执行引擎中心/audit/x1_live_fills.jsonl"
    for rec in _iter_jsonl_window(fills_path, start_ts, end_ts):
        if not rec.get("order_placed"):
            continue
        placed += 1
        if rec.get("decision_id"):
            filled_ids.add(str(rec["decision_id"]))
        request = rec.get("request") if isinstance(rec.get("request"), dict) else {}
        try:
            if float(request.get("sl_pct") or 0) > 0 and float(request.get("tp_pct") or 0) > 0:
                attached += 1
        except (TypeError, ValueError):
            continue

    live_outbox = violations = 0
    outbox_path = repo / "50-NN主矛盾评估器/runtime/live/outbox.jsonl"
    for rec in _iter_jsonl_window(outbox_path, start_ts, end_ts):
        if str(rec.get("mode") or "") != "live":
            continue
        live_outbox += 1
        execution = rec.get("execution") if isinstance(rec.get("execution"), dict) else {}
        outcome = str(execution.get("outcome") or rec.get("execution_rights") or "")
        if outcome != "live:50-bypass" or not rec.get("mandate_id"):
            violations += 1

    return {
        "live_decisions": len(live_ids),
        "placed_orders": placed,
        "sltp_attached": attached,
        "filled_with_decision_id": len(filled_ids),
        "join_matched": len(filled_ids & live_ids),
        "decision_fill_join_ratio": _ratio(len(filled_ids & live_ids), len(filled_ids)),
        "sltp_attach_ratio": _ratio(attached, placed),
        "live_outbox": live_outbox,
        "single_exit_violations": violations,
    }


# ------------------------------ 告警统计 ------------------------------
def _count_episodes(timestamps: List[float], step: float = ALERT_STEP_SECONDS) -> int:
    """按采样间隔把 firing 采样点切成连续段；断档超过 1.5 个 step 视为新一段。"""
    ordered = sorted(timestamps)
    if not ordered:
        return 0
    episodes = 1
    for prev, cur in zip(ordered, ordered[1:], strict=False):
        if cur - prev > step * 1.5:
            episodes += 1
    return episodes


def collect_alerts(prometheus: str | None, start_ts: float, end_ts: float) -> Dict[str, Any]:
    if not prometheus:
        return {"available": False, "error": "disabled", "alerts": {}, "firing_episodes": 0}
    params = urllib.parse.urlencode(
        {
            "query": ALERT_QUERY,
            "start": int(start_ts),
            "end": int(end_ts),
            "step": ALERT_STEP_SECONDS,
        }
    )
    url = f"{prometheus.rstrip('/')}/api/v1/query_range?{params}"
    try:
        data = _http_json(url)
    except Exception as exc:  # fail-open：统计失败不影响 SLO 报告
        return {
            "available": False,
            "error": f"{type(exc).__name__}: {exc}",
            "alerts": {},
            "firing_episodes": 0,
        }
    if data.get("status") != "success":
        return {
            "available": False,
            "error": str(data.get("error") or "prometheus query failed"),
            "alerts": {},
            "firing_episodes": 0,
        }

    alerts: Dict[str, Dict[str, Any]] = {}
    for series in (data.get("data") or {}).get("result") or []:
        metric = series.get("metric") if isinstance(series.get("metric"), dict) else {}
        name = str(metric.get("alertname") or "?")
        stamps = [float(v[0]) for v in series.get("values") or [] if isinstance(v, list) and v]
        slot = alerts.setdefault(
            name,
            {"episodes": 0, "samples": 0, "severity": str(metric.get("severity") or "")},
        )
        slot["episodes"] += _count_episodes(stamps)
        slot["samples"] += len(stamps)
        if not slot["severity"] and metric.get("severity"):
            slot["severity"] = str(metric["severity"])
    return {
        "available": True,
        "error": "",
        "alerts": dict(sorted(alerts.items())),
        "firing_episodes": sum(a["episodes"] for a in alerts.values()),
    }


# ------------------------------ 误报台账 ------------------------------
def _ledger_file(out_dir: Path) -> Path:
    return out_dir / "fp_ledger.json"


def load_ledger(path: Path) -> Dict[str, Any]:
    data = _read_json(path)
    entries = data.get("entries") if isinstance(data.get("entries"), list) else []
    return {
        "version": 1,
        "updated_at": str(data.get("updated_at") or ""),
        "entries": [e for e in entries if isinstance(e, dict)],
    }


def save_ledger(path: Path, data: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def mark_fp(path: Path, alert: str, note: str, day: str) -> Dict[str, Any]:
    """登记一条误报；同一 (alert, date) 重复登记只更新备注，避免同一日重复计数。"""
    data = load_ledger(path)
    now = _iso(datetime.now(timezone.utc).timestamp())
    entries = [
        e
        for e in data["entries"]
        if not (str(e.get("alert")) == alert and str(e.get("date")) == day)
    ]
    row = {"alert": alert, "date": day, "note": note or "", "marked_at": now}
    entries.append(row)
    data["entries"] = sorted(entries, key=lambda e: (str(e.get("date")), str(e.get("alert"))))
    data["updated_at"] = now
    save_ledger(path, data)
    return row


def render_fp_list(data: Dict[str, Any]) -> str:
    entries = data.get("entries") or []
    lines = [f"误报台账：{len(entries)} 条（updated_at={data.get('updated_at') or '-'}）"]
    if not entries:
        lines.append("（空）")
    for row in entries:
        note = f" — {row['note']}" if row.get("note") else ""
        lines.append(f"- {row.get('date')}  {row.get('alert')}{note}")
    return "\n".join(lines)


def _fp_summary(ledger: Dict[str, Any], day: str, firing_episodes: int, available: bool):
    day_entries = [e for e in ledger.get("entries", []) if str(e.get("date")) == day]
    rate = None
    if available and firing_episodes > 0:
        rate = round(len(day_entries) / firing_episodes, 4)
    return {
        "marked": len(day_entries),
        "rate": rate,
        "within_slo": None if rate is None else rate < 0.05,
        "entries": day_entries,
    }


# ------------------------------ SLO 汇总 ------------------------------
def evaluate_slo(chain: Dict[str, Any], execution: Dict[str, Any]) -> List[Dict[str, Any]]:
    def entry(key: str, label: str, target: str, value, ok):
        return {"key": key, "label": label, "target": target, "value": value, "ok": ok}

    completion = chain["completion_ratio"]
    attributable = chain["wait_attributable_ratio"]
    wait_broken = chain["wait_vs_broken_ratio"]
    join = execution["decision_fill_join_ratio"]
    attach = execution["sltp_attach_ratio"]
    violations = execution["single_exit_violations"]
    return [
        entry(
            "chain_completion",
            "链路完整率(M6→M13)",
            ">= 99%",
            completion,
            None if completion is None else completion >= LIMITS["chain_completion"],
        ),
        entry(
            "wait_attributable",
            "WAIT 可归因率",
            ">= 95%",
            attributable,
            None if attributable is None else attributable >= LIMITS["wait_attributable"],
        ),
        entry(
            "wait_vs_broken",
            "WAIT 断链占比",
            "<= 5%",
            wait_broken,
            None if wait_broken is None else wait_broken <= LIMITS["wait_vs_broken"],
        ),
        entry(
            "decision_fill_join",
            "决策→成交可回溯率",
            ">= 95%",
            join,
            None if join is None else join >= LIMITS["decision_fill_join"],
        ),
        entry(
            "sltp_attach",
            "下单 SL/TP 附带率",
            "= 100%",
            attach,
            None if attach is None else attach >= LIMITS["sltp_attach"],
        ),
        entry(
            "single_exit_violation",
            "单出口违约",
            "= 0",
            violations,
            violations <= LIMITS["single_exit_violation"],
        ),
    ]


# ------------------------------ 报告组装 ------------------------------
def _parse_day(value: str | None) -> date:
    if not value:
        return datetime.now(CST).date()
    return datetime.strptime(value, "%Y-%m-%d").date()


def _day_window(day: date) -> tuple[float, float]:
    start = datetime.combine(day, dtime.min, tzinfo=CST)
    return start.timestamp(), (start + timedelta(days=1)).timestamp()


def build_report(
    repo: Path,
    day: date,
    prometheus: str | None = DEFAULT_PROMETHEUS,
    ledger_path: Path | None = None,
) -> Dict[str, Any]:
    start_ts, end_ts = _day_window(day)
    chain = collect_chain(repo, start_ts, end_ts)
    execution = collect_execution(repo, start_ts, end_ts)
    alerts = collect_alerts(prometheus, start_ts, end_ts)
    slo = evaluate_slo(chain, execution)
    ledger = load_ledger(ledger_path) if ledger_path else {"version": 1, "entries": []}
    fp = _fp_summary(ledger, day.isoformat(), alerts["firing_episodes"], alerts["available"])

    unresolved = [s["label"] for s in slo if s["ok"] is False]
    return {
        "date": day.isoformat(),
        "generated_at": _iso(datetime.now(timezone.utc).timestamp()),
        "window": {"start": _iso(start_ts), "end": _iso(end_ts), "timezone": "Asia/Shanghai"},
        "slo": slo,
        "chain": chain,
        "execution": execution,
        "alerts": alerts,
        "false_positive": fp,
        "ok": not unresolved,
        "failed_slo": unresolved,
    }


def _fmt_ratio(value, dash: str = "N/A") -> str:
    return dash if value is None else f"{value * 100:.2f}%"


def render_markdown(report: Dict[str, Any]) -> str:
    chain = report["chain"]
    execution = report["execution"]
    alerts = report["alerts"]
    fp = report["false_positive"]
    lines = [
        f"# main-nn 每日复盘（{report['date']}）",
        "",
        f"- 窗口：{report['window']['start']} → {report['window']['end']}（Asia/Shanghai）",
        f"- 生成时间：{report['generated_at']}",
        f"- 结论：{'✅ SLO 达标' if report['ok'] else '⚠️ SLO 未达标：' + '、'.join(report['failed_slo'])}",
        "",
        "## SLO",
        "",
        "| SLO | 目标 | 实测 | 结论 |",
        "|---|---|---|---|",
    ]
    for item in report["slo"]:
        value = item["value"]
        shown = f"{value}" if item["key"] == "single_exit_violation" else _fmt_ratio(value)
        verdict = "N/A" if item["ok"] is None else ("✅" if item["ok"] else "❌")
        lines.append(f"| {item['label']} | {item['target']} | {shown} | {verdict} |")

    lines += [
        "",
        "## 链路",
        "",
        f"- main-nn 事件 {chain['events']} 条，链路 {chain['chains']} 条（含 M6 的 {chain['signal_chains']} 条）",
        f"- 完整链（M12+M13）：{chain['complete_chains']} / {chain['signal_chains']}"
        f"（{_fmt_ratio(chain['completion_ratio'])}）",
        "- 缺失阶段：" + "，".join(f"{k}={v}" for k, v in chain["missing_stage"].items()),
        f"- WAIT(skip) 事件 {chain['wait_total']} 条，不可归因 {chain['wait_broken']} 条",
    ]
    if chain["wait_reasons"]:
        top = list(chain["wait_reasons"].items())[:5]
        lines.append("- WAIT 原因 Top：" + "，".join(f"{k}={v}" for k, v in top))

    lines += [
        "",
        "## 执行",
        "",
        f"- live 决策 {execution['live_decisions']} 条，live 出箱 {execution['live_outbox']} 条",
        f"- 下单 {execution['placed_orders']} 笔，SL/TP 附带 {execution['sltp_attached']} 笔"
        f"（{_fmt_ratio(execution['sltp_attach_ratio'])}）",
        f"- 可按 decision_id 回溯：{execution['join_matched']} / "
        f"{execution['filled_with_decision_id']}（{_fmt_ratio(execution['decision_fill_join_ratio'])}）",
        f"- 单出口违约：{execution['single_exit_violations']} 条",
        "",
        "## 告警（Prometheus query_range）",
        "",
    ]
    if not alerts["available"]:
        lines.append(f"- 跳过统计（fail-open）：{alerts['error']}")
    elif not alerts["alerts"]:
        lines.append("- 当日无 MainNN* firing")
    else:
        lines += ["| 告警 | 级别 | 触发段数 | 采样点 |", "|---|---|---:|---:|"]
        for name, item in alerts["alerts"].items():
            lines.append(
                f"| {name} | {item.get('severity') or '-'} | {item['episodes']} | {item['samples']} |"
            )
        lines.append(f"\n- firing 合计：{alerts['firing_episodes']} 段")

    lines += [
        "",
        "## 误报台账（当日）",
        "",
        f"- 已登记误报：{fp['marked']} 条，误报率：{_fmt_ratio(fp['rate'], 'N/A（无 firing 或告警不可用）')}"
        f"，观察期 SLO <5%："
        + ("N/A" if fp["within_slo"] is None else ("✅" if fp["within_slo"] else "❌")),
    ]
    if fp["entries"]:
        lines += ["", "| 告警 | 备注 | 标记时间 |", "|---|---|---|"]
        for row in fp["entries"]:
            lines.append(
                f"| {row.get('alert')} | {row.get('note') or '-'} | {row.get('marked_at') or '-'} |"
            )

    lines += [
        "",
        "## 复现与登记",
        "",
        "```bash",
        f"python3 15-监控告警系统/scripts/main_nn_daily_report.py --date {report['date']}",
        "python3 15-监控告警系统/scripts/main_nn_daily_report.py --mark-fp <AlertName> --note '原因'",
        "python3 15-监控告警系统/scripts/main_nn_daily_report.py --list-fp",
        "```",
    ]
    return "\n".join(lines) + "\n"


def main(argv: List[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="main-nn 每日复盘 / SLO / 误报统计")
    parser.add_argument("--date", help="统计日 YYYY-MM-DD（默认今天，Asia/Shanghai）")
    parser.add_argument("--repo-root", default=str(DEFAULT_REPO_ROOT))
    parser.add_argument("--prometheus", default=DEFAULT_PROMETHEUS, help="为空则跳过告警统计")
    parser.add_argument("--out", default=str(DEFAULT_OUT_DIR), help="报告输出目录")
    parser.add_argument("--ledger", default="", help="误报台账路径（默认 <out>/fp_ledger.json）")
    parser.add_argument("--mark-fp", metavar="ALERT", help="登记一条误报")
    parser.add_argument("--note", default="", help="配合 --mark-fp 的备注")
    parser.add_argument("--list-fp", action="store_true", help="列出台账后退出")
    args = parser.parse_args(argv)

    day = _parse_day(args.date)
    out_dir = Path(args.out)
    ledger_path = Path(args.ledger) if args.ledger else _ledger_file(out_dir)

    if args.list_fp:
        print(render_fp_list(load_ledger(ledger_path)))
        return 0
    if args.mark_fp:
        row = mark_fp(ledger_path, args.mark_fp, args.note, day.isoformat())
        print(f"已登记误报：{row['alert']} @ {row['date']} — {row['note'] or '(无备注)'}")
        return 0

    report = build_report(
        Path(args.repo_root),
        day,
        prometheus=args.prometheus or None,
        ledger_path=ledger_path,
    )
    markdown = render_markdown(report)
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = day.strftime("%Y%m%d")
    (out_dir / f"{stamp}-main-nn.md").write_text(markdown, encoding="utf-8")
    (out_dir / f"{stamp}-main-nn.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    (out_dir / "latest-main-nn.md").write_text(markdown, encoding="utf-8")
    print(markdown)
    return 0


if __name__ == "__main__":
    sys.exit(main())
