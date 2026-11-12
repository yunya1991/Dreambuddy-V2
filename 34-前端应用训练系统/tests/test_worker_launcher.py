# -*- coding: utf-8 -*-
"""W1 单角色 MVP：Worker 拉起器单测。

覆盖 PROPOSAL-P0-D3 §4.5/§4.6（W1 子集）：
  - inbox 增量消费 + offset 持久化（含半行不消费）
  - 已回执 Ticket 跳过（重放防护）
  - 未知 worker_id / 未知 role → failed(manual, role_violation)，不执行
  - executor 正常/异常 → done / failed(manual, runtime_error)
  - 坏行 FAIL-OPEN
  - 端到端：Router 派单 → 拉起器执行 → Router 下一轮 ended
"""

import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from core.router_loop import JsonlInboxSink, run_pass  # noqa: E402
from core.ticket_store import JsonlTicketStore, recover_tickets  # noqa: E402
from core.worker_launcher import WorkerLauncher  # noqa: E402

_FLAGS = {
    "enable_router_loop": True,
    "enable_superagent_router": True,
    "enable_ticket_store": True,
    "enable_worker_pool": True,
}
_ROSTER = {"research": ["w-res-1"]}
_ROLES = {
    "research": {"description": "研究 Worker", "tools": ["recall", "unified_search"]},
}


def _plan(*refs):
    return {
        "draft": True,
        "tickets": [
            {"external_ref": r, "mandate": {"goal": r}, "route_hint": {"role": "research"}}
            for r in refs
        ],
        "dispatch": {"mode": "parallel", "depends_on": {}},
    }


def _inbox(root):
    return os.path.join(str(root), "34-前端应用训练系统", "dsh_worker_inbox.jsonl")


def _receipts(root):
    return os.path.join(str(root), "34-前端应用训练系统", "dsh_worker_receipts.jsonl")


def _append_inbox(root, rec, newline=True):
    path = _inbox(root)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + ("\n" if newline else ""))


def _read_receipts(root):
    path = _receipts(root)
    if not os.path.exists(path):
        return []
    out = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            if line.strip():
                out.append(json.loads(line))
    return out


def _state_dir(root):
    return os.path.join(str(root), "34-前端应用训练系统", ".worker_launcher")


def _read_claims(root):
    path = os.path.join(_state_dir(root), "claims.json")
    if not os.path.exists(path):
        return {}
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _write_claims(root, data):
    os.makedirs(_state_dir(root), exist_ok=True)
    with open(os.path.join(_state_dir(root), "claims.json"), "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)


def _write_offset(root, offset):
    os.makedirs(_state_dir(root), exist_ok=True)
    with open(os.path.join(_state_dir(root), "offset.json"), "w", encoding="utf-8") as f:
        json.dump({"offset": int(offset)}, f)


def _assignment(**over):
    rec = {
        "ticket_id": "TK-R1",
        "external_ref": "R1",
        "worker_id": "w-res-1",
        "role": "research",
        "mandate": {"goal": "R1"},
        "trace_id": "rp-test",
        "assigned_at": 1794498000.0,
    }
    rec.update(over)
    return rec


def _launcher(root, executor, **kw):
    kw.setdefault("worker_ids", {"w-res-1"})
    return WorkerLauncher(root=str(root), roles=_ROLES, executor=executor, **kw)


def test_consume_writes_done_receipt_and_advances_offset(tmp_path):
    calls = []
    _append_inbox(tmp_path, _assignment())
    lc = _launcher(
        tmp_path, lambda a: calls.append(a) or {"status": "done", "evidence": {"summary": "ok"}}
    )

    stats = lc.run_once()

    assert stats["consumed"] == 1 and stats["receipts"] == 1 and stats["skipped"] == 0
    assert len(calls) == 1
    rec = _read_receipts(tmp_path)[0]
    assert rec["ticket_id"] == "TK-R1"
    assert rec["status"] == "done"
    assert rec["failure_class"] is None
    assert rec["attempts"] == 1
    assert rec["worker_id"] == "w-res-1"
    assert rec["trace_id"] == "rp-test"
    assert rec["receipt_id"].startswith("rc-")
    # 第二轮无新行
    assert lc.run_once()["consumed"] == 0


def test_partial_line_is_not_consumed_until_newline(tmp_path):
    calls = []
    lc = _launcher(tmp_path, lambda a: calls.append(a) or {"status": "done"})
    _append_inbox(tmp_path, _assignment(), newline=False)

    assert lc.run_once()["consumed"] == 0
    assert calls == []

    with open(_inbox(tmp_path), "a", encoding="utf-8") as f:
        f.write("\n")
    assert lc.run_once()["consumed"] == 1
    assert len(calls) == 1


def test_bad_json_line_is_skipped_fail_open(tmp_path):
    path = _inbox(tmp_path)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write("this is not json\n")
    _append_inbox(tmp_path, _assignment())
    lc = _launcher(tmp_path, lambda a: {"status": "done"})

    stats = lc.run_once()

    assert stats["bad_lines"] == 1
    assert stats["receipts"] == 1
    assert _read_receipts(tmp_path)[0]["status"] == "done"


def test_already_receipted_ticket_is_skipped(tmp_path):
    calls = []
    _append_inbox(tmp_path, _assignment())
    os.makedirs(os.path.dirname(_receipts(tmp_path)), exist_ok=True)
    with open(_receipts(tmp_path), "w", encoding="utf-8") as f:
        f.write(json.dumps({"ticket_id": "TK-R1", "status": "done"}) + "\n")
    lc = _launcher(tmp_path, lambda a: calls.append(a) or {"status": "done"})

    stats = lc.run_once()

    assert stats["consumed"] == 1 and stats["skipped"] == 1 and stats["receipts"] == 0
    assert calls == []


def test_unknown_worker_id_is_rejected_without_execute(tmp_path):
    calls = []
    _append_inbox(tmp_path, _assignment(worker_id="w-other"))
    lc = _launcher(tmp_path, lambda a: calls.append(a) or {"status": "done"})

    lc.run_once()

    rec = _read_receipts(tmp_path)[0]
    assert rec["status"] == "failed"
    assert rec["failure_class"] == "manual"
    assert rec["evidence"]["reason"] == "role_violation"
    assert calls == []


def test_unknown_role_is_rejected_without_execute(tmp_path):
    calls = []
    _append_inbox(tmp_path, _assignment(role="verifier"))
    lc = _launcher(tmp_path, lambda a: calls.append(a) or {"status": "done"})

    lc.run_once()

    rec = _read_receipts(tmp_path)[0]
    assert rec["failure_class"] == "manual"
    assert rec["evidence"]["reason"] == "role_violation"
    assert calls == []


def test_executor_exception_retries_then_exhausts(tmp_path):
    """W2：工具异常 = retryable，中间重试不写回执，第 3 次写终态 manual。"""
    calls = []

    def boom(_a):
        calls.append(1)
        raise RuntimeError("tool exploded")

    _append_inbox(tmp_path, _assignment())
    lc = _launcher(tmp_path, boom, backoff=(0, 0, 0), jitter_ratio=0)

    first = lc.run_once()
    assert first["retried"] == 1 and first["receipts"] == 0
    lc.run_once()
    third = lc.run_once()

    assert len(calls) == 3
    assert third["failed"] == 1
    recs = _read_receipts(tmp_path)
    assert len(recs) == 1  # 只有终态回执
    assert recs[0]["status"] == "failed"
    assert recs[0]["failure_class"] == "manual"
    assert recs[0]["evidence"]["reason"] == "runtime_error"
    assert recs[0]["attempts"] == 3
    assert "tool exploded" in recs[0]["evidence"]["summary"]


def test_executor_retryable_is_escalated_after_max_attempts(tmp_path):
    _append_inbox(tmp_path, _assignment())
    lc = _launcher(
        tmp_path,
        lambda a: {
            "status": "failed",
            "failure_class": "retryable",
            "evidence": {"reason": "tool_error"},
        },
        backoff=(0, 0, 0),
        jitter_ratio=0,
    )

    lc.run_once()
    lc.run_once()
    lc.run_once()

    rec = _read_receipts(tmp_path)[0]
    assert rec["failure_class"] == "manual"
    assert rec["evidence"]["reason"] == "tool_error"
    assert rec["attempts"] == 3


def test_manual_failure_does_not_retry(tmp_path):
    calls = []
    _append_inbox(tmp_path, _assignment())
    lc = _launcher(
        tmp_path,
        lambda a: calls.append(a)
        or {
            "status": "failed",
            "failure_class": "manual",
            "evidence": {"reason": "role_violation"},
        },
    )

    lc.run_once()
    lc.run_once()

    assert len(calls) == 1
    assert len(_read_receipts(tmp_path)) == 1


def test_backoff_is_exponential_without_jitter(tmp_path):
    _append_inbox(tmp_path, _assignment())
    lc = _launcher(
        tmp_path,
        lambda a: {
            "status": "failed",
            "failure_class": "retryable",
            "evidence": {"reason": "tool_error"},
        },
        jitter_ratio=0,
    )

    lc.run_once(now=1000.0)
    claims = _read_claims(tmp_path)
    assert claims["TK-R1"]["next_retry_at"] == 1005.0  # 5s

    lc.run_once(now=1006.0)
    assert _read_claims(tmp_path)["TK-R1"]["next_retry_at"] == 1026.0  # 1006+20

    lc.run_once(now=1030.0)
    assert _read_claims(tmp_path) == {}  # 第 3 次耗尽 → 移除
    assert _read_receipts(tmp_path)[0]["attempts"] == 3


def test_task_timeout_retries_then_exhausts(tmp_path):
    def slow(_a):
        import time

        time.sleep(0.2)
        return {"status": "done"}

    _append_inbox(tmp_path, _assignment())
    lc = _launcher(tmp_path, slow, task_timeout=0.03, backoff=(0, 0, 0), jitter_ratio=0)

    lc.run_once()
    lc.run_once()
    stats = lc.run_once()

    assert stats["timeouts"] == 1
    rec = _read_receipts(tmp_path)[0]
    assert rec["status"] == "failed"
    assert rec["failure_class"] == "manual"
    assert rec["evidence"]["reason"] == "timeout"
    assert rec["attempts"] == 3


def test_expired_lease_is_recovered_and_retried(tmp_path):
    """kill -9 / 心跳丢失：租约过期 → 回收，attempt 续接后完成。"""
    _append_inbox(tmp_path, _assignment())
    # 模拟崩溃现场：inbox 已消费、claim 处于 running 且租约过期
    _write_offset(tmp_path, os.path.getsize(_inbox(tmp_path)))
    _write_claims(
        tmp_path,
        {
            "TK-R1": {
                "ticket_id": "TK-R1",
                "assignment": _assignment(),
                "attempt": 1,
                "state": "running",
                "first_started_at": 1794498000.0,
                "next_retry_at": 1794498000.0,
                "lease_until": 0,
            }
        },
    )
    lc = _launcher(tmp_path, lambda a: {"status": "done"})

    stats = lc.run_once(now=1794499000.0)

    assert stats["recovered"] == 1
    assert stats["receipts"] == 1
    assert _read_receipts(tmp_path)[0]["attempts"] == 2
    assert _read_claims(tmp_path) == {}


def test_max_task_duration_blocks_further_retry(tmp_path):
    _append_inbox(tmp_path, _assignment())
    calls = []
    _write_offset(tmp_path, os.path.getsize(_inbox(tmp_path)))
    _write_claims(
        tmp_path,
        {
            "TK-R1": {
                "ticket_id": "TK-R1",
                "assignment": _assignment(),
                "attempt": 1,
                "state": "retry_pending",
                "first_started_at": 1000.0,
                "next_retry_at": 1000.0,
                "lease_until": None,
            }
        },
    )
    lc = _launcher(
        tmp_path, lambda a: calls.append(a) or {"status": "done"}, max_task_duration=60.0
    )

    lc.run_once(now=1100.0)  # 已超 60s 硬上限

    assert calls == []
    rec = _read_receipts(tmp_path)[0]
    assert rec["failure_class"] == "manual"
    assert rec["evidence"]["reason"] == "timeout"
    assert _read_claims(tmp_path) == {}


def test_truncated_inbox_resets_offset(tmp_path):
    _append_inbox(tmp_path, _assignment(ticket_id="TK-R1"))
    lc = _launcher(tmp_path, lambda a: {"status": "done"})
    lc.run_once()
    # 人工清空/轮转文件
    with open(_inbox(tmp_path), "w", encoding="utf-8"):
        pass
    _append_inbox(tmp_path, _assignment(ticket_id="TK-R2"))

    stats = lc.run_once()

    assert stats["consumed"] == 1
    assert {r["ticket_id"] for r in _read_receipts(tmp_path)} == {"TK-R1", "TK-R2"}


def test_requested_tools_outside_role_are_rejected(tmp_path):
    """W3：请求 propose 工具越权 → role_violation，executor 零调用。"""
    calls = []
    _append_inbox(tmp_path, _assignment(mandate={"goal": "R1", "tools": ["eval_analyze"]}))
    lc = _launcher(tmp_path, lambda a: calls.append(a) or {"status": "done"})

    lc.run_once()

    rec = _read_receipts(tmp_path)[0]
    assert rec["failure_class"] == "manual"
    assert rec["evidence"]["reason"] == "role_violation"
    assert "eval_analyze" in rec["evidence"]["summary"]
    assert calls == []


def test_requested_tools_inside_role_execute(tmp_path):
    calls = []
    _append_inbox(tmp_path, _assignment(tools=["recall", "unified_search"]))
    lc = _launcher(tmp_path, lambda a: calls.append(a) or {"status": "done"})

    lc.run_once()

    assert len(calls) == 1
    assert _read_receipts(tmp_path)[0]["status"] == "done"


def test_router_end_to_end_reaches_ended(tmp_path):
    """W1 退出条件：1 任务闭环，Router 下一轮 ended。"""
    store = JsonlTicketStore(root=str(tmp_path))
    sink = JsonlInboxSink(str(tmp_path))

    out1 = run_pass(store, roster=_ROSTER, plan=_plan("R1"), sink=sink, flags=_FLAGS, shadow=False)
    ticket_id = out1["assignments"][0]["ticket_id"]
    assert recover_tickets(store)[ticket_id]["state"] == "live"

    lc = _launcher(tmp_path, lambda a: {"status": "done", "evidence": {"summary": "done"}})
    lc.run_once()
    assert _read_receipts(tmp_path)[0]["ticket_id"] == ticket_id

    out2 = run_pass(store, roster=_ROSTER, plan=_plan("R1"), sink=sink, flags=_FLAGS, shadow=False)
    assert out2["receipts"]["applied"][0]["to"] == "ended"
    assert recover_tickets(store)[ticket_id]["state"] == "ended"
    assert out2["assignments"] == []
