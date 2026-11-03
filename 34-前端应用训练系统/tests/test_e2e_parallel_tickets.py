# -*- coding: utf-8 -*-
"""T-DSH-P1 E2E: 并行 Ticket × L0 持久化 × Thread 直通 × Mandate 门禁。

依据: DESIGN-DSH-ARCH-UPGRADE v0.2 P1·并行退出判据 + 验收 V3(3 Ticket 同时
live,任一 paused 不占槽) / V4(越权明确拒绝,审计留痕) / V5(重启后 Ticket
可从 L0 恢复)。

链路(全部 in-process):
  3 事件 → worker_pool 并发分派(3 Worker 各占一槽,并行 live)
  → 每次迁移即写 L0(ticket_store,latest-wins)
  → 模拟重启 recover → 状态完整(V5)
  → 其一 paused(waiting_event) → 槽释放 → 新 Ticket 派到刚释放的 Worker(V3)
  → 同 Thread 后续事件 → 亲和直通原 Worker(不经 Router);paused 后亲和解除
  → Worker 越权调用 → mandate_gate 明确拒绝 + 审计留痕(V4)
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from core.mandate_gate import (  # noqa: E402
    check_tool_call,
    load_mandate_write_tools,
    load_worker_roles,
)
from core.thread_affinity import AffinityTable  # noqa: E402
from core.ticket_state import create_ticket, transition_ticket  # noqa: E402
from core.ticket_store import JsonlTicketStore, recover_tickets, save_ticket  # noqa: E402
from core.worker_pool import dispatch_concurrent  # noqa: E402

_ROSTER = {"research": ["w-res-1", "w-res-2"], "engineer": ["w-eng-1"]}


def _plan3():
    return {
        "draft": True,
        "tickets": [
            {"external_ref": "R1", "mandate": {"goal": "g1"}, "route_hint": {"role": "research"}},
            {"external_ref": "R2", "mandate": {"goal": "g2"}, "route_hint": {"role": "research"}},
            {"external_ref": "E1", "mandate": {"goal": "g3"}, "route_hint": {"role": "engineer"}},
        ],
        "dispatch": {"mode": "parallel", "depends_on": {}},
    }


def test_e2e_p1_parallel_persist_affinity_gate(tmp_path):
    store = JsonlTicketStore(root=str(tmp_path))
    affinity = AffinityTable()
    trace = "tr-e2e-p1-001"

    # ① 并发分派: 3 Ticket → 3 Worker,同时 live(V3 前半)
    out = dispatch_concurrent(_plan3(), _ROSTER, active_tickets=[])
    assert len(out["assignments"]) == 3
    assert out["unassigned"] == []

    tickets = []
    for i, a in enumerate(out["assignments"]):
        t = create_ticket(f"TK-{a['external_ref']}", trace_id=trace)
        t["worker_id"] = a["worker_id"]
        t["thread_id"] = f"TH-{i}"
        save_ticket(t, store)  # 每次迁移即写 L0(ADR-2 单一事实源)
        affinity.bind(t["thread_id"], t["worker_id"], t["ticket_id"], now=1000.0)
        tickets.append(t)
    live_workers = {t["worker_id"] for t in tickets}
    assert live_workers == {"w-res-1", "w-res-2", "w-eng-1"}  # 并行 live 互不阻塞

    # ② V5: 模拟重启——新 store 实例 recover,全部 live 状态完整恢复
    recovered = recover_tickets(JsonlTicketStore(root=str(tmp_path)))
    assert len(recovered) == 3
    assert all(t["state"] == "live" for t in recovered.values())
    assert all(t["trace_id"] == trace for t in recovered.values())

    # ③ Thread 直通: 同 Thread 后续事件 → 亲和命中,不经 Router
    hit = affinity.lookup("TH-0", now=1010.0)
    assert hit["worker_id"] == tickets[0]["worker_id"]
    assert hit["ticket_id"] == tickets[0]["ticket_id"]

    # ④ V3 后半: TK-R1 paused(waiting_event) → 不占槽 → 亲和解除 → 新 Ticket 入槽
    t0 = transition_ticket(tickets[0], "paused", paused_reason="waiting_event", now=1020.0)
    save_ticket(t0, store)
    affinity.on_ticket_state("TH-0", "paused")
    assert affinity.lookup("TH-0", now=1021.0) is None  # 亲和解除,不再直通

    active = [t0, tickets[1], tickets[2]]
    assert t0["worker_id"] is None  # paused 不占槽
    out2 = dispatch_concurrent(
        {
            "draft": True,
            "tickets": [
                {
                    "external_ref": "R3",
                    "mandate": {"goal": "g4"},
                    "route_hint": {"role": "research"},
                }
            ],
            "dispatch": {"mode": "parallel", "depends_on": {}},
        },
        _ROSTER,
        active_tickets=active,
    )
    assert len(out2["assignments"]) == 1
    assert out2["assignments"][0]["worker_id"] == tickets[0]["worker_id"]  # 刚释放的 w-res-1
    assert set(out2["occupied"]) == {"w-res-2", "w-eng-1"}

    # ⑤ V4: 越权调用被明确拒绝 + 审计留痕(接 47 registry 真实角色集)
    roles = load_worker_roles()
    write_tools = load_mandate_write_tools()
    verdicts = []
    d1 = check_tool_call(
        "engineer",
        "eval_report",
        roles=roles,
        write_tools=write_tools,
        recorder=verdicts.append,
        trace_id=trace,
    )
    assert d1["allowed"] is False
    assert d1["reason"] == "tool_not_in_role_set"
    d2 = check_tool_call(
        "research",
        "record",
        roles=roles,
        write_tools=write_tools,
        recorder=verdicts.append,
        trace_id=trace,
    )
    assert d2["allowed"] is False  # 写工具 H7 一律拒
    assert d2["reason"] == "write_tool_requires_mandate"
    assert len(verdicts) == 2
    assert all(v["trace_id"] == trace for v in verdicts)  # 审计留痕 trace 一致

    # ⑥ 恢复链再验证: paused 状态也已持久化(重启可续跑的基础)
    recovered2 = recover_tickets(JsonlTicketStore(root=str(tmp_path)))
    assert recovered2["TK-R1"]["state"] == "paused"
    assert recovered2["TK-R1"]["paused_reason"] == "waiting_event"
    assert recovered2["TK-R1"]["worker_id"] is None
