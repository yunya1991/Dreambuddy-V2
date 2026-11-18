# -*- coding: utf-8 -*-
"""裁决事件唤醒桥测试（P2.5 运行时接线）。

验收：
  - verdict.updated → trigger(kind=waiting_verdict, source=verdict)
  - 非裁决事件 / 非法 payload → None
  - paused(waiting_verdict) Ticket 被事件唤醒 → live
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from core.ticket_resume import RESUMABLE_REASONS  # noqa: E402
from core.ticket_state import create_ticket, transition_ticket  # noqa: E402
from core.ticket_store import JsonlTicketStore, load_ticket, save_ticket  # noqa: E402
from core.verdict_resume_bridge import (  # noqa: E402
    VERDICT_EVENT_TYPE,
    WAKE_KIND,
    apply_verdict_event,
    to_resume_trigger,
)


def _event(payload_over=None):
    payload = {
        "verdict_id": "verdict:task-1:U3:abcd1234",
        "task_id": "task-1",
        "trace_id": "tr-1",
        "claim": "该接口返回营收字段",
        "level": "U3",
        "verdict": "supported",
    }
    payload.update(payload_over or {})
    return {
        "type": VERDICT_EVENT_TYPE,
        "task_id": "task-1",
        "trace_id": "tr-1",
        "seq": 1,
        "ts": 1000.0,
        "payload": payload,
    }


def test_waiting_verdict_is_resumable():
    assert "waiting_verdict" in RESUMABLE_REASONS


def test_trigger_mapping():
    trigger = to_resume_trigger(_event())
    assert trigger["kind"] == WAKE_KIND
    assert trigger["source"] == "verdict"
    assert trigger["trigger_id"] == "verdict:task-1:U3:abcd1234"
    assert trigger["payload_ref"].startswith("verdict:")


def test_non_verdict_events_ignored():
    assert to_resume_trigger({"type": "gate.updated"}) is None
    assert to_resume_trigger(_event({"verdict": "unknown"})) is None
    assert to_resume_trigger(_event({"task_id": ""})) is None
    assert to_resume_trigger(None) is None
    assert apply_verdict_event(None, {"type": "gate.updated"}) == []


def test_apply_resumes_waiting_verdict_ticket(tmp_path):
    store = JsonlTicketStore(str(tmp_path))
    ticket = create_ticket("TK-V", trace_id="tr-1")
    ticket["worker_id"] = "w-1"
    ticket = transition_ticket(ticket, "paused", paused_reason="waiting_verdict", now=1000.0)
    ticket["waiting_on"] = {"kinds": [WAKE_KIND], "source": "verdict"}
    assert save_ticket(ticket, store) is not None

    resumed = apply_verdict_event(store, _event(), now=2000.0)

    assert [item["ticket_id"] for item in resumed] == ["TK-V"]
    back = load_ticket("TK-V", store)
    assert back["state"] == "live"
    assert back["paused_reason"] is None
    assert back.get("worker_id") is None


def test_apply_keeps_unrelated_ticket_paused(tmp_path):
    store = JsonlTicketStore(str(tmp_path))
    ticket = create_ticket("TK-O", trace_id="tr-1")
    ticket = transition_ticket(ticket, "paused", paused_reason="waiting_event", now=1000.0)
    ticket["waiting_on"] = {"kinds": ["data_ready"], "source": "18"}
    save_ticket(ticket, store)

    assert apply_verdict_event(store, _event(), now=2000.0) == []
    assert load_ticket("TK-O", store)["state"] == "paused"
