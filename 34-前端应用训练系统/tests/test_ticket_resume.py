# -*- coding: utf-8 -*-
"""会话级离线续跑(T-DSH-P3 P3-2) RED 测试。

依据: DESIGN-DSH-ARCH-UPGRADE v0.2 P3·常驻退出判据(重启后 Ticket 可续跑)
+ ADR-3(paused 子因 waiting_event/waiting_job 必须走事件唤醒,禁止忙轮询)
+ ADR-2(权威状态在 L0,重启后从 L0 恢复) + V5(重启后 Ticket 可从 L0 恢复)
+ H1 FAIL-OPEN。

断言:
  - recover_resumable 只挑 paused(waiting_event/waiting_job),其余态不挑
  - matches_wakeup: thread_id 直通 / waiting_on.kinds 命中 / 不匹配 False
  - resume_on_event: 事件唤醒 → paused→live 并回写 L0(latest-wins);
    可选亲和重建;不匹配事件 → 不唤醒;坏输入 → [] 不抛错
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from core.thread_affinity import AffinityTable  # noqa: E402
from core.ticket_resume import (  # noqa: E402
    matches_wakeup,
    recover_resumable,
    resume_on_event,
)
from core.ticket_state import create_ticket, transition_ticket  # noqa: E402
from core.ticket_store import JsonlTicketStore, load_ticket, save_ticket  # noqa: E402


def _paused_ticket(tid, reason, **extra):
    t = create_ticket(tid, trace_id="tr-resume")
    t["worker_id"] = "w-1"
    t = transition_ticket(t, "paused", paused_reason=reason, now=1000.0)
    t.update(extra)
    return t


def test_recover_resumable_filters(tmp_path):
    store = JsonlTicketStore(str(tmp_path))
    save_ticket(_paused_ticket("TK-E", "waiting_event"), store)
    save_ticket(_paused_ticket("TK-J", "waiting_job"), store)
    save_ticket(_paused_ticket("TK-P", "waiting_person"), store)
    live = create_ticket("TK-L")
    save_ticket(live, store)
    ended = transition_ticket(create_ticket("TK-X"), "ended", now=1.0)
    save_ticket(ended, store)

    resumable = recover_resumable(store)
    assert sorted(t["ticket_id"] for t in resumable) == ["TK-E", "TK-J"]
    # 坏输入 FAIL-OPEN
    assert recover_resumable(None) == []


def test_matches_wakeup_by_thread_and_kind():
    t = _paused_ticket("TK-1", "waiting_event", thread_id="th-9")
    t["waiting_on"] = {"kinds": ["backtest_done"], "source": "45"}
    assert matches_wakeup(t, {"thread_id": "th-9", "kind": "other"}) is True
    assert matches_wakeup(t, {"kind": "backtest_done", "source": "45"}) is True
    assert matches_wakeup(t, {"kind": "unrelated", "source": "45"}) is False
    assert matches_wakeup(t, {"kind": "backtest_done", "source": "other"}) is False
    # 非 paused / 坏输入 → False
    assert matches_wakeup(create_ticket("TK-2"), {"kind": "x"}) is False
    assert matches_wakeup(None, {"kind": "x"}) is False
    assert matches_wakeup(t, None) is False


def test_resume_on_event_wakes_and_persists(tmp_path):
    store = JsonlTicketStore(str(tmp_path))
    t = _paused_ticket("TK-1", "waiting_event", thread_id="th-1")
    t["waiting_on"] = {"kinds": ["data_ready"]}
    save_ticket(t, store)

    # 模拟重启: 新建 store(同路径),亲和表为空
    store2 = JsonlTicketStore(str(tmp_path))
    affinity = AffinityTable()
    resumed = resume_on_event(
        store2,
        {"trigger_id": "tg-1", "source": "s", "kind": "data_ready", "thread_id": "th-1"},
        now=2000.0,
        affinity=affinity,
        worker_id="w-2",
    )
    assert [x["ticket_id"] for x in resumed] == ["TK-1"]
    # 状态回 live + 子因清空 + 迁移留痕
    back = load_ticket("TK-1", store2)
    assert back["state"] == "live"
    assert back["paused_reason"] is None
    assert back["history"][-1]["from"] == "paused"
    assert back["history"][-1]["to"] == "live"
    # 亲和重建(直通锚点)
    hit = affinity.lookup("th-1", now=2001.0)
    assert hit == {"worker_id": "w-2", "ticket_id": "TK-1"}


def test_resume_on_event_no_match(tmp_path):
    store = JsonlTicketStore(str(tmp_path))
    t = _paused_ticket("TK-1", "waiting_event")
    t["waiting_on"] = {"kinds": ["data_ready"]}
    save_ticket(t, store)
    resumed = resume_on_event(
        store, {"trigger_id": "tg-2", "source": "s", "kind": "noise"}, now=1.0
    )
    assert resumed == []
    assert load_ticket("TK-1", store)["state"] == "paused"


def test_resume_waiting_job_by_kind(tmp_path):
    store = JsonlTicketStore(str(tmp_path))
    t = _paused_ticket("TK-J", "waiting_job")
    t["waiting_on"] = {"kinds": ["job_done:EV-1"]}
    save_ticket(t, store)
    resumed = resume_on_event(
        store, {"trigger_id": "tg-3", "source": "45", "kind": "job_done:EV-1"}, now=5.0
    )
    assert [x["ticket_id"] for x in resumed] == ["TK-J"]


def test_resume_fail_open():
    assert resume_on_event(None, {"kind": "x"}) == []
    assert resume_on_event("bad", None) == []
