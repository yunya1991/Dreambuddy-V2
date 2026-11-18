# -*- coding: utf-8 -*-
"""裁决事件消费者测试（P2.5 运行时接线）。

验收：
  - verdict.updated 事件唤醒 waiting_verdict Ticket
  - seq 游标幂等，第二轮不重复唤醒
  - 非裁决事件 / 坏行不影响其它事件
"""

import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from core.ticket_state import create_ticket, transition_ticket  # noqa: E402
from core.ticket_store import JsonlTicketStore, load_ticket, save_ticket  # noqa: E402
from core.verdict_event_consumer import consume_once  # noqa: E402
from core.verdict_resume_bridge import WAKE_KIND  # noqa: E402


def _write_events(events_dir, task_id, events):
    os.makedirs(events_dir, exist_ok=True)
    path = os.path.join(events_dir, "{}.jsonl".format(task_id))
    with open(path, "w", encoding="utf-8") as f:
        for event in events:
            f.write(json.dumps(event, ensure_ascii=False) + "\n")


def _verdict_event(task_id, seq=0):
    return {
        "task_id": task_id,
        "trace_id": "tr-1",
        "seq": seq,
        "ts": 1000.0,
        "type": "verdict.updated",
        "payload": {
            "verdict_id": "verdict:{}:U3:abcd".format(task_id),
            "task_id": task_id,
            "trace_id": "tr-1",
            "claim": "c",
            "level": "U3",
            "verdict": "supported",
        },
    }


def _pause_waiting_verdict(task_id):
    ticket = create_ticket(task_id, trace_id="tr-1")
    ticket["worker_id"] = "w-1"
    ticket = transition_ticket(ticket, "paused", paused_reason="waiting_verdict", now=1000.0)
    ticket["waiting_on"] = {"kinds": [WAKE_KIND], "source": "verdict"}
    return ticket


def test_consume_resumes_and_is_idempotent(tmp_path):
    root = str(tmp_path)
    store = JsonlTicketStore(root)
    save_ticket(_pause_waiting_verdict("TK-1"), store)

    events_dir = os.path.join(root, "task-board")
    state = os.path.join(root, "state.json")
    _write_events(
        events_dir,
        "TK-1",
        [
            {"task_id": "TK-1", "seq": 0, "ts": 900.0, "type": "gate.updated", "payload": {}},
            _verdict_event("TK-1", seq=1),
        ],
    )

    first = consume_once(store, events_dir, state, now=2000.0)
    assert first["verdict_events"] == 1
    assert first["resumed"] == 1
    assert load_ticket("TK-1", store)["state"] == "live"

    second = consume_once(store, events_dir, state, now=3000.0)
    assert second["verdict_events"] == 0
    assert second["resumed"] == 0


def test_bad_lines_do_not_break_other_events(tmp_path):
    root = str(tmp_path)
    store = JsonlTicketStore(root)
    save_ticket(_pause_waiting_verdict("TK-2"), store)

    events_dir = os.path.join(root, "task-board")
    os.makedirs(events_dir)
    path = os.path.join(events_dir, "TK-2.jsonl")
    with open(path, "w", encoding="utf-8") as f:
        f.write("{bad json\n")
        f.write(json.dumps(_verdict_event("TK-2", seq=1)) + "\n")

    counts = consume_once(store, events_dir, os.path.join(root, "state.json"), now=2000.0)
    assert counts["resumed"] == 1
    assert load_ticket("TK-2", store)["state"] == "live"


def test_non_verdict_events_do_not_resume(tmp_path):
    root = str(tmp_path)
    store = JsonlTicketStore(root)
    save_ticket(_pause_waiting_verdict("TK-3"), store)

    events_dir = os.path.join(root, "task-board")
    _write_events(
        events_dir,
        "TK-3",
        [{"task_id": "TK-3", "seq": 0, "ts": 900.0, "type": "gate.updated", "payload": {}}],
    )

    counts = consume_once(store, events_dir, os.path.join(root, "state.json"))
    assert counts["resumed"] == 0
    assert load_ticket("TK-3", store)["state"] == "paused"
