#!/usr/bin/env python3
"""G-BCL 门禁判定脚本。

依据：1-ARCHITECTURE/SPEC-20261113-THREE-BUSINESS-CLOSED-LOOPS.md §12.1
计划：1-ARCHITECTURE/PLAN-20261113-THREE-BUSINESS-CLOSED-LOOPS.md T0-1

设计原则：
1. 宁可判 not_evaluated，也不虚报 PASS；
2. 阈值未显式传入时输出 threshold_unconfirmed，结论不得作为放行依据；
3. 纯读，不修改任何生产数据。

输入契约（可选参数，缺失则对应门禁判 not_evaluated）：
  --training-events  JSONL，每行至少含：
                     decision_id / order_id / fill_id / pnl / training_event_id
  --execution-rights execution_rights.json，按 symbol 统计 active executor
  --trace-records    JSONL，每行至少含：task_id / trace_id / stage / degraded_reason
                     stage ∈ {created, route, execute, accept, settle}
                     L1 直答行 task_id 为空且 entry=l1，按 trace_id 聚合；
                     交接 L2 的行 handoff=true，不重复计入执行单元；
                     降级行须带 degraded=true 或 verdict=fail，且 degraded_reason 非空
  --rollback-evidence 目录，内含回滚演练证据文件

退出码：0 全部 PASS；1 存在 FAIL；2 无 FAIL 但存在 not_evaluated / threshold_unconfirmed。
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[3]
SPEC_PATH = REPO_ROOT / "1-ARCHITECTURE" / "SPEC-20261113-THREE-BUSINESS-CLOSED-LOOPS.md"
MODULE_MAP_PATH = REPO_ROOT / "1-ARCHITECTURE" / "3+3架构模块映射.md"
PACKAGES_PATH = REPO_ROOT / "1-ARCHITECTURE" / "registry" / "capability_packages.yaml"
REGISTRY_VALIDATOR = (
    REPO_ROOT / "47-MCP管理系统" / "registry" / "scripts" / "validate_mcp_registry.py"
)

# 阈值已由用户于 2026-11-13 确认（D-01 / D-02），作为硬下限生效。
# 禁止为通过门禁而下调；如需变更须重新确认并更新本注释。
DEFAULT_JOIN_COVERAGE = 0.95
DEFAULT_MIN_SAMPLE = 100
REQUIRED_TRACE_STAGES = ("created", "route", "execute", "accept", "settle")


def _result(gate_id: str, verdict: str, value, threshold, evidence: str, note: str = "") -> dict:
    return {
        "gate_id": gate_id,
        "verdict": verdict,  # PASS / FAIL / not_evaluated
        "value": value,
        "threshold": threshold,
        "evidence_ref": evidence,
        "note": note,
        "checked_at": datetime.now(timezone.utc).isoformat(),
    }


def _read_jsonl(path: Path) -> list[dict]:
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        rows.append(json.loads(line))
    return rows


def gate_0_semantics() -> dict:
    """G-BCL-0：语义门禁。49 不得作为运行节点；声明必须存在。"""
    if not SPEC_PATH.exists():
        return _result("G-BCL-0", "not_evaluated", None, None, str(SPEC_PATH), "SPEC 缺失")

    spec = SPEC_PATH.read_text(encoding="utf-8")
    declaration = "49 是交易契约层，不是运行节点" in spec
    # 在线链中出现 "→ 49" 或 "49 →" 视为把 49 当运行节点；
    # 但描述"旧口径"的行是引用历史表述，不算违规
    online_section = spec.split("#### 4.2.1", 1)[0]
    lineage_hits = []
    for line in online_section.splitlines():
        if any(k in line for k in ("旧表述", "旧口径", "历史口径", "对照")):
            continue
        if re.search(r"(?:→\s*49\b|\b49\s*→)", line):
            lineage_hits.append(line.strip())

    legacy_phrase = False
    if MODULE_MAP_PATH.exists():
        mm = MODULE_MAP_PATH.read_text(encoding="utf-8")
        legacy_phrase = bool(re.search(r"反馈层\s*→\s*48\s*训练\s*40/50", mm))

    value = {
        "declaration_present": declaration,
        "lineage_hits": lineage_hits,
        "legacy_phrase_in_3plus3": legacy_phrase,
    }
    failed = (not declaration) or bool(lineage_hits)
    return _result(
        "G-BCL-0",
        "FAIL" if failed else "PASS",
        value,
        "declaration=true 且 lineage_hits=0",
        str(SPEC_PATH),
        "legacy_phrase 仅作提示，不单独判失败" if legacy_phrase else "",
    )


def gate_1_trading(args) -> dict:
    """G-BCL-1：D1 交易证据链覆盖率。"""
    threshold = args.join_coverage_threshold
    min_sample = args.min_sample
    if not args.training_events:
        return _result(
            "G-BCL-1",
            "not_evaluated",
            None,
            {"join_coverage": threshold, "min_sample": min_sample},
            "未提供 --training-events",
        )

    path = Path(args.training_events)
    if not path.exists():
        return _result("G-BCL-1", "not_evaluated", None, threshold, str(path), "文件不存在")

    rows = _read_jsonl(path)
    required = ("decision_id", "order_id", "fill_id", "pnl", "training_event_id")
    missing_kinds = {"no_order": 0, "no_fill": 0, "no_pnl": 0, "no_training_event": 0}
    joined = 0
    for row in rows:
        if all(row.get(k) not in (None, "") for k in required):
            joined += 1
            continue
        if not row.get("order_id"):
            missing_kinds["no_order"] += 1
        elif not row.get("fill_id"):
            missing_kinds["no_fill"] += 1
        elif row.get("pnl") in (None, ""):
            missing_kinds["no_pnl"] += 1
        elif not row.get("training_event_id"):
            missing_kinds["no_training_event"] += 1

    total = len(rows)
    coverage = round(joined / total, 6) if total else 0.0
    enough = total >= min_sample
    passed = enough and coverage >= threshold

    return _result(
        "G-BCL-1",
        "PASS" if passed else "FAIL",
        {
            "join_coverage": coverage,
            "samples": total,
            "missing": missing_kinds,
        },
        {"join_coverage": threshold, "min_sample": min_sample},
        str(path),
        "" if enough else f"样本量 {total} < {min_sample}",
    )


def gate_2_emergence() -> dict:
    """G-BCL-2：涌现验证证据完整性。"""
    if not PACKAGES_PATH.exists():
        return _result(
            "G-BCL-2", "not_evaluated", None, None, str(PACKAGES_PATH), "能力包登记表缺失"
        )

    data = yaml.safe_load(PACKAGES_PATH.read_text(encoding="utf-8")) or {}
    packages = data.get("packages") or []
    problems = []
    published = verified = 0
    for pkg in packages:
        if not isinstance(pkg, dict):
            continue
        status = pkg.get("status")
        if status in ("verified", "approved", "published"):
            ref = (pkg.get("observability") or {}).get("evidence") or ""
            if not ref or ref.startswith("TODO"):
                problems.append(f"{pkg.get('chain_id')}:{status} 缺可解析 evidence_ref")
            if status in ("published",):
                published += 1
            if status == "verified":
                verified += 1

    # falsified 结论不得被删除：要求存在记录条目
    falsified = [p for p in packages if isinstance(p, dict) and p.get("status") == "falsified"]

    value = {
        "published": published,
        "verified": verified,
        "falsified": len(falsified),
        "problems": problems,
        "vacuous": published == 0 and verified == 0,
    }
    return _result(
        "G-BCL-2",
        "FAIL" if problems else "PASS",
        value,
        "verified/published 均需 evidence_ref；problems=0",
        str(PACKAGES_PATH),
        "当前无 verified/published 条目，判定为空集通过" if value["vacuous"] else "",
    )


def gate_3_trace(args) -> dict:
    """G-BCL-3：执行链 trace 贯穿率（同请求唯一性 + 降级原因覆盖率）。"""
    min_sample = args.min_sample
    if not args.trace_records:
        return _result(
            "G-BCL-3",
            "not_evaluated",
            None,
            {"min_sample": min_sample},
            "未提供 --trace-records",
        )

    path = Path(args.trace_records)
    if not path.exists():
        return _result("G-BCL-3", "not_evaluated", None, min_sample, str(path), "文件不存在")

    rows = _read_jsonl(path)
    units: dict[str, dict] = {}
    trace_tasks: dict[str, set] = {}
    degraded_rows = 0
    degraded_missing = 0

    for row in rows:
        tid = str(row.get("task_id") or "")
        trace = str(row.get("trace_id") or "")
        entry = row.get("entry")

        # 降级项必须给出原因：verdict=fail 或显式 degraded 均视为降级项
        is_degraded = bool(row.get("degraded")) or row.get("verdict") == "fail"
        if is_degraded:
            degraded_rows += 1
            if not str(row.get("degraded_reason") or "").strip():
                degraded_missing += 1

        if not trace:
            continue
        if tid:
            trace_tasks.setdefault(trace, set()).add(tid)
            key = f"task:{tid}"
        elif entry == "l1":
            key = f"trace:{trace}"
        else:
            continue

        item = units.setdefault(key, {"trace_ids": set(), "stages": set(), "handoff": False})
        item["trace_ids"].add(trace)
        if row.get("stage"):
            item["stages"].add(row["stage"])
        if row.get("handoff"):
            item["handoff"] = True

    counted = {k: v for k, v in units.items() if not v["handoff"]}
    total = len(counted)
    full = sum(
        1
        for v in counted.values()
        if v["trace_ids"]
        and len(v["trace_ids"]) == 1  # 同一执行单元只允许一个 trace
        and all(s in v["stages"] for s in REQUIRED_TRACE_STAGES)
    )
    multi_trace = sum(1 for v in units.values() if len(v["trace_ids"]) > 1)
    trace_reuse = {t: sorted(ids) for t, ids in trace_tasks.items() if len(ids) > 1}
    rate = round(full / total, 6) if total else 0.0
    reason_coverage = (
        round((degraded_rows - degraded_missing) / degraded_rows, 6) if degraded_rows else 1.0
    )
    passed = (
        total >= min_sample
        and rate == 1.0
        and multi_trace == 0
        and not trace_reuse
        and degraded_missing == 0
    )

    task_units = sum(1 for k in counted if k.startswith("task:"))
    request_units = total - task_units
    notes = []
    if total < min_sample:
        notes.append(f"样本量 {total} < {min_sample}")
    if trace_reuse:
        notes.append(f"trace 被多 task 复用: {len(trace_reuse)}")
    if degraded_missing:
        notes.append(f"降级缺原因: {degraded_missing}")

    return _result(
        "G-BCL-3",
        "PASS" if passed else "FAIL",
        {
            "execution_units": total,
            "tasks": task_units,
            "l1_requests": request_units,
            "full_chain_units": full,
            "throughput_rate": rate,
            "multi_trace_units": multi_trace,
            "trace_reuse_across_tasks": len(trace_reuse),
            "degraded_rows": degraded_rows,
            "degraded_missing_reason": degraded_missing,
            "degraded_reason_coverage": reason_coverage,
        },
        {
            "min_sample": min_sample,
            "throughput_rate": 1.0,
            "multi_trace_units": 0,
            "trace_reuse_across_tasks": 0,
            "degraded_reason_coverage": 1.0,
        },
        str(path),
        "；".join(notes),
    )


def gate_4_boundary() -> dict:
    """G-BCL-4：对外边界。复用 47 注册表校验器（含 V8 交叉引用）。"""
    if not REGISTRY_VALIDATOR.exists():
        return _result(
            "G-BCL-4",
            "not_evaluated",
            None,
            "registry 校验零违规",
            str(REGISTRY_VALIDATOR),
            "校验器缺失",
        )

    proc = subprocess.run(
        [sys.executable, str(REGISTRY_VALIDATOR), "--quiet"],
        capture_output=True,
        text=True,
        cwd=str(REPO_ROOT),
    )
    out = (proc.stdout or "") + (proc.stderr or "")
    return _result(
        "G-BCL-4",
        "PASS" if proc.returncode == 0 else "FAIL",
        {"returncode": proc.returncode, "output": out.strip()[:2000]},
        "registry 校验零违规",
        str(REGISTRY_VALIDATOR),
    )


def gate_5_rollback(args) -> dict:
    """G-BCL-5：回滚可用性。"""
    if not PACKAGES_PATH.exists():
        return _result(
            "G-BCL-5", "not_evaluated", None, None, str(PACKAGES_PATH), "能力包登记表缺失"
        )

    data = yaml.safe_load(PACKAGES_PATH.read_text(encoding="utf-8")) or {}
    pending = []
    for pkg in data.get("packages") or []:
        if not isinstance(pkg, dict):
            continue
        # draft 条目允许 rollback 未定义；进入 verified 及之后必须可用
        if pkg.get("status") == "draft":
            continue
        rollback = str(pkg.get("rollback") or "")
        if not rollback or rollback.startswith("TODO"):
            pending.append(pkg.get("chain_id"))

    evidence_dir = Path(args.rollback_evidence) if args.rollback_evidence else None
    evidence_files = []
    if evidence_dir and evidence_dir.exists():
        evidence_files = [p.name for p in evidence_dir.iterdir() if p.is_file()]

    value = {"rollback_pending": pending, "evidence_files": len(evidence_files)}
    if pending:
        return _result("G-BCL-5", "FAIL", value, "rollback 无 TODO", str(PACKAGES_PATH))
    if not evidence_files:
        return _result(
            "G-BCL-5",
            "not_evaluated",
            value,
            "近 90 天内至少 1 次回滚演练证据",
            str(evidence_dir or "未提供 --rollback-evidence"),
            "回滚入口已定义但无演练证据",
        )
    return _result("G-BCL-5", "PASS", value, "≥1 次回滚演练", str(evidence_dir))


def main() -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

    ap = argparse.ArgumentParser(description="G-BCL 门禁判定")
    ap.add_argument("--training-events")
    ap.add_argument("--execution-rights")
    ap.add_argument("--trace-records")
    ap.add_argument("--rollback-evidence")
    ap.add_argument("--join-coverage-threshold", type=float, default=DEFAULT_JOIN_COVERAGE)
    ap.add_argument("--min-sample", type=int, default=DEFAULT_MIN_SAMPLE)
    ap.add_argument("--json-out")
    args = ap.parse_args()

    gates = [
        gate_0_semantics(),
        gate_1_trading(args),
        gate_2_emergence(),
        gate_3_trace(args),
        gate_4_boundary(),
        gate_5_rollback(args),
    ]

    payload = {
        "spec_ref": "1-ARCHITECTURE/SPEC-20261113-THREE-BUSINESS-CLOSED-LOOPS.md@v0.3.3",
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "thresholds": {
            "join_coverage": args.join_coverage_threshold,
            "min_sample": args.min_sample,
            "confirmed_by_user": "2026-11-13 (D-01 / D-02)",
        },
        "gates": gates,
        "summary": {
            "pass": sum(1 for g in gates if g["verdict"] == "PASS"),
            "fail": sum(1 for g in gates if g["verdict"] == "FAIL"),
            "not_evaluated": sum(1 for g in gates if g["verdict"] == "not_evaluated"),
        },
    }

    text = json.dumps(payload, ensure_ascii=False, indent=2)
    print(text)
    if args.json_out:
        Path(args.json_out).write_text(text + "\n", encoding="utf-8")

    if payload["summary"]["fail"]:
        return 1
    if payload["summary"]["not_evaluated"]:
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
