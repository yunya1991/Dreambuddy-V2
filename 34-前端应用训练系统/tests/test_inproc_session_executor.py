# -*- coding: utf-8 -*-
"""W4 方案 B：单运行时多会话执行器单测。

不启动真实 DSH：用假 Popen 验证契约（一次进程、批次输入/输出、失败映射）。
真实多会话实跑见 tools/dsh_session_host + PROPOSAL-P0-D3 §4.15。
"""

import json
import os
import subprocess
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from core.inproc_session_executor import InProcessSessionExecutor  # noqa: E402

_PATCH = "/tmp/host.patch.yml"


class _FakeProc:
    def __init__(self, cmd, env, on_run):
        self.pid = 4321
        self._env = env
        self._on_run = on_run
        self.killed = False

    def communicate(self, timeout=None):
        self._on_run(self._env)
        return ("", "")

    def kill(self):
        self.killed = True


class _TimeoutProc(_FakeProc):
    def __init__(self, cmd, env, on_run):
        super().__init__(cmd, env, on_run)
        self._raised = False

    def communicate(self, timeout=None):
        if not self._raised:
            self._raised = True
            raise subprocess.TimeoutExpired(cmd="dsh", timeout=timeout)
        return ("", "")


def _root(tmp_path):
    (tmp_path / "34-前端应用训练系统").mkdir(parents=True, exist_ok=True)
    return str(tmp_path)


def _executor(tmp_path, popen, **kw):
    kw.setdefault("patches", [_PATCH])
    kw.setdefault("install_plugins", False)
    return InProcessSessionExecutor(root=_root(tmp_path), popen=popen, **kw)


def _assignment(ticket_id, goal=None, **over):
    rec = {
        "ticket_id": ticket_id,
        "role": "research",
        "mandate": {"goal": goal or ticket_id},
    }
    rec.update(over)
    return rec


def _popen_factory(payload=None, proc_cls=_FakeProc):
    calls = []

    def factory(cmd, **kwargs):
        env = kwargs["env"]
        record = {"cmd": cmd, "env": env, "tasks": None}

        def on_run(run_env):
            in_path = run_env["D3_BATCH_INPUT"]
            if os.path.exists(in_path):
                with open(in_path, encoding="utf-8") as handle:
                    record["tasks"] = json.load(handle)
            if payload is not None:
                with open(run_env["D3_BATCH_OUTPUT"], "w", encoding="utf-8") as handle:
                    json.dump(payload, handle)

        record["proc"] = proc_cls(cmd, env, on_run)
        calls.append(record)
        return record["proc"]

    factory.calls = calls
    return factory


def test_one_process_for_whole_batch(tmp_path):
    payload = {
        "TK-A": {
            "status": "done",
            "ok": True,
            "evidence": {"summary": "child-a done"},
            "pid": 777,
            "session_id": "sess-a",
            "duration_ms": 12,
        },
        "TK-B": {
            "status": "failed",
            "ok": False,
            "failure_class": "retryable",
            "evidence": {"summary": "boom", "reason": "tool_error"},
            "pid": 777,
            "session_id": "sess-b",
        },
    }
    factory = _popen_factory(payload)
    executor = _executor(tmp_path, factory)

    results = executor.run_batch([_assignment("TK-A"), _assignment("TK-B", goal="B 目标")])

    assert len(factory.calls) == 1  # 关键：两个 assignment 只起一个运行时
    call = factory.calls[0]
    assert call["cmd"] == ["dsh", "--profile", "sandbox", "--patch", _PATCH, "D3-HOST"]
    assert call["env"]["D3_HOST_MAX"] == "8"
    assert [t["ticket_id"] for t in call["tasks"]] == ["TK-A", "TK-B"]
    assert call["tasks"][1]["goal"] == "B 目标"

    assert results["TK-A"]["status"] == "done"
    assert results["TK-A"]["evidence"]["pid"] == 777
    assert results["TK-A"]["evidence"]["session_id"] == "sess-a"
    assert results["TK-B"]["status"] == "failed"
    assert results["TK-B"]["failure_class"] == "retryable"
    assert results["TK-B"]["evidence"]["reason"] == "tool_error"


def test_missing_output_is_retryable(tmp_path):
    factory = _popen_factory(None)
    executor = _executor(tmp_path, factory)
    results = executor.run_batch([_assignment("TK-A")])
    assert results["TK-A"]["status"] == "failed"
    assert results["TK-A"]["failure_class"] == "retryable"
    assert "no output" in results["TK-A"]["evidence"]["summary"]


def test_host_timeout_kills_process(tmp_path):
    factory = _popen_factory(None, proc_cls=_TimeoutProc)
    executor = _executor(tmp_path, factory, timeout=1.0)
    results = executor.run_batch([_assignment("TK-A")])
    assert results["TK-A"]["failure_class"] == "timeout"
    assert factory.calls[0]["proc"].killed is True


def test_host_error_payload_is_retryable(tmp_path):
    factory = _popen_factory({"__host_error__": "create root agent failed"})
    executor = _executor(tmp_path, factory)
    results = executor.run_batch([_assignment("TK-A"), _assignment("TK-B")])
    for ticket_id in ("TK-A", "TK-B"):
        assert results[ticket_id]["failure_class"] == "retryable"
        assert "root agent" in results[ticket_id]["evidence"]["summary"]


def test_call_compat_single_assignment(tmp_path):
    payload = {"TK-A": {"status": "done", "evidence": {"summary": "ok"}, "pid": 1}}
    factory = _popen_factory(payload)
    executor = _executor(tmp_path, factory)
    result = executor(_assignment("TK-A"))
    assert result["status"] == "done"
    assert result["evidence"]["duration_ms"] >= 0
