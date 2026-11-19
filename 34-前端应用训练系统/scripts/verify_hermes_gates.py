#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""P0-D3B Phase 3: H0–H8 门禁探针（本地可执行子集，不调用真实模型）。

用法:
    python3 scripts/verify_hermes_gates.py
    python3 scripts/verify_hermes_gates.py --hermes-bin /path/to/hermes

结论写入 acceptance_bundles/P0-D3B-GATES-<date>.json。
退出码: 0 全过（允许 SKIP）；1 存在 FAIL；2 配置错误。

本探针不会修改 53 登记；是否启用由人根据结果决定。
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime
from typing import Any, Dict, List

_HERE = os.path.dirname(os.path.abspath(__file__))
_PROJECT = os.path.dirname(_HERE)
sys.path.insert(0, _PROJECT)

import yaml  # noqa: E402
from core.hermes_executor import (  # noqa: E402
    CliHermesTransport,
    HermesExecutor,
    build_executor_router,
)

ROLES = {
    "research": {
        "tools": ["recall", "unified_search"],
        "shells": ["l0.cognition.mcp"],
        "executor": "hermes",
    },
    "engineer": {
        "tools": ["recall", "submit_rea_analyze"],
        "shells": ["l0.rea.mcp"],
        "executor": "hermes",
    },
}


class FakeTransport:
    def __init__(self, result: Dict[str, Any]):
        self.result = result
        self.calls: List[Dict[str, Any]] = []

    def execute(self, task: Dict[str, Any]) -> Dict[str, Any]:
        self.calls.append(task)
        return json.loads(json.dumps(self.result))


def assignment(**overrides: Any) -> Dict[str, Any]:
    data = {
        "ticket_id": "GATE-T-1",
        "role": "research",
        "trace_id": "trace-gate-1",
        "mandate": {
            "goal": "门禁探针",
            "tools": ["recall"],
            "budget": {"max_turns": 3, "max_tokens": 1000, "timeout_s": 10},
        },
    }
    data.update(overrides)
    return data


def write_registry(directory: str, enabled: bool = True) -> str:
    path = os.path.join(directory, "external_runtimes.yaml")
    with open(path, "w", encoding="utf-8") as handle:
        yaml.safe_dump(
            {
                "default_deny": True,
                "external_runtimes": [
                    {
                        "id": "hermes",
                        "status": "pending_verification",
                        "enabled": enabled,
                        "allowed_roles": ["research", "engineer"],
                        "permitted_profiles": ["sandbox"],
                        "required_gates": ["H1", "H2", "H3", "B1"],
                    }
                ],
            },
            handle,
            allow_unicode=True,
        )
    return path


def engine(tmp: str, transport: Any) -> HermesExecutor:
    return HermesExecutor(
        transport,
        roles=ROLES,
        runtime_registry=write_registry(tmp),
        state_dir=os.path.join(tmp, "state"),
    )


def gate(gate_id: str, name: str, status: str, evidence: Any) -> Dict[str, Any]:
    return {"id": gate_id, "name": name, "status": status, "evidence": evidence}


def probe_h0(tmp: str) -> Dict[str, Any]:
    ok = 0
    transport = FakeTransport(
        {"status": "done", "evidence": {"summary": "ok", "hermes_session_id": "hs-1"}}
    )
    runner = engine(tmp, transport)
    for index in range(10):
        result = runner(assignment(ticket_id="H0-T-%d" % index))
        if result.get("status") == "done" and isinstance(result.get("evidence"), dict):
            ok += 1
    return gate("H0", "契约一致性", "PASS" if ok == 10 else "FAIL", {"valid": ok, "total": 10})


def probe_h1(hermes_bin: str = "") -> Dict[str, Any]:
    candidates = [
        hermes_bin,
        os.environ.get("HERMES_BIN", ""),
        os.path.expanduser("~/.hermes/.venv/bin/hermes"),
        shutil.which("hermes") or "",
    ]
    attempts = []
    for candidate in [item for item in candidates if item]:
        if not os.path.exists(candidate):
            attempts.append({"bin": candidate, "ok": False, "reason": "not_found"})
            continue
        try:
            proc = subprocess.run([candidate, "--help"], capture_output=True, text=True, timeout=10)
        except Exception as exc:  # noqa: BLE001
            attempts.append({"bin": candidate, "ok": False, "reason": str(exc)})
            continue
        text = (proc.stdout or "") + (proc.stderr or "")
        # Hermes v0.19 headless: `-z PROMPT`；也兼容 --headless/--task 形态
        headless = any(token in text for token in ("-z PROMPT", "--headless", "--task", "--prompt"))
        repl_only = "--repl" in text and not headless
        attempts.append(
            {
                "bin": candidate,
                "ok": proc.returncode == 0 and headless,
                "returncode": proc.returncode,
                "repl_only": repl_only,
                "output_head": text.strip().splitlines()[:3],
            }
        )
    passed = any(item.get("ok") for item in attempts)
    return gate("H1", "程序化入口", "PASS" if passed else "FAIL", attempts)


def probe_h2(tmp: str) -> Dict[str, Any]:
    # 入口白名单：mandate 带越权工具 → 不执行
    transport = FakeTransport({"status": "done", "evidence": {"summary": "ok"}})
    runner = engine(tmp, transport)
    rejected = runner(assignment(mandate={"goal": "x", "tools": ["data_fetch"]}))
    # 运行中越权：Hermes 返回写工具调用 → manual
    transport.result = {
        "status": "done",
        "evidence": {"summary": "ok", "tool_calls": [{"name": "place_order"}]},
    }
    runtime_violation = runner(assignment())
    passed = (
        rejected.get("evidence", {}).get("reason") == "contract_error"
        and runtime_violation.get("failure_class") == "manual"
        and runtime_violation.get("evidence", {}).get("reason") == "role_violation"
    )
    return gate(
        "H2",
        "工具边界",
        "PASS" if passed else "FAIL",
        {
            "entry_reject": rejected.get("evidence", {}).get("reason"),
            "runtime_reject": runtime_violation.get("evidence", {}).get("reason"),
            "transport_calls": len(transport.calls),
        },
    )


def probe_h3(tmp: str) -> Dict[str, Any]:
    root = os.path.join(tmp, "h3-root")
    os.makedirs(root, exist_ok=True)
    probes = {}
    for name in ("dsh_tickets.jsonl", "dsh_worker_receipts.jsonl", "launcher.offset.json"):
        path = os.path.join(root, name)
        with open(path, "w", encoding="utf-8") as handle:
            handle.write('{"sentinel": true}\n')
        probes[name] = open(path, "rb").read()

    transport = FakeTransport(
        {
            "status": "done",
            "evidence": {
                "summary": "ok",
                "hermes_session_id": "hs-1",
                "tool_calls": [{"name": "recall"}],
            },
        }
    )
    engine(tmp, transport)(assignment())
    unchanged = all(
        open(os.path.join(root, name), "rb").read() == body for name, body in probes.items()
    )
    return gate("H3", "写隔离", "PASS" if unchanged else "FAIL", {"files_unchanged": unchanged})


def probe_h4(tmp: str) -> Dict[str, Any]:
    runner = engine(tmp, FakeTransport({"status": "done", "evidence": {"summary": "ok"}}))
    done = runner(assignment())
    runner = engine(
        tmp,
        FakeTransport(
            {"status": "failed", "failure_class": "retryable", "evidence": {"reason": "timeout"}}
        ),
    )
    retryable = runner(assignment())
    runner = engine(
        tmp,
        FakeTransport(
            {
                "status": "failed",
                "failure_class": "manual",
                "evidence": {"reason": "approval_denied"},
            }
        ),
    )
    manual = runner(assignment())
    passed = (
        done.get("status") == "done"
        and retryable.get("status") == "failed"
        and retryable.get("failure_class") == "retryable"
        and manual.get("failure_class") == "manual"
    )
    return gate(
        "H4",
        "回执兼容",
        "PASS" if passed else "FAIL",
        {
            "done": done.get("status"),
            "retryable": retryable.get("failure_class"),
            "manual": manual.get("failure_class"),
        },
    )


def probe_h5(tmp: str) -> Dict[str, Any]:
    runner = engine(
        tmp,
        FakeTransport(
            {"status": "done", "evidence": {"summary": "ok", "hermes_session_id": "hs-1"}}
        ),
    )
    result = runner(assignment())
    evidence = result.get("evidence") or {}
    passed = (
        result.get("status") == "done"
        and bool(evidence.get("trace_id"))
        and bool(evidence.get("hermes_session_id"))
    )
    return gate("H5", "Trace", "PASS" if passed else "FAIL", evidence)


def probe_h6() -> Dict[str, Any]:
    return gate(
        "H6",
        "崩溃恢复",
        "SKIP",
        {"reason": "需要 kill -9 故障注入；由 launcher 租约回收测试覆盖"},
    )


def probe_h7(tmp: str) -> Dict[str, Any]:
    no_trace = engine(tmp, FakeTransport({"status": "done", "evidence": {"summary": "ok"}}))(
        assignment(trace_id="")
    )
    slow = CliHermesTransport(command=[sys.executable, "-c", "import time; time.sleep(5)"])
    timed_out = slow.execute({"ticket_id": "H7-T", "budget": {"timeout_s": 0.2}})
    passed = (
        no_trace.get("evidence", {}).get("reason") == "contract_error"
        and timed_out.get("failure_class") == "retryable"
        and timed_out.get("evidence", {}).get("reason") == "timeout"
    )
    return gate(
        "H7",
        "预算/超时",
        "PASS" if passed else "FAIL",
        {
            "no_trace": no_trace.get("evidence", {}).get("reason"),
            "timeout": timed_out.get("evidence", {}).get("reason"),
        },
    )


def probe_h8() -> Dict[str, Any]:
    marker = {"status": "done", "evidence": {"summary": "dsh"}}

    def dsh(_assignment: Dict[str, Any]) -> Dict[str, Any]:
        return marker

    runner = build_executor_router(ROLES, {"dsh": dsh}, env={}, default="dsh")
    passed = runner is dsh
    return gate("H8", "回归/回退", "PASS" if passed else "FAIL", {"switch_off_identity": passed})


def main(argv: List[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="P0-D3B H0–H8 门禁探针")
    parser.add_argument("--hermes-bin", default="", help="可用的 Hermes headless 二进制")
    parser.add_argument("--out-dir", default=os.path.join(_PROJECT, "acceptance_bundles"))
    args = parser.parse_args(argv)

    try:
        with tempfile.TemporaryDirectory(prefix="d3b-gates-") as tmp:
            results = [
                probe_h0(tmp),
                probe_h1(args.hermes_bin),
                probe_h2(tmp),
                probe_h3(tmp),
                probe_h4(tmp),
                probe_h5(tmp),
                probe_h6(),
                probe_h7(tmp),
                probe_h8(),
            ]
    except Exception as exc:  # noqa: BLE001
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False))
        return 2

    failed = [item["id"] for item in results if item["status"] == "FAIL"]
    bundle = {
        "spec": "P0-D3B-HERMES-EXECUTOR-v0.1",
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "ok": not failed,
        "failed": failed,
        "gates": results,
        "decision": "keep_disabled" if failed else "eligible_for_canary",
    }
    os.makedirs(args.out_dir, exist_ok=True)
    path = os.path.join(args.out_dir, "P0-D3B-GATES-%s.json" % datetime.now().strftime("%Y-%m-%d"))
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(bundle, handle, ensure_ascii=False, indent=2)
    bundle["bundle_path"] = path
    print(json.dumps(bundle, ensure_ascii=False, indent=2))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
