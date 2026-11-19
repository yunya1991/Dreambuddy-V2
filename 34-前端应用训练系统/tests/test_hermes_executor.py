# -*- coding: utf-8 -*-
"""P0-D3B Phase 3: HermesExecutor / 角色路由 / 53 登记校验。"""

import os
import sys

import yaml

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from core.hermes_executor import (  # noqa: E402
    CliHermesTransport,
    ExecutorRouter,
    HermesExecutor,
    build_executor_router,
    runtime_entry,
)
from core.worker_roles import RolePolicy  # noqa: E402

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
    "verifier": {
        "tools": ["recall"],
        "shells": ["l0.eval.mcp"],
        "executor": "dsh",
    },
}


class FakeTransport:
    def __init__(self, result=None):
        self.calls = []
        self.result = result or {
            "status": "done",
            "evidence": {"summary": "ok", "hermes_session_id": "hs-1"},
        }

    def execute(self, task):
        self.calls.append(task)
        return dict(self.result)


def write_registry(
    tmp_path, *, enabled=True, roles=("research", "engineer"), profiles=("sandbox",)
):
    path = tmp_path / "external_runtimes.yaml"
    path.write_text(
        yaml.safe_dump(
            {
                "default_deny": True,
                "external_runtimes": [
                    {
                        "id": "hermes",
                        "status": "pending_verification",
                        "enabled": enabled,
                        "allowed_roles": list(roles),
                        "permitted_profiles": list(profiles),
                        "required_gates": ["H1", "H2", "H3", "B1"],
                    }
                ],
            },
            allow_unicode=True,
        ),
        encoding="utf-8",
    )
    return str(path)


def assignment(**overrides):
    data = {
        "ticket_id": "T-1",
        "role": "research",
        "trace_id": "tr-1",
        "mandate": {
            "goal": "分析一下",
            "tools": ["recall"],
            "budget": {"max_turns": 3, "max_tokens": 1000, "timeout_s": 30},
        },
    }
    data.update(overrides)
    return data


def executor(tmp_path, transport=None, *, enabled=True, roles=("research", "engineer")):
    return HermesExecutor(
        transport or FakeTransport(),
        roles=ROLES,
        runtime_registry=write_registry(tmp_path, enabled=enabled, roles=roles),
        state_dir=str(tmp_path / "state"),
    )


def test_disabled_runtime_fails_closed_and_does_not_execute(tmp_path):
    transport = FakeTransport()
    result = executor(tmp_path, transport, enabled=False)(assignment())
    assert result["status"] == "failed"
    assert result["failure_class"] == "manual"
    assert result["evidence"]["reason"] == "runtime_disabled"
    assert transport.calls == []


def test_unknown_role_is_rejected_before_runtime(tmp_path):
    transport = FakeTransport()
    result = executor(tmp_path, transport)(assignment(role="trading"))
    assert result["status"] == "failed"
    assert result["evidence"]["reason"] == "contract_error"
    assert transport.calls == []


def test_missing_trace_and_goal_and_tools_are_contract_errors(tmp_path):
    engine = executor(tmp_path)
    assert engine(assignment(trace_id=""))["evidence"]["reason"] == "contract_error"
    assert (
        engine(assignment(mandate={"goal": "", "tools": ["recall"]}))["evidence"]["reason"]
        == "contract_error"
    )
    assert (
        engine(assignment(mandate={"goal": "x", "tools": []}))["evidence"]["reason"]
        == "contract_error"
    )


def test_tool_outside_role_and_write_tool_are_rejected(tmp_path):
    engine = executor(tmp_path)
    outside = engine(assignment(mandate={"goal": "x", "tools": ["data_fetch"]}))
    assert outside["evidence"]["reason"] == "contract_error"
    write = engine(assignment(mandate={"goal": "x", "tools": ["place_order"]}))
    assert write["evidence"]["reason"] == "contract_error"


def test_done_result_is_normalized_and_session_is_idempotent(tmp_path):
    transport = FakeTransport()
    engine = executor(tmp_path, transport, enabled=True)

    first = engine(assignment())
    assert first["status"] == "done"
    assert first["evidence"]["executor"] == "hermes"
    assert first["evidence"]["trace_id"] == "tr-1"
    assert "duration_ms" in first["evidence"]
    assert transport.calls[0]["session_id"] == ""

    second = engine(assignment())
    assert second["status"] == "done"
    assert transport.calls[1]["session_id"] == "hs-1"


def test_runtime_tool_call_violation_becomes_manual_failure(tmp_path):
    transport = FakeTransport(
        {
            "status": "done",
            "evidence": {
                "summary": "ok",
                "tool_calls": [{"name": "recall"}, {"name": "place_order"}],
            },
        }
    )
    result = executor(tmp_path, transport)(assignment())
    assert result["status"] == "failed"
    assert result["failure_class"] == "manual"
    assert result["evidence"]["reason"] == "role_violation"


def test_transport_exception_is_retryable(tmp_path):
    class Boom:
        def execute(self, _task):
            raise TimeoutError("boom")

    result = executor(tmp_path, Boom())(assignment())
    assert result["status"] == "failed"
    assert result["failure_class"] == "retryable"
    assert result["evidence"]["reason"] == "runtime_error"


def test_evidence_is_capped(tmp_path):
    transport = FakeTransport(
        {"status": "done", "evidence": {"summary": "x" * 100000, "tool_calls": []}}
    )
    engine = HermesExecutor(
        transport,
        roles=ROLES,
        runtime_registry=write_registry(tmp_path),
        state_dir=str(tmp_path / "state"),
        max_evidence_bytes=1024,
    )
    result = engine(assignment())
    assert result["status"] == "done"
    assert len(result["evidence"]["summary"]) <= 2000
    import json

    assert len(json.dumps(result["evidence"], ensure_ascii=False).encode("utf-8")) <= 1024


def test_executor_does_not_write_ticket_receipt_or_offset(tmp_path):
    root = tmp_path / "root"
    root.mkdir()
    sentinels = {}
    for name in ("dsh_tickets.jsonl", "dsh_worker_receipts.jsonl", "launcher.offset.json"):
        path = root / name
        path.write_text('{"sentinel": true}\n', encoding="utf-8")
        sentinels[name] = path.read_bytes()

    transport = FakeTransport()
    assert executor(tmp_path, transport)(assignment())["status"] == "done"
    for name, body in sentinels.items():
        assert (root / name).read_bytes() == body


def test_runtime_entry_reads_registry(tmp_path):
    path = write_registry(tmp_path, enabled=True)
    entry = runtime_entry("hermes", path)
    assert entry["enabled"] is True
    assert entry["allowed_roles"] == ["research", "engineer"]


# ── ExecutorRouter / build_executor_router ──────────────────────────────
def _stub(name, calls):
    def run(_assignment):
        calls.append(name)
        return {"status": "done", "evidence": {"summary": name}}

    return run


def test_router_dispatches_by_role_and_canary():
    calls = []
    router = ExecutorRouter(
        {"dsh": _stub("dsh", calls), "hermes": _stub("hermes", calls)},
        role_executors={"research": "hermes"},
        default="dsh",
        canary_pct=100,
    )
    router(assignment(role="research", ticket_id="T-1"))
    router(assignment(role="verifier", ticket_id="T-2"))
    assert calls == ["hermes", "dsh"]

    calls.clear()
    router.canary_pct = 0
    router(assignment(role="research", ticket_id="T-3"))
    assert calls == ["dsh"]


def test_canary_distribution_is_approximately_uniform():
    calls = []
    router = ExecutorRouter(
        {"dsh": _stub("dsh", calls), "hermes": _stub("hermes", calls)},
        role_executors={"research": "hermes"},
        default="dsh",
        canary_pct=50,
    )
    for index in range(1000):
        router(assignment(role="research", ticket_id="T-%d" % index))
    hermes = calls.count("hermes")
    assert 450 <= hermes <= 550, hermes


def test_build_router_is_disabled_by_default():
    calls = []
    executors = {"dsh": _stub("dsh", calls), "hermes": _stub("hermes", calls)}
    router = build_executor_router(ROLES, executors, env={}, default="dsh")
    router(assignment(role="research"))
    assert calls == ["dsh"]

    calls.clear()
    routed = build_executor_router(
        ROLES,
        executors,
        env={
            "enable_hermes_executor": "1",
            "hermes_executor_roles": "research",
            "hermes_executor_canary_pct": "100",
        },
        default="dsh",
    )
    routed(assignment(role="research"))
    assert calls == ["hermes"]
    routed(assignment(role="engineer"))
    assert calls == ["hermes", "dsh"]


# ── 53 登记 / 花名册校验 ────────────────────────────────────────────────
def test_worker_roles_validate_executor_against_53(tmp_path):
    bad_roles = {
        "research": {"tools": ["recall"], "shells": ["s"], "executor": "hermes"},
        "weird": {"tools": ["recall"], "shells": ["s"], "executor": "nope"},
    }
    problems = RolePolicy(bad_roles).validate(write_registry(tmp_path, roles=("engineer",)))
    assert any("research: not in hermes allowed_roles" in item for item in problems)
    assert any("weird: unknown executor" in item for item in problems)

    ok = RolePolicy(ROLES).validate(write_registry(tmp_path))
    assert ok == []


# ── CLI transport ──────────────────────────────────────────────────────
def test_cli_transport_parses_json_and_timeout():
    transport = CliHermesTransport(
        command=[
            sys.executable,
            "-c",
            'print(\'{"status":"done","evidence":{"summary":"ok"}}\')',
        ]
    )
    result = transport.execute({"ticket_id": "T-1", "budget": {"timeout_s": 10}})
    assert result["status"] == "done"
    assert result["evidence"]["summary"] == "ok"

    slow = CliHermesTransport(command=[sys.executable, "-c", "import time; time.sleep(5)"])
    timed_out = slow.execute({"ticket_id": "T-2", "budget": {"timeout_s": 0.2}})
    assert timed_out["status"] == "failed"
    assert timed_out["failure_class"] == "retryable"
    assert timed_out["evidence"]["reason"] == "timeout"


def test_default_command_matches_headless_protocol(monkeypatch):
    for name in ("hermes_executor_cmd", "HERMES_EXECUTOR_CMD", "D3_HERMES_BIN"):
        monkeypatch.delenv(name, raising=False)
    assert CliHermesTransport().command == ("hermes", "-z", "{prompt}")

    monkeypatch.setenv("D3_HERMES_BIN", "/opt/hermes")
    assert CliHermesTransport().command == ("/opt/hermes", "-z", "{prompt}")

    monkeypatch.setenv("hermes_executor_cmd", "/opt/hermes -z {prompt} -t mcp")
    assert CliHermesTransport().command == ("/opt/hermes", "-z", "{prompt}", "-t", "mcp")


def test_cli_transport_passes_prompt_and_parses_fenced_json():
    script = (
        "import sys, json;"
        "assert 'TASK JSON' in sys.argv[1], sys.argv[1];"
        "assert 'TK-9' in sys.argv[1];"
        "print('```json');"
        "print(json.dumps({'status': 'done', 'evidence': {'summary': 'fenced'}}));"
        "print('```')"
    )
    transport = CliHermesTransport(command=[sys.executable, "-c", script, "{prompt}"])
    result = transport.execute({"ticket_id": "TK-9", "mandate": {"goal": "g", "tools": ["recall"]}})
    assert result["status"] == "done"
    assert result["evidence"]["summary"] == "fenced"
