# -*- coding: utf-8 -*-
"""T-DSH-P0 D2a: Router 常驻循环单轮 pass 单测。

覆盖 DESIGN-P0-D2-ROUTER-LOOP v0.1 §8.2:
  A1 开关关断零副作用 / A2 无状态可复现 / A3 幂等 / A4 槽位不抢占 /
  A5 paused 释放槽 / A6 shadow 不写 / A7 FAIL-OPEN / A9 重启可恢复 /
  A10 trace 贯穿。
"""

import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from core.router_loop import JsonlInboxSink, PassStats, run_pass  # noqa: E402
from core.thread_affinity import AffinityTable  # noqa: E402
from core.ticket_state import create_ticket, transition_ticket  # noqa: E402
from core.ticket_store import JsonlTicketStore, recover_tickets, save_ticket  # noqa: E402

_FLAGS = {
    "enable_router_loop": True,
    "enable_superagent_router": True,
    "enable_ticket_store": True,
    "enable_worker_pool": True,
    "enable_thread_affinity": True,
}

_ROSTER = {"research": ["w-res-1"], "engineer": ["w-eng-1"]}


def _plan(*refs, role="research", deps=None, thread_id=None):
    tickets = []
    for ref in refs:
        item = {"external_ref": ref, "mandate": {"goal": ref}, "route_hint": {"role": role}}
        if thread_id:
            item["thread_id"] = thread_id
        tickets.append(item)
    return {
        "draft": True,
        "tickets": tickets,
        "dispatch": {"mode": "parallel", "depends_on": deps or {}},
    }


def _store(tmp_path):
    return JsonlTicketStore(root=str(tmp_path))


def _seed_live(store, ticket_id, ref, worker_id):
    t = create_ticket(ticket_id)
    t["external_ref"] = ref
    t["worker_id"] = worker_id
    save_ticket(t, store)
    return t


def test_disabled_returns_degraded(tmp_path):
    out = run_pass(_store(tmp_path), flags={}, shadow=True)
    assert out["ok"] is False
    assert out["degraded"] is True
    assert out["reason"] == "loop_disabled"


def test_store_flag_required(tmp_path):
    flags = dict(_FLAGS)
    flags.pop("enable_ticket_store")
    out = run_pass(_store(tmp_path), flags=flags)
    assert out["degraded"] is True
    assert out["reason"] == "store_unavailable"


def test_store_none_degraded(tmp_path):
    out = run_pass(None, flags=_FLAGS)
    assert out["degraded"] is True
    assert out["reason"] == "store_unavailable"


def test_shadow_writes_nothing(tmp_path):
    store = _store(tmp_path)
    sink_hits = []
    out = run_pass(
        store,
        roster=_ROSTER,
        plan=_plan("R1"),
        sink=sink_hits.append,
        flags=_FLAGS,
        shadow=True,
    )
    assert out["ok"] is True
    assert out["shadow"] is True
    assert out["materialized"] == []
    assert out["committed"] == 0
    assert len(out["would_assignments"]) == 1
    assert out["would_assignments"][0]["worker_id"] == "w-res-1"
    assert sink_hits == []
    assert not (tmp_path / "34-前端应用训练系统" / "dsh_tickets.jsonl").exists()


def test_commit_persists_and_sinks(tmp_path):
    store = _store(tmp_path)
    sink = JsonlInboxSink(root=str(tmp_path))
    out = run_pass(store, roster=_ROSTER, plan=_plan("R1"), sink=sink, flags=_FLAGS, shadow=False)
    assert out["ok"] is True
    assert out["committed"] == 1
    assert out["materialized"][0]["ticket_id"] == "TK-R1"

    tickets = recover_tickets(store)
    assert tickets["TK-R1"]["worker_id"] == "w-res-1"
    assert tickets["TK-R1"]["state"] == "live"
    assert tickets["TK-R1"]["trace_id"] == out["pass_id"]  # A10 trace 贯穿
    assert out["assignments"][0]["trace_id"] == out["pass_id"]

    inbox = tmp_path / "34-前端应用训练系统" / "dsh_worker_inbox.jsonl"
    assert inbox.exists()
    assert "TK-R1" in inbox.read_text(encoding="utf-8")


def test_idempotent_already_live(tmp_path):
    store = _store(tmp_path)
    first = run_pass(store, roster=_ROSTER, plan=_plan("R1"), flags=_FLAGS, shadow=False)
    assert first["committed"] == 1
    second = run_pass(store, roster=_ROSTER, plan=_plan("R1"), flags=_FLAGS, shadow=False)
    assert second["skipped"] == [{"external_ref": "R1", "reason": "already_live"}]
    assert second["materialized"] == []
    assert len(recover_tickets(store)) == 1


def test_no_free_worker(tmp_path):
    store = _store(tmp_path)
    _seed_live(store, "TK-X1", "X1", "w-res-1")
    out = run_pass(store, roster=_ROSTER, plan=_plan("R2"), flags=_FLAGS, shadow=False)
    assert out["assignments"] == []
    assert out["unassigned"] == [{"external_ref": "R2", "reason": "no_free_worker"}]


def test_unassigned_ticket_redispatched_next_pass(tmp_path):
    """物化后被槽位闸挡住的 ticket 必须能在后续轮补派，不得被 already_live 永久锁死(R13)。"""
    store = _store(tmp_path)
    first = run_pass(store, roster={}, plan=_plan("R1"), flags=_FLAGS, shadow=False)
    assert first["assignments"] == []
    assert first["unassigned"] == [{"external_ref": "R1", "reason": "no_free_worker"}]
    assert not recover_tickets(store)["TK-R1"].get("worker_id")

    second = run_pass(store, roster=_ROSTER, plan=_plan("R1"), flags=_FLAGS, shadow=False)
    assert second["skipped"] == []
    assert second["committed"] == 1
    assert second["assignments"][0]["worker_id"] == "w-res-1"
    assert recover_tickets(store)["TK-R1"]["worker_id"] == "w-res-1"


def test_paused_releases_slot(tmp_path):
    store = _store(tmp_path)
    live = _seed_live(store, "TK-X1", "X1", "w-res-1")
    paused = transition_ticket(live, "paused", paused_reason="waiting_event")
    save_ticket(paused, store)

    out = run_pass(store, roster=_ROSTER, plan=_plan("R2"), flags=_FLAGS, shadow=False)
    assert len(out["assignments"]) == 1
    assert out["assignments"][0]["worker_id"] == "w-res-1"


def test_dependency_deferred(tmp_path):
    store = _store(tmp_path)
    plan = _plan("R1", "R2", deps={"R2": ["R1"]})
    out = run_pass(store, roster=_ROSTER, plan=plan, flags=_FLAGS, shadow=False)
    assigned_refs = {a["external_ref"] for a in out["assignments"]}
    assert assigned_refs == {"R1"}
    assert out["deferred"] == [{"external_ref": "R2", "reason": "dependency_unmet"}]


def test_dependency_completed_from_store(tmp_path):
    store = _store(tmp_path)
    done = create_ticket("TK-R1")
    done["external_ref"] = "R1"
    done = transition_ticket(done, "ended")
    save_ticket(done, store)

    out = run_pass(
        store,
        roster=_ROSTER,
        plan=_plan("R1", "R2", deps={"R2": ["R1"]}),
        flags=_FLAGS,
        shadow=False,
    )
    # R1 已是 ended → 幂等闸跳过;R2 依赖 R1(已完成) → 可派
    assert out["skipped"] == [{"external_ref": "R1", "reason": "already_ended"}]
    assert [a["external_ref"] for a in out["assignments"]] == ["R2"]


def test_dependency_held_across_rounds_until_receipt(tmp_path):
    """依赖票已派但未 ended 时，下游不得因它被移出本批而提前放行(R15)。"""
    store = _store(tmp_path)
    plan = _plan("R1", "R2", deps={"R2": ["R1"]})
    first = run_pass(store, roster=_ROSTER, plan=plan, flags=_FLAGS, shadow=False)
    assert [a["external_ref"] for a in first["assignments"]] == ["R1"]

    second = run_pass(store, roster=_ROSTER, plan=plan, flags=_FLAGS, shadow=False)
    assert second["skipped"] == [{"external_ref": "R1", "reason": "already_live"}]
    assert second["deferred"] == [{"external_ref": "R2", "reason": "dependency_unmet"}]
    assert second["assignments"] == []

    _append_receipts(tmp_path, {"ticket_id": "TK-R1", "status": "done"})
    third = run_pass(store, roster=_ROSTER, plan=plan, flags=_FLAGS, shadow=False)
    assert [a["external_ref"] for a in third["assignments"]] == ["R2"]


def test_affinity_bound_on_commit(tmp_path):
    store = _store(tmp_path)
    affinity = AffinityTable()
    out = run_pass(
        store,
        roster=_ROSTER,
        affinity=affinity,
        plan=_plan("R1", thread_id="TH-1"),
        flags=_FLAGS,
        shadow=False,
    )
    assert out["committed"] == 1
    hit = affinity.lookup("TH-1", now=1e9)
    assert hit is not None
    assert hit["worker_id"] == "w-res-1"


def test_wakeup_resumes_paused(tmp_path):
    store = _store(tmp_path)
    live = _seed_live(store, "TK-X1", "X1", "w-res-1")
    paused = transition_ticket(live, "paused", paused_reason="waiting_event")
    paused["waiting_on"] = {"kinds": ["job_done"]}
    save_ticket(paused, store)

    out = run_pass(
        store,
        roster=_ROSTER,
        triggers=[{"trigger_id": "EV-1", "source": "job", "kind": "job_done"}],
        flags=_FLAGS,
        shadow=False,
    )
    assert [r["ticket_id"] for r in out["resumed"]] == ["TK-X1"]
    assert recover_tickets(store)["TK-X1"]["state"] == "live"


def test_drift_reports_live_without_worker(tmp_path):
    store = _store(tmp_path)
    t = create_ticket("TK-X1")
    t["external_ref"] = "X1"
    save_ticket(t, store)
    out = run_pass(store, roster=_ROSTER, flags=_FLAGS, shadow=True)
    assert out["drift"] == [{"ticket_id": "TK-X1", "reason": "live_without_worker"}]


def test_deterministic_same_snapshot(tmp_path):
    store = _store(tmp_path)
    a = run_pass(store, roster=_ROSTER, plan=_plan("R1", "R2"), flags=_FLAGS, shadow=True)
    b = run_pass(store, roster=_ROSTER, plan=_plan("R1", "R2"), flags=_FLAGS, shadow=True)

    def strip(out):
        return [(x["external_ref"], x["worker_id"]) for x in out["would_assignments"]]  # noqa: E731

    assert strip(a) == strip(b)


def test_stats_accumulate(tmp_path):
    store = _store(tmp_path)
    stats = PassStats(max_ring=2)
    run_pass(store, flags={}, stats=stats)
    run_pass(store, roster=_ROSTER, plan=_plan("R1"), flags=_FLAGS, shadow=True, stats=stats)
    snap = stats.snapshot()
    assert snap["passes"] == 2
    assert snap["degraded_count"] == 1
    assert len(snap["ring"]) == 2


# ---- R14: 回执消费闭环(worker_receipts → Ticket 状态 → 依赖闸解除) ----


def _append_receipts(tmp_path, *receipts):
    path = tmp_path / "34-前端应用训练系统" / "dsh_worker_receipts.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as fh:
        for rec in receipts:
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
    return path


def test_receipt_done_ends_ticket_and_unblocks_dependency(tmp_path):
    """done 回执 → ended → 下游依赖解除,下一轮可派单(completed_refs 可持续来源)。"""
    store = _store(tmp_path)
    plan = _plan("R1", "R2", deps={"R2": ["R1"]})
    first = run_pass(store, roster=_ROSTER, plan=plan, flags=_FLAGS, shadow=False)
    assert [a["external_ref"] for a in first["assignments"]] == ["R1"]
    assert first["deferred"] == [{"external_ref": "R2", "reason": "dependency_unmet"}]

    _append_receipts(tmp_path, {"ticket_id": "TK-R1", "status": "done"})
    second = run_pass(store, roster=_ROSTER, plan=plan, flags=_FLAGS, shadow=False)

    assert second["receipts"]["applied"] == [{"ticket_id": "TK-R1", "from": "live", "to": "ended"}]
    assert second["skipped"] == [{"external_ref": "R1", "reason": "already_ended"}]
    assert [a["external_ref"] for a in second["assignments"]] == ["R2"]
    assert recover_tickets(store)["TK-R1"]["state"] == "ended"


def test_receipt_failed_retryable_pauses_waiting_job(tmp_path):
    """failed + retryable → paused + waiting_job,释放 Worker 槽(D3/D5 契约)。"""
    store = _store(tmp_path)
    _seed_live(store, "TK-R1", "R1", "w-res-1")
    _append_receipts(
        tmp_path, {"ticket_id": "TK-R1", "status": "failed", "failure_class": "retryable"}
    )

    out = run_pass(store, roster=_ROSTER, plan=_plan("R2"), flags=_FLAGS, shadow=False)

    assert out["receipts"]["applied"] == [{"ticket_id": "TK-R1", "from": "live", "to": "paused"}]
    saved = recover_tickets(store)["TK-R1"]
    assert saved["state"] == "paused"
    assert saved["paused_reason"] == "waiting_job"
    assert saved["worker_id"] is None
    # 槽已释放 → 同角色 R2 可派给同一个 worker
    assert out["assignments"][0]["worker_id"] == "w-res-1"


def test_receipt_failed_manual_waits_for_person(tmp_path):
    """failed + manual → waitsForPerson(需人工,不自动重试)。"""
    store = _store(tmp_path)
    _seed_live(store, "TK-R1", "R1", "w-res-1")
    _append_receipts(
        tmp_path, {"ticket_id": "TK-R1", "status": "failed", "failure_class": "manual"}
    )

    out = run_pass(store, roster=_ROSTER, plan=_plan("R2"), flags=_FLAGS, shadow=False)

    assert out["receipts"]["applied"] == [
        {"ticket_id": "TK-R1", "from": "live", "to": "waitsForPerson"}
    ]
    saved = recover_tickets(store)["TK-R1"]
    assert saved["state"] == "waitsForPerson"
    assert saved["worker_id"] is None
    assert out["assignments"][0]["worker_id"] == "w-res-1"


def test_receipt_failed_without_failure_class_is_manual(tmp_path):
    """旧回执缺 failure_class → 按 manual 兼容 → waitsForPerson。"""
    store = _store(tmp_path)
    _seed_live(store, "TK-R1", "R1", "w-res-1")
    _append_receipts(tmp_path, {"ticket_id": "TK-R1", "status": "failed"})

    out = run_pass(store, roster=_ROSTER, flags=_FLAGS, shadow=False)

    assert out["receipts"]["applied"] == [
        {"ticket_id": "TK-R1", "from": "live", "to": "waitsForPerson"}
    ]
    assert recover_tickets(store)["TK-R1"]["state"] == "waitsForPerson"


def test_receipt_unknown_failure_class_is_manual(tmp_path):
    """未知 failure_class 走保守侧(manual),不静默自动重试。"""
    store = _store(tmp_path)
    _seed_live(store, "TK-R1", "R1", "w-res-1")
    _append_receipts(tmp_path, {"ticket_id": "TK-R1", "status": "failed", "failure_class": "bogus"})

    out = run_pass(store, roster=_ROSTER, flags=_FLAGS, shadow=False)

    assert out["receipts"]["applied"] == [
        {"ticket_id": "TK-R1", "from": "live", "to": "waitsForPerson"}
    ]


def test_receipt_replay_after_manual_resume_is_idempotent(tmp_path):
    """回执文件每轮重读: 人工恢复后旧 failed 不得再次把 Ticket 打回 paused(R16)。"""
    store = _store(tmp_path)
    _seed_live(store, "TK-R1", "R1", "w-res-1")
    _append_receipts(
        tmp_path, {"ticket_id": "TK-R1", "status": "failed", "failure_class": "retryable"}
    )

    first = run_pass(store, roster=_ROSTER, plan=_plan("R2"), flags=_FLAGS, shadow=False)
    assert first["receipts"]["applied"] == [{"ticket_id": "TK-R1", "from": "live", "to": "paused"}]
    assert first["assignments"][0]["worker_id"] == "w-res-1"

    resumed = transition_ticket(recover_tickets(store)["TK-R1"], "live")
    save_ticket(resumed, store)

    second = run_pass(store, roster=_ROSTER, flags=_FLAGS, shadow=False)
    assert second["receipts"]["applied"] == []
    assert recover_tickets(store)["TK-R1"]["state"] == "live"


def test_receipt_bad_lines_fail_open(tmp_path):
    """坏行/未知状态/未知 ticket → 计入 ignored,本轮 pass 不崩(FAIL-OPEN)。"""
    store = _store(tmp_path)
    path = _append_receipts(
        tmp_path,
        {"ticket_id": "TK-R1", "status": "weird"},
        {"ticket_id": "TK-GONE", "status": "done"},
    )
    with open(path, "a", encoding="utf-8") as fh:
        fh.write("{not-json\n")

    out = run_pass(store, roster=_ROSTER, plan=_plan("R1"), flags=_FLAGS, shadow=False)

    assert out["ok"] is True
    assert out["receipts"]["applied"] == []
    assert out["receipts"]["ignored"] == 3
    assert out["committed"] == 1


def test_receipt_not_consumed_in_shadow(tmp_path):
    """shadow 只算不写 → 不消费回执,L0 状态保持不变。"""
    store = _store(tmp_path)
    _seed_live(store, "TK-R1", "R1", "w-res-1")
    _append_receipts(tmp_path, {"ticket_id": "TK-R1", "status": "done"})

    out = run_pass(store, roster=_ROSTER, flags=_FLAGS, shadow=True)

    assert out["receipts"] == {"applied": [], "ignored": 0}
    assert recover_tickets(store)["TK-R1"]["state"] == "live"
