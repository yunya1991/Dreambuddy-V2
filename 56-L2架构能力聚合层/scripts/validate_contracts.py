#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""56-L2 契约校验器（G-L2-7/8/9 与总装线 A0 四契约的可执行判定）。

用法：
  python3 scripts/validate_contracts.py --self-test
  python3 scripts/validate_contracts.py --ledger <file.json|file.jsonl>
  python3 scripts/validate_contracts.py --plugin <file.json>
  python3 scripts/validate_contracts.py --stop-reason <file.json>
  python3 scripts/validate_contracts.py --tool-set <file.json>
  python3 scripts/validate_contracts.py --span <file.json>
  python3 scripts/validate_contracts.py --plan <file.json>

退出码：0 全部通过；1 存在违规或自检失败。

判定范围：
- repair_ledger.schema.json：结构/枚举/签名/条件必填；
- state_machine.yaml：初始态、链式连续性、合法边、终态、attempts 上限、重开 reason；
- trigger.ref 与 resolver 的匹配（G-L2-7）；
- plugin_extension.schema.json：四动作 request/response、错误码、install 的 rollback_verified；
- 总装线 A0：stop_reason / tool_set / span / plan_handoff 四契约。

说明：guard 只对**最后一条迁移**求值（历史边只做结构校验），避免「回归失败→重开→再通过」
后历史 guard 被终态覆盖而误判。
"""

from __future__ import annotations

import argparse
import copy
import json
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Tuple

import yaml
from jsonschema import Draft202012Validator, FormatChecker

ROOT = Path(__file__).resolve().parents[1]
CONTRACTS = ROOT / "contracts"
LEDGER_SCHEMA = CONTRACTS / "repair_ledger.schema.json"
PLUGIN_SCHEMA = CONTRACTS / "plugin_extension.schema.json"
STATE_MACHINE = CONTRACTS / "state_machine.yaml"
STOP_REASON_SCHEMA = CONTRACTS / "stop_reason.schema.json"
TOOL_SET_SCHEMA = CONTRACTS / "tool_set.schema.json"
SPAN_SCHEMA = CONTRACTS / "span.schema.json"
PLAN_SCHEMA = CONTRACTS / "plan_handoff.schema.json"

RESOLVER_PATTERNS = {
    "48.experiment_id": r"^(D2B|D3B|XA)-[A-Za-z0-9._-]{3,}$",
    "54.discovery_path": r"^reports/discovery/\d{8}-\d{4}/?$",
    "github.issue": r"^(https://github\.com/[\w.-]+/[\w.-]+/issues/\d+|#?\d+)$",
}

_MISSING = object()


def load_json(path: Path) -> Any:
    with path.open(encoding="utf-8") as fh:
        return json.load(fh)


def schema_errors(doc: Any, schema: Any) -> List[str]:
    validator = Draft202012Validator(schema, format_checker=FormatChecker())
    out = []
    for err in sorted(validator.iter_errors(doc), key=lambda e: list(e.absolute_path)):
        loc = "/".join(str(p) for p in err.absolute_path) or "<root>"
        out.append(f"{loc}: {err.message}")
    return out


def _get(doc: Any, path: str) -> Any:
    if path == "history[-1].reason":
        history = doc.get("history") or []
        return history[-1].get("reason", _MISSING) if history else _MISSING
    cur = doc
    for part in path.split("."):
        if not isinstance(cur, dict) or part not in cur:
            return _MISSING
        cur = cur[part]
    return cur


def eval_guard(doc: Dict[str, Any], guard: Dict[str, Any]) -> Tuple[bool, str]:
    value = _get(doc, guard["field"])
    op = guard["op"]
    expected = guard.get("value")

    if op == "non_empty":
        ok = (
            value is not _MISSING
            and value is not None
            and (len(value) > 0 if hasattr(value, "__len__") else bool(value))
        )
    elif op == "present":
        ok = value is not _MISSING and value not in (None, "")
    elif op == "eq":
        ok = value is not _MISSING and value == expected
    elif op == "in":
        ok = value is not _MISSING and value in (expected or [])
    elif op == "min_len":
        ok = isinstance(value, str) and len(value) >= int(expected)
    elif op == "min_items":
        ok = isinstance(value, list) and len(value) >= int(expected)
    elif op == "keys":
        ok = isinstance(value, dict) and all(k in value for k in (expected or []))
    else:
        return False, f"未知 guard 算子: {op}"
    return ok, "" if ok else f"guard 未满足: {guard['field']} {op} {expected}（实际 {value!r}）"


def validate_trigger(doc: Dict[str, Any]) -> List[str]:
    errors: List[str] = []
    trigger = doc.get("trigger") or {}
    resolver = trigger.get("resolver")
    ref = trigger.get("ref", "")
    pattern = RESOLVER_PATTERNS.get(resolver)
    if not pattern:
        errors.append(f"trigger.resolver 未知: {resolver}")
    elif not re.match(pattern, str(ref)):
        errors.append(f"trigger.ref 与 resolver={resolver} 不匹配（G-L2-7）: {ref!r}")
    return errors


def validate_state_machine(doc: Dict[str, Any], sm: Dict[str, Any]) -> List[str]:
    errors: List[str] = []
    history = doc.get("history") or []
    if not history:
        return ["history 为空，无法校验迁移"]

    if history[0].get("from") != sm["initial"]:
        errors.append(f"history 起点必须为 {sm['initial']}，实际 {history[0].get('from')}")

    for prev, cur in zip(history, history[1:], strict=False):
        if cur.get("from") != prev.get("to"):
            errors.append(f"history 链断裂: {prev.get('to')} → {cur.get('from')}")

    last = history[-1]
    if last.get("to") != doc.get("state"):
        errors.append(f"state={doc.get('state')} 与最后一条迁移 to={last.get('to')} 不一致")

    edges = {(t["from"], t["to"]): t for t in sm["transitions"]}
    reopen_count = 0
    for idx, item in enumerate(history):
        key = (item.get("from"), item.get("to"))
        edge = edges.get(key)
        if edge is None:
            errors.append(f"非法迁移: {key[0]} → {key[1]}")
            continue
        if edge.get("reopen"):
            reopen_count += 1
            if sm["reopen"].get("require_reason") and not item.get("reason"):
                errors.append(f"重开迁移缺少 reason: {key[0]} → {key[1]}")
        if idx == len(history) - 1:  # 只对最后一条迁移求 guard
            for guard_name in edge.get("guards", []):
                guard = sm["guards"].get(guard_name)
                if guard is None:
                    errors.append(f"未定义 guard: {guard_name}")
                    continue
                ok, msg = eval_guard(doc, guard)
                if not ok:
                    errors.append(msg)

    max_attempts = int(sm.get("max_attempts", 3))
    attempts = doc.get("attempts")
    if reopen_count != attempts:
        errors.append(f"attempts={attempts} 与重开次数 {reopen_count} 不一致")
    if isinstance(attempts, int) and attempts > max_attempts:
        errors.append(f"attempts={attempts} 超过上限 {max_attempts}")

    if doc.get("state") in sm.get("terminal", []) and last.get("to") != doc.get("state"):
        errors.append(f"终态 {doc.get('state')} 缺少对应迁移")
    return errors


def validate_ledger(doc: Dict[str, Any]) -> List[str]:
    schema = load_json(LEDGER_SCHEMA)
    sm = yaml.safe_load(STATE_MACHINE.read_text(encoding="utf-8"))
    errors = schema_errors(doc, schema)
    errors += validate_trigger(doc)
    errors += validate_state_machine(doc, sm)
    return errors


def validate_plugin(doc: Dict[str, Any]) -> List[str]:
    return schema_errors(doc, load_json(PLUGIN_SCHEMA))


def _parse_ts(value: str) -> datetime:
    return datetime.fromisoformat(str(value).replace("Z", "+00:00"))


def validate_stop_reason(doc: Dict[str, Any]) -> List[str]:
    return schema_errors(doc, load_json(STOP_REASON_SCHEMA))


def validate_tool_set(doc: Dict[str, Any]) -> List[str]:
    errors = schema_errors(doc, load_json(TOOL_SET_SCHEMA))
    try:
        _parse_ts(doc["generated_at"])
    except (KeyError, ValueError) as exc:
        errors.append(f"generated_at 不是合法 RFC3339 时间: {exc}")
    tools = doc.get("tools") or []
    names = [t.get("name") for t in tools if isinstance(t, dict)]
    dup = sorted({n for n in names if names.count(n) > 1})
    if dup:
        errors.append(f"tools 名称重复: {dup}")
    denied = set(doc.get("denied_tools") or [])
    overlap = sorted(denied.intersection(names))
    if overlap:
        errors.append(f"denied_tools 与 tools 冲突: {overlap}")
    return errors


def validate_span(doc: Dict[str, Any]) -> List[str]:
    errors = schema_errors(doc, load_json(SPAN_SCHEMA))
    try:
        if _parse_ts(doc["ended_at"]) < _parse_ts(doc["started_at"]):
            errors.append("ended_at 早于 started_at")
    except (KeyError, ValueError) as exc:
        errors.append(f"时间字段无法解析: {exc}")
    return errors


def validate_plan(doc: Dict[str, Any]) -> List[str]:
    errors = schema_errors(doc, load_json(PLAN_SCHEMA))
    budget = doc.get("budget") or {}
    soft, hard = budget.get("soft_tokens"), budget.get("hard_tokens")
    if isinstance(soft, int) and isinstance(hard, int) and soft > hard:
        errors.append(f"budget.soft_tokens({soft}) 不得大于 hard_tokens({hard})")
    indexes = [s.get("index") for s in (doc.get("steps") or []) if isinstance(s, dict)]
    if indexes != list(range(1, len(indexes) + 1)):
        errors.append(f"steps.index 必须从 1 连续递增，实际 {indexes}")
    return errors


# --------------------------------------------------------------------------
# 自检：1 个正例 + 5 个负例（台账）+ 1 个正例 + 1 个负例（插件）
# --------------------------------------------------------------------------


def _base_ledger() -> Dict[str, Any]:
    t = "2026-11-16T10:0{}:00+08:00"
    return {
        "schema_version": "1.1",
        "task_id": "fix-20261116-001",
        "kind": "bugfix",
        "trigger": {
            "source": "bug_report",
            "resolver": "github.issue",
            "ref": "#123",
            "resolved_at": t.format(0),
        },
        "state": "settled",
        "history": [
            {"from": "reported", "to": "reproduced", "at": t.format(0), "by": "agent"},
            {"from": "reproduced", "to": "root_caused", "at": t.format(1), "by": "agent"},
            {"from": "root_caused", "to": "fixed", "at": t.format(2), "by": "agent"},
            {"from": "fixed", "to": "regression_passed", "at": t.format(3), "by": "pytest"},
            {"from": "regression_passed", "to": "settled", "at": t.format(4), "by": "agent"},
        ],
        "attempts": 0,
        "symptom": "L1 路由在空候选集时抛 KeyError",
        "reported": {"repo": "dreambuddy-v2", "base_commit": "a1b2c3d", "env": "py3.12/local"},
        "root_cause": "空候选集未走 early-return，索引越界",
        "change_ref": {"type": "commit", "sha": "d4e5f6a1b2c3", "summary": "空集 early-return"},
        "evidence": {
            "repro": {
                "cmd": "pytest tests/test_route_signal.py -k empty",
                "fails_on_base": True,
                "artifact_hash": "sha256:" + "0" * 64,
            },
            "regression": {
                "runner": "pytest",
                "cmd": "pytest tests/test_route_signal.py -q",
                "exit_code": 0,
                "passed": True,
                "ts": t.format(4),
                "log_uri": "logs/pytest-123.txt",
            },
        },
        "metrics": [],
        "settled": {"case": "done", "cognition": "done", "process": "done", "doc": "skipped"},
        "run_ids": ["run-001"],
        "created_at": t.format(0),
        "updated_at": t.format(4),
    }


def _install_request(rollback_verified: bool = True) -> Dict[str, Any]:
    return {
        "schema_version": "1.0",
        "op": "install",
        "direction": "request",
        "request_id": "req-0001",
        "manifest": {
            "plugin_id": "demo.plugin",
            "version": "1.0.0",
            "entry": "index.js",
            "permissions": ["fs.read"],
        },
        "mandate": {
            "mandate_id": "m-0001",
            "granted_by": "user",
            "scope": "plugin.install",
            "expires_at": "2026-11-30T00:00:00+08:00",
        },
        "rollback_verified": rollback_verified,
    }


def _base_stop(reason: str = "done", parked: str | None = None) -> Dict[str, Any]:
    doc: Dict[str, Any] = {
        "schema_version": "1.1",
        "trace_id": "trace-20261116-001",
        "run_id": "run-20261116-001",
        "stop_reason": reason,
        "resumable": reason in {"interrupted", "cost_limit", "max_steps", "parked"},
        "steps": 3,
        "tokens_used": 1200,
        "cost_cu": 2.5,
        "detail": {},
    }
    if parked:
        doc["parked_reason"] = parked
    return doc


def _base_tool_set() -> Dict[str, Any]:
    return {
        "schema_version": "1.0",
        "run_id": "run-20261116-001",
        "generated_at": "2026-11-16T10:00:00+08:00",
        "source": "47-registry",
        "policy": {"order": ["deny", "mode", "allow", "human"], "mode": "default"},
        "tools": [
            {
                "name": "l2.dreamos.poll_run",
                "shell": "l2.dreamos.mcp",
                "layer": "L2",
                "exposure": "read",
                "effect": "read",
                "requires_mandate": False,
                "visibility": "model",
                "approval": "auto",
            },
            {
                "name": "l2.dreamos.submit_run",
                "shell": "l2.dreamos.mcp",
                "layer": "L2",
                "exposure": "control",
                "effect": "write",
                "requires_mandate": True,
                "visibility": "model",
                "approval": "human",
            },
        ],
        "denied_tools": ["l2.debate.trigger_live"],
    }


def _base_span() -> Dict[str, Any]:
    return {
        "schema_version": "1.0",
        "trace_id": "trace-20261116-001",
        "run_id": "run-20261116-001",
        "span_id": "span-compute-1",
        "parent_span_id": None,
        "name": "compute.step",
        "segment": "compute",
        "started_at": "2026-11-16T10:00:00+08:00",
        "ended_at": "2026-11-16T10:00:01+08:00",
        "model_id": "qwen-max",
        "tokens_in": 120,
        "tokens_out": 80,
        "cost_cu": 1.2,
        "stop_reason": "done",
        "context_hash": "sha256:" + "a" * 64,
        "attrs": {"step": 1},
    }


def _base_plan(mode: str = "self") -> Dict[str, Any]:
    doc: Dict[str, Any] = {
        "schema_version": "1.1",
        "trace_id": "trace-20261116-001",
        "plan_id": "plan-20261116-001",
        "run_id": "run-20261116-001",
        "intent": "修复空候选集路由异常",
        "mode": mode,
        "handoff": None,
        "steps": [
            {
                "index": 1,
                "action": "复现并确认基线失败",
                "tool": "l2.dreamos.get_result",
                "acceptance": ["evidence.repro.fails_on_base=true"],
            }
        ],
        "budget": {"max_steps": 8, "soft_tokens": 12000, "hard_tokens": 20000},
        "validation": {"evaluators": ["45.dev@1.0.0"], "tripwire": ["G-L2-8"]},
        "artifacts": [],
    }
    if mode == "handoff":
        doc["handoff"] = {"target": "agent.dev", "control": "transferred", "return_to": None}
    elif mode == "agents_as_tools":
        doc["handoff"] = {"target": "agent.dev", "control": "retained", "return_to": "agent.main"}
    return doc


def self_test() -> int:
    failures: List[str] = []
    ran: List[str] = []

    def expect_ok(name: str, doc: Dict[str, Any], fn) -> None:
        ran.append(name)
        errs = fn(doc)
        if errs:
            failures.append(f"[{name}] 期望通过但失败: {errs[:2]}")

    def expect_fail(name: str, doc: Dict[str, Any], fn, needle: str) -> None:
        ran.append(name)
        errs = fn(doc)
        if not errs:
            failures.append(f"[{name}] 期望失败但通过")
        elif not any(needle in e for e in errs):
            failures.append(f"[{name}] 失败原因不含 {needle!r}: {errs[:2]}")

    base = _base_ledger()
    expect_ok("正例-完整闭环", base, validate_ledger)

    # v1.1：L1 发现入队（初始 reported→reported 自迁移）
    initial = json.loads(json.dumps(base))
    initial.update(
        {
            "task_id": "fix-20261116-002",
            "state": "reported",
            "history": [
                {"from": "reported", "to": "reported", "at": base["created_at"], "by": "l1_finding"}
            ],
            "attempts": 0,
            "trigger": {
                "source": "l1_finding",
                "resolver": "54.discovery_path",
                "ref": "reports/discovery/20261117-0001",
                "resolved_at": base["created_at"],
            },
            "evidence": {"repro": base["evidence"]["repro"]},
        }
    )
    for key in ("root_cause", "change_ref", "settled", "run_ids"):
        initial.pop(key, None)
    expect_ok("正例-初始入队", initial, validate_ledger)

    # 负例 1：跳步（reported → root_caused）
    skip = copy.deepcopy(base)
    skip["history"] = [skip["history"][0]] + skip["history"][2:]
    skip["history"][0]["to"] = "root_caused"
    skip["history"][0]["from"] = "reported"
    expect_fail("负例1-跳步", skip, validate_ledger, "非法迁移")

    # 负例 2：回归失败却进 settled
    bad_reg = copy.deepcopy(base)
    bad_reg["evidence"]["regression"]["passed"] = False
    bad_reg["evidence"]["regression"]["exit_code"] = 1
    expect_fail("负例2-回归未通过", bad_reg, validate_ledger, "True")

    # 负例 3：settled 缺 process 分流
    missing_split = copy.deepcopy(base)
    del missing_split["settled"]["process"]
    expect_fail("负例3-settled缺process", missing_split, validate_ledger, "process")

    # 负例 4：回归结果由 manual 自填
    manual = copy.deepcopy(base)
    manual["evidence"]["regression"]["runner"] = "manual"
    expect_fail("负例4-自填passed", manual, validate_ledger, "manual")

    # 负例 5：trigger.ref 与 resolver 不匹配（旧的 F-* 命名空间）
    bad_ref = copy.deepcopy(base)
    bad_ref["trigger"]["resolver"] = "48.experiment_id"
    bad_ref["trigger"]["ref"] = "F-2026-xx"
    expect_fail("负例5-ref不可解析", bad_ref, validate_ledger, "不匹配")

    expect_ok("正例-install", _install_request(True), validate_plugin)
    expect_fail("负例6-install无回滚验证", _install_request(False), validate_plugin, "False")

    # ---- 总装线 A0 四契约 ----
    expect_ok("正例-parked停止", _base_stop("parked", "waiting_for_human"), validate_stop_reason)
    expect_fail("负例7-parked缺子因", _base_stop("parked"), validate_stop_reason, "parked_reason")
    bad_done = _base_stop("done")
    bad_done["resumable"] = True
    expect_fail("负例8-done不可续跑", bad_done, validate_stop_reason, "False")
    no_ctx = _base_stop("no_next_context")
    no_ctx["resumable"] = True
    expect_fail("负例18-无下一上下文不可续跑", no_ctx, validate_stop_reason, "False")
    no_trace = _base_stop("done")
    no_trace.pop("trace_id")
    expect_fail("负例19-停止原因缺trace_id", no_trace, validate_stop_reason, "trace_id")

    expect_ok("正例-工具集快照", _base_tool_set(), validate_tool_set)
    bad_tool = _base_tool_set()
    bad_tool["tools"][1]["effect"] = "trade"
    bad_tool["tools"][1]["approval"] = "auto"
    expect_fail("负例9-交易工具自动放行", bad_tool, validate_tool_set, "auto")
    dup_tool = _base_tool_set()
    dup_tool["tools"].append(copy.deepcopy(dup_tool["tools"][0]))
    expect_fail("负例10-工具名重复", dup_tool, validate_tool_set, "重复")
    no_mandate = _base_tool_set()
    no_mandate["tools"][1].update(
        {"effect": "trade", "approval": "human", "requires_mandate": False}
    )
    expect_fail("负例16-交易无Mandate", no_mandate, validate_tool_set, "True")
    bad_time = _base_tool_set()
    bad_time["generated_at"] = "not-a-date"
    expect_fail("负例17-生成时间非法", bad_time, validate_tool_set, "generated_at")

    expect_ok("正例-span", _base_span(), validate_span)
    bad_span = _base_span()
    bad_span["ended_at"] = "2026-11-16T09:59:59+08:00"
    expect_fail("负例11-结束早于开始", bad_span, validate_span, "早于")
    no_model = _base_span()
    no_model["model_id"] = "none"
    no_model["tokens_in"] = 10
    expect_fail("负例12-无模型却有token", no_model, validate_span, "0")

    expect_ok("正例-Plan(self)", _base_plan("self"), validate_plan)
    expect_ok("正例-Plan(handoff)", _base_plan("handoff"), validate_plan)
    expect_ok("正例-Plan(agents_as_tools)", _base_plan("agents_as_tools"), validate_plan)
    bad_handoff = _base_plan("handoff")
    bad_handoff["handoff"]["control"] = "retained"
    expect_fail("负例13-handoff未交权", bad_handoff, validate_plan, "transferred")
    bad_budget = _base_plan("self")
    bad_budget["budget"]["soft_tokens"] = 30000
    expect_fail("负例14-软预算超硬预算", bad_budget, validate_plan, "soft_tokens")
    bad_steps = _base_plan("self")
    bad_steps["steps"].append(copy.deepcopy(bad_steps["steps"][0]))
    expect_fail("负例15-步骤序号不连续", bad_steps, validate_plan, "steps.index")
    no_trace_plan = _base_plan("self")
    no_trace_plan.pop("trace_id")
    expect_fail("负例20-Plan缺trace_id", no_trace_plan, validate_plan, "trace_id")

    total = len(ran)
    if failures:
        print(f"SELF-TEST FAILED ({len(failures)}/{total})")
        for f in failures:
            print(" -", f)
        return 1
    print(f"SELF-TEST PASSED ({total}/{total})")
    return 0


def _iter_docs(path: Path):
    text = path.read_text(encoding="utf-8")
    if path.suffix == ".jsonl":
        for lineno, line in enumerate(text.splitlines(), 1):
            if line.strip():
                yield lineno, json.loads(line)
    else:
        yield 1, json.loads(text)


def main() -> int:
    ap = argparse.ArgumentParser(description="56-L2 契约校验器")
    ap.add_argument("--self-test", action="store_true", help="跑全量自检（台账/插件/总装线四契约）")
    ap.add_argument("--ledger", type=Path, help="台账 json/jsonl 路径")
    ap.add_argument("--plugin", type=Path, help="插件契约 json 路径")
    ap.add_argument("--stop-reason", type=Path, help="停止原因契约 json 路径")
    ap.add_argument("--tool-set", type=Path, help="工具集快照 json 路径")
    ap.add_argument("--span", type=Path, help="span 契约 json 路径")
    ap.add_argument("--plan", type=Path, help="Plan/Handoff 契约 json 路径")
    args = ap.parse_args()

    if args.self_test:
        return self_test()

    targets = [
        (args.ledger, validate_ledger),
        (args.plugin, validate_plugin),
        (args.stop_reason, validate_stop_reason),
        (args.tool_set, validate_tool_set),
        (args.span, validate_span),
        (args.plan, validate_plan),
    ]
    if not any(path for path, _ in targets):
        ap.print_help()
        return 2

    failed = 0
    for path, fn in targets:
        if not path:
            continue
        for lineno, doc in _iter_docs(path):
            errs = fn(doc)
            for e in errs:
                print(f"{path}:{lineno}: {e}")
            failed += len(errs)

    if failed:
        print(f"FAILED: {failed} violation(s)")
        return 1
    print("OK: 0 violation")
    return 0


if __name__ == "__main__":
    sys.exit(main())
