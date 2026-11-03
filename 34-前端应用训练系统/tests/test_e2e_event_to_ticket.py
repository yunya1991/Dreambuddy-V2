# -*- coding: utf-8 -*-
"""T-DSH-P0 E2E: 事件→Ticket→Worker→45 shadow→Settle 端到端测试。

依据: DESIGN-DSH-ARCH-UPGRADE v0.2 P0·骨架(1 类事件端到端走通
Router→Ticket→Worker→45→settle) + 验证标准 V2(全链路 trace_id 一致)
+ SPEC-EVENT-DRIVEN-L1-GATEWAY v0.2 §三.1 任务6(45 门禁 P0 shadow:
评测执行但只记录不拦截)。

链路(全部 in-process,外部系统用 fake):
  文件落盘事件 → event_gateway 分流(escalate_l2)
  → l0_context_assembler 组六维信封(信封铁律)
  → okr_ticket_bridge 翻译建议性草案 → ticket_router 单轮分派
  → ticket_state 创建/迁移(Worker 产出后 ended)
  → 45 门禁 shadow(记录裁决,不拦截) → L0 settle 写回案例库
  全链路 trace_id 一致。
"""

import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from core.event_gateway import ACTION_ESCALATE_L2, load_event_intents, route_trigger  # noqa: E402
from core.l0_context_assembler import build_six_dim_context  # noqa: E402
from core.l0_foundation import L0Foundation  # noqa: E402
from core.okr_ticket_bridge import translate_plan_to_tickets  # noqa: E402
from core.ticket_router import route_single_round  # noqa: E402
from core.ticket_state import create_ticket, transition_ticket  # noqa: E402

_TRACE = "tr-e2e-p0-001"
_WORKERS = {"research": ["w-res-1"], "engineer": ["w-eng-1"], "verifier": ["w-ver-1"]}


class _FakeL0ForContext:
    """六维供给 fake(避免触真实数据源)。"""

    def fetch_context(self, scope, params=None):
        return {
            "ok": True,
            "data": {"scope": scope},
            "source": "fake",
            "timestamp": "t",
            "degraded": False,
            "meta": {},
        }


def test_e2e_event_to_ticket_to_settle(tmp_path):
    # ① 文件落盘事件 → 网关分流: file_landed 命中契约意图? 此处用未注册 kind
    #    走高价值升级路径(六维供给 + L2)
    trigger = {
        "trigger_id": "EV-1",
        "source": "file_watch",
        "kind": "research_request",  # 契约未注册 → 未命中意图
        "payload_ref": "events/inbox/EV-1.json",
        "ts": 1000.0,
    }
    decision = route_trigger(
        trigger,
        rules={"value_threshold": 0.5, "kind_value": {"research_request": 0.9}},
        intents=load_event_intents(),
    )
    assert decision["action"] == ACTION_ESCALATE_L2

    # ② 升级 L2 前组六维上下文信封(信封铁律: 逐维子信封原样保留)
    ctx = build_six_dim_context(trigger, l0=_FakeL0ForContext(), trace_id=_TRACE)
    assert ctx["ok"] is True
    assert ctx["data"]["trace_id"] == _TRACE
    assert set(ctx["data"]["six_dims"].keys()) == {
        "market",
        "skill",
        "knowledge",
        "experience",
        "cases",
        "rea",
    }

    # ③ A 层 OKR → 建议性 Ticket 草案(双门之前)
    plan = {"plan_items": [{"okr": "研判研究请求并产出研究结论", "domain": "finance_research"}]}
    draft = translate_plan_to_tickets(plan)
    assert draft["draft"] is True
    assert draft["tickets"][0]["route_hint"]["role"] == "research"

    # ④ Router 单轮分派(无状态;只感知角色标签)
    routed = route_single_round(draft, _WORKERS)
    assert len(routed["assignments"]) == 1
    assignment = routed["assignments"][0]
    assert assignment["worker_id"] == "w-res-1"

    # ⑤ Ticket 创建 → Worker 只读产出(以 fake 结果代表) → ended
    ticket = create_ticket("TK-EV-1", trace_id=_TRACE)
    ticket["worker_id"] = assignment["worker_id"]
    worker_result = {"success": True, "answer": "研究结论: ...", "data": {"k": 1}}
    ticket = transition_ticket(ticket, "ended", now=1002.0)
    assert ticket["state"] == "ended"
    assert ticket["trace_id"] == _TRACE
    assert len(ticket["history"]) == 1

    # ⑥ 45 门禁 shadow: 评测执行、裁决记录、但不拦截 settle(P0 shadow)
    gate_verdicts = []

    def shadow_gate(context):
        verdict = {"verdict": "PASS_SHADOW", "trace_id": context.get("trace_id")}
        gate_verdicts.append(verdict)
        return True, verdict  # shadow: 只记录不拦截 → 一律放行

    # ⑦ Settle 写回 L0(案例库落 tmp 根,验证 trace_id 全链一致)
    l0 = L0Foundation(root=str(tmp_path))
    l0.settle(
        worker_result,
        {"intent": "event_research", "message": "研究请求", "trace_id": _TRACE},
        gate=shadow_gate,
    )
    case_path = tmp_path / "34-前端应用训练系统" / "l1_case_store.jsonl"
    assert case_path.exists()
    case = json.loads(case_path.read_text(encoding="utf-8").strip().splitlines()[-1])
    assert case["intent"] == "event_research"

    # ⑧ 全链路 trace_id 一致性断言
    assert gate_verdicts[0]["trace_id"] == _TRACE
    assert ctx["data"]["trace_id"] == _TRACE
    assert ticket["trace_id"] == _TRACE


def test_e2e_45_shadow_does_not_block_even_on_fail_verdict(tmp_path):
    """45 shadow 语义: 即使评测给 FAIL 也放行(只记录),P1 才转强制。"""
    verdicts = []

    def fail_shadow_gate(context):
        verdicts.append("FAIL_SHADOW")
        return True, {"verdict": "FAIL_SHADOW"}  # shadow: FAIL 也放行

    l0 = L0Foundation(root=str(tmp_path))
    l0.settle(
        {"success": True, "answer": "a", "data": None},
        {"intent": "event_research", "message": "m"},
        gate=fail_shadow_gate,
    )
    case_path = tmp_path / "34-前端应用训练系统" / "l1_case_store.jsonl"
    assert case_path.exists()  # 未被拦截
    assert verdicts == ["FAIL_SHADOW"]  # 但裁决已记录可审计
