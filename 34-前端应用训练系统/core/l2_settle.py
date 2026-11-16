"""L2 settle → 台账/案例回写 L0 + 周报（SPEC-56 §2.5 / IF-5 / G-L2-8 / ADR-06）。

职责边界
--------
- **台账迁移**：只允许 `regression_passed → settled`，补齐 `evidence.regression`、`settled`
  四分流、`run_ids` 与 `history` 末条；其余状态一律 fail-closed（不可跳步）。
- **案例回写 L0**：`settled.case=done` 时向 L0 案例库（`l1_case_store.jsonl`，与
  `l0_foundation._CASE_STORE` 同域）追加 `case_type=l2_repair` 记录，按 `task_id` 幂等。
- **周报**：只报事件窗口内的可审计口径——修复率 = `settled/(settled+abandoned)`、
  回归通过率 = `passed/带回归证据`、优化收益 = 同测试集 `before/after/delta`。
  样本不足时指标为 `null`（不按 0 记），优化收益不自动判优劣（方向由指标语义决定）。
- **不造数**：没有回归证据、没有 run_ids、状态不对，直接拒绝，不写「先落地再说」的结算。
"""

from __future__ import annotations

import argparse
import copy
import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

try:  # 包内导入（tests / 3.1 侧）
    from core.l2_repair_ledger import (
        DEFAULT_LEDGER_PATH,
        load_ledger,
        validate_entry,
    )
except ImportError:  # pragma: no cover - 直连脚本执行（python3 core/l2_settle.py）
    from l2_repair_ledger import (  # type: ignore[no-redef]
        DEFAULT_LEDGER_PATH,
        load_ledger,
        validate_entry,
    )

REPORT_SCHEMA_VERSION = "1.0"
CASE_SCHEMA_VERSION = "v2"
CASE_TYPE = "l2_repair"

CASE_STORE_FILENAME = "l1_case_store.jsonl"
DEFAULT_CASE_STORE_PATH = Path(__file__).resolve().parents[1] / CASE_STORE_FILENAME

SPLIT_KEYS = ("case", "cognition", "process", "doc")
SPLIT_VALUES = ("done", "skipped")
RUNNERS = ("pytest", "ci", "gate45")
TERMINAL_STATES = ("settled", "abandoned")


class SettleError(ValueError):
    """不满足 settle 前置条件（拒绝回写）"""


# ============================================================
# 基础工具
# ============================================================


def _iso(value: Optional[datetime] = None) -> str:
    stamp = value or datetime.now(timezone.utc)
    if stamp.tzinfo is None:
        stamp = stamp.replace(tzinfo=timezone.utc)
    return stamp.isoformat()


def _parse_ts(value: Any) -> datetime:
    """解析 ISO 时间（支持 datetime；无时区按 UTC），失败抛 SettleError。"""
    if isinstance(value, datetime):
        stamp = value
    else:
        text = str(value or "").strip()
        if not text:
            raise SettleError("缺少时间戳（ISO 8601）")
        try:
            stamp = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError as exc:
            raise SettleError(f"时间戳无法解析（应为 ISO 8601）: {value!r}") from exc
    if stamp.tzinfo is None:
        stamp = stamp.replace(tzinfo=timezone.utc)
    return stamp


def _safe_parse(value: Any) -> Optional[datetime]:
    try:
        return _parse_ts(value)
    except SettleError:
        return None


def _in_window(value: Any, since: datetime, until: datetime) -> bool:
    stamp = _safe_parse(value)
    return stamp is not None and since <= stamp < until


# ============================================================
# settle 前置校验
# ============================================================


def _validate_regression(regression: Any) -> None:
    """G-L2-8：回归必须可复跑且通过，不接受「人工确认」。"""
    if not isinstance(regression, dict):
        raise SettleError("缺少 evidence.regression（settled 必须带回归证据）")

    runner = regression.get("runner")
    if runner not in RUNNERS:
        raise SettleError(f"回归 runner 非法: {runner!r}（允许 {RUNNERS}，manual 不可用）")

    if len(str(regression.get("cmd") or "").strip()) < 3:
        raise SettleError("回归缺少可复跑命令 cmd")

    exit_code = regression.get("exit_code")
    if type(exit_code) is not int:
        raise SettleError(f"回归 exit_code 必须是整数: {exit_code!r}")
    if exit_code != 0:
        raise SettleError(f"回归未通过（exit_code={exit_code}），只能标 fixed/重开，不得 settled")

    if regression.get("passed") is not True:
        raise SettleError("回归未通过（passed 必须为 true），不得 settled")

    if _safe_parse(regression.get("ts")) is None:
        raise SettleError("回归缺少合法时间戳 ts（ISO 8601）")

    if len(str(regression.get("log_uri") or "").strip()) < 3:
        raise SettleError("回归缺少日志 log_uri（必须可追溯）")


def _validate_run_ids(run_ids: Any) -> List[str]:
    if not isinstance(run_ids, (list, tuple)) or not run_ids:
        raise SettleError("run_ids 必须非空（关联 L2Envelope）")
    out = [str(item) for item in run_ids]
    for item in out:
        if len(item) < 3:
            raise SettleError(f"run_ids 元素过短（至少 3 字）: {item!r}")
    return out


def _normalize_splits(splits: Optional[Dict[str, Any]]) -> Dict[str, str]:
    """ADR-06 四分流：case/cognition/process/doc，各 done|skipped（缺省 skipped）。"""
    if splits is None:
        return dict.fromkeys(SPLIT_KEYS, "skipped")
    if not isinstance(splits, dict):
        raise SettleError("settled 四分流必须是对象 {case,cognition,process,doc}")
    unknown = sorted(set(splits) - set(SPLIT_KEYS))
    if unknown:
        raise SettleError(f"settled 含未知分流键: {unknown}（只允许 {SPLIT_KEYS}）")
    out = {}
    for key in SPLIT_KEYS:
        value = splits.get(key, "skipped")
        if value not in SPLIT_VALUES:
            raise SettleError(f"settled.{key} 非法: {value!r}（只允许 {SPLIT_VALUES}）")
        out[key] = value
    return out


# ============================================================
# 案例回写 L0
# ============================================================


def build_case(entry: Dict[str, Any], settled_at: str) -> Dict[str, Any]:
    """由 settled 台账条目生成 L0 案例记录（案例库 v2 结构 + l2_repair 类型）。"""
    return {
        "ts": settled_at,
        "schema_version": CASE_SCHEMA_VERSION,
        "case_type": CASE_TYPE,
        "task_id": entry["task_id"],
        "payload": {
            "kind": entry.get("kind"),
            "trigger": entry.get("trigger"),
            "symptom": entry.get("symptom"),
            "root_cause": entry.get("root_cause"),
            "change_ref": entry.get("change_ref"),
            "regression": (entry.get("evidence") or {}).get("regression"),
            "optimization": (entry.get("evidence") or {}).get("optimization"),
            "metrics": entry.get("metrics") or [],
            "run_ids": entry.get("run_ids") or [],
            "settled": entry.get("settled"),
            "settled_at": settled_at,
        },
    }


def _case_exists(path: Path, task_id: str) -> bool:
    if not path.exists():
        return False
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if row.get("case_type") == CASE_TYPE and row.get("task_id") == task_id:
            return True
    return False


def _append_case(case: Dict[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(case, ensure_ascii=False) + "\n")


# ============================================================
# 台账回写
# ============================================================


def _rewrite_ledger(rows: Iterable[Dict[str, Any]], path: Path) -> None:
    """原子替换台账文件（保持行序；不追加重复 task_id）。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows),
        encoding="utf-8",
    )
    os.replace(tmp, path)


def settle_task(
    task_id: str,
    regression: Dict[str, Any],
    run_ids: Sequence[str],
    splits: Optional[Dict[str, Any]] = None,
    ledger_path: Optional[Path] = None,
    case_store_path: Optional[Path] = None,
    by: str = "l2_settle",
    now: Optional[datetime] = None,
) -> Dict[str, Any]:
    """把 `regression_passed` 条目结算为 `settled`，并按四分流回写案例。

    幂等：已是 `settled` 的同一条目直接返回（不重复回写）。
    """
    path = Path(ledger_path) if ledger_path else DEFAULT_LEDGER_PATH
    case_path = Path(case_store_path) if case_store_path else DEFAULT_CASE_STORE_PATH

    if len(str(by).strip()) < 2:
        raise SettleError("history.by 至少 2 字（留痕责任主体）")

    rows = load_ledger(path)
    index = next((i for i, row in enumerate(rows) if row.get("task_id") == task_id), None)
    if index is None:
        raise SettleError(f"台账未找到 task_id={task_id}")

    entry = rows[index]
    current = entry.get("state")
    if current == "settled":
        return entry
    if current != "regression_passed":
        raise SettleError(
            f"只有 regression_passed 可 settle（当前 state={current}）；不可跳步或终态重开"
        )

    _validate_regression(regression)
    normalized_run_ids = _validate_run_ids(run_ids)
    normalized_splits = _normalize_splits(splits)

    stamp = now or datetime.now(timezone.utc)
    iso_now = _iso(stamp)

    settled_entry = copy.deepcopy(entry)
    settled_entry["state"] = "settled"
    settled_entry["history"] = list(entry.get("history") or []) + [
        {"from": "regression_passed", "to": "settled", "at": iso_now, "by": str(by)}
    ]
    settled_entry["evidence"] = dict(entry.get("evidence") or {})
    settled_entry["evidence"]["regression"] = copy.deepcopy(dict(regression))
    settled_entry["settled"] = normalized_splits
    settled_entry["run_ids"] = normalized_run_ids
    settled_entry["updated_at"] = iso_now

    # 先过契约，再落任何文件：不合契约的结算不污染案例库
    validate_entry(settled_entry)

    if normalized_splits["case"] == "done" and not _case_exists(case_path, task_id):
        _append_case(build_case(settled_entry, iso_now), case_path)

    rows[index] = settled_entry
    _rewrite_ledger(rows, path)
    return settled_entry


# ============================================================
# 周报
# ============================================================


def _rate(numerator: int, denominator: int) -> Dict[str, Any]:
    value = round(numerator / denominator, 4) if denominator else None
    return {"value": value, "numerator": numerator, "denominator": denominator}


def _optimization_view(row: Dict[str, Any], settled_at: str) -> Dict[str, Any]:
    metrics: List[Dict[str, Any]] = []
    for item in row.get("metrics") or []:
        if not isinstance(item, dict):
            continue
        before = item.get("before")
        after = item.get("after")
        delta = None
        delta_pct = None
        if isinstance(before, (int, float)) and isinstance(after, (int, float)):
            delta = round(after - before, 6)
            delta_pct = round((after - before) / abs(before) * 100, 2) if before else None
        metrics.append(
            {
                "name": item.get("name"),
                "unit": item.get("unit"),
                "before": before,
                "after": after,
                "delta": delta,
                "delta_pct": delta_pct,
            }
        )
    return {
        "task_id": row.get("task_id"),
        "symptom": row.get("symptom"),
        "settled_at": settled_at,
        "metrics": metrics,
        "evidence": (row.get("evidence") or {}).get("optimization") or {},
    }


def weekly_report(
    rows: Iterable[Dict[str, Any]],
    since: Any,
    until: Any,
    now: Optional[datetime] = None,
) -> Dict[str, Any]:
    """按事件窗口出周报。

    - 修复率：窗口内 `to=settled` / (`to=settled` + `to=abandoned`)
    - 回归通过率：窗口内 `evidence.regression.ts` 的 `passed=true` 占比
    - 优化收益：窗口内 settled 的 optimization 条目，逐指标给 before/after/delta
    - 样本为 0 时指标为 null，不按 0 记
    """
    since_dt = _parse_ts(since)
    until_dt = _parse_ts(until)
    if since_dt >= until_dt:
        raise SettleError("周报窗口非法：since 必须早于 until")

    row_list = list(rows)
    settled_events: List[Tuple[Dict[str, Any], str]] = []
    abandoned_events: List[Tuple[Dict[str, Any], str]] = []
    regressions: List[Dict[str, Any]] = []
    created = 0
    active = 0

    for row in row_list:
        if _in_window(row.get("created_at"), since_dt, until_dt):
            created += 1
            if row.get("state") not in TERMINAL_STATES:
                active += 1

        for item in row.get("history") or []:
            if not isinstance(item, dict):
                continue
            target = item.get("to")
            if target == "settled" and _in_window(item.get("at"), since_dt, until_dt):
                settled_events.append((row, str(item.get("at"))))
            elif target == "abandoned" and _in_window(item.get("at"), since_dt, until_dt):
                abandoned_events.append((row, str(item.get("at"))))

        regression = (row.get("evidence") or {}).get("regression")
        if isinstance(regression, dict) and _in_window(regression.get("ts"), since_dt, until_dt):
            regressions.append(regression)

    fix_rate = _rate(len(settled_events), len(settled_events) + len(abandoned_events))
    fix_rate["formula"] = "settled/(settled+abandoned)"

    regression_rate = _rate(
        sum(1 for item in regressions if item.get("passed") is True), len(regressions)
    )
    regression_rate["formula"] = "passed/regression_evidence"

    optimizations = [
        _optimization_view(row, settled_at)
        for row, settled_at in settled_events
        if row.get("kind") == "optimization"
    ]

    notes = [
        "优化收益只报 before/after/delta，方向由指标语义决定，不做自动优劣判定。",
        "tokens 成本未纳入周报：GAP-17（L2Envelope.tokens_used 未接通）。",
    ]
    if fix_rate["denominator"] == 0:
        notes.append("样本不足：窗口内无 settled/abandoned 事件，修复率为 null（不按 0 记）。")
    if regression_rate["denominator"] == 0:
        notes.append("样本不足：窗口内无回归证据，回归通过率为 null（不按 0 记）。")

    return {
        "schema_version": REPORT_SCHEMA_VERSION,
        "generated_at": _iso(now),
        "window": {"since": _iso(since_dt), "until": _iso(until_dt)},
        "counts": {
            "created": created,
            "settled": len(settled_events),
            "abandoned": len(abandoned_events),
            "active": active,
        },
        "fix_rate": fix_rate,
        "regression_pass_rate": regression_rate,
        "optimizations": optimizations,
        "notes": notes,
    }


def _fmt_rate(stat: Dict[str, Any]) -> str:
    if stat.get("value") is None:
        return f"null（样本不足：0/{stat.get('denominator', 0)}）"
    return f"{stat['value'] * 100:.1f}%（{stat.get('numerator')}/{stat.get('denominator')}）"


def _fmt_num(value: Any) -> str:
    return "—" if value is None else str(value)


def render_weekly_markdown(report: Dict[str, Any]) -> str:
    window = report.get("window") or {}
    counts = report.get("counts") or {}
    lines = [
        f"# L2 开发端周报（{window.get('since')} ~ {window.get('until')}）",
        "",
        f"生成时间：{report.get('generated_at')}",
        f"台账样本：created={counts.get('created', 0)} / settled={counts.get('settled', 0)}"
        f" / abandoned={counts.get('abandoned', 0)} / active={counts.get('active', 0)}",
        "",
        "## 核心指标",
        "",
        "| 指标 | 值 | 口径 |",
        "|---|---|---|",
        f"| 修复率 | {_fmt_rate(report.get('fix_rate') or {})} | settled/(settled+abandoned) |",
        f"| 回归通过率 | {_fmt_rate(report.get('regression_pass_rate') or {})} | passed/regression_evidence |",
        "",
        "## 优化收益",
        "",
    ]

    optimizations = report.get("optimizations") or []
    if not optimizations:
        lines.append("- 窗口内无已结算的优化任务（样本不足，不做收益推断）。")
    else:
        lines.append("| task_id | 指标 | 单位 | before | after | Δ | Δ% |")
        lines.append("|---|---|---|---|---|---|---|")
        for opt in optimizations:
            metrics = opt.get("metrics") or []
            if not metrics:
                lines.append(f"| {opt.get('task_id')} | — | — | — | — | — | — |")
                continue
            for metric in metrics:
                lines.append(
                    "| {} | {} | {} | {} | {} | {} | {} |".format(
                        opt.get("task_id"),
                        metric.get("name"),
                        metric.get("unit"),
                        _fmt_num(metric.get("before")),
                        _fmt_num(metric.get("after")),
                        _fmt_num(metric.get("delta")),
                        _fmt_num(metric.get("delta_pct")),
                    )
                )

    lines += ["", "## 口径说明", ""]
    lines += [f"- {note}" for note in report.get("notes") or []]
    lines.append("")
    return "\n".join(lines)


# ============================================================
# CLI
# ============================================================


def _cli(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(prog="l2_settle.py", description="L2 settle 回写与周报")
    sub = parser.add_subparsers(dest="command", required=True)

    weekly = sub.add_parser("weekly", help="出周报（修复率/回归通过率/优化收益）")
    weekly.add_argument("--since", help="窗口起点（ISO 8601，缺省=until-7d）")
    weekly.add_argument("--until", help="窗口终点（ISO 8601，缺省=当前时间）")
    weekly.add_argument("--ledger", type=Path, default=DEFAULT_LEDGER_PATH)
    weekly.add_argument("--format", choices=("md", "json"), default="md")
    weekly.add_argument("--out", type=Path, help="落盘路径（缺省只打印）")

    settle = sub.add_parser("settle", help="把 regression_passed 条目结算为 settled")
    settle.add_argument("task_id")
    settle.add_argument("--payload", type=Path, required=True, help="{regression,run_ids,splits}")
    settle.add_argument("--ledger", type=Path, default=DEFAULT_LEDGER_PATH)
    settle.add_argument("--case-store", type=Path, default=DEFAULT_CASE_STORE_PATH)

    args = parser.parse_args(argv)

    if args.command == "settle":
        payload = json.loads(args.payload.read_text(encoding="utf-8"))
        entry = settle_task(
            args.task_id,
            regression=payload["regression"],
            run_ids=payload["run_ids"],
            splits=payload.get("splits"),
            ledger_path=args.ledger,
            case_store_path=args.case_store,
        )
        print(json.dumps(entry, ensure_ascii=False))
        return 0

    until = _parse_ts(args.until) if args.until else datetime.now(timezone.utc)
    since = _parse_ts(args.since) if args.since else until - timedelta(days=7)
    report = weekly_report(load_ledger(args.ledger), since, until)
    text = (
        json.dumps(report, ensure_ascii=False, indent=2)
        if args.format == "json"
        else render_weekly_markdown(report)
    )
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(text + "\n", encoding="utf-8")
    print(text)
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(_cli())
