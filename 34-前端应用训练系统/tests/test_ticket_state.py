# -*- coding: utf-8 -*-
"""T-DSH-P0 D2: Ticket 四态状态机测试（RED）。

依据: DESIGN-DSH-ARCH-UPGRADE v0.2 ADR-2 修订(状态映射 L0 存储,禁 DSH 第二套
权威状态) + ADR-3 补充(paused 子因 G3 定稿: waiting_event/waiting_job/
waiting_person;异步等待必须走 job 完成事件唤醒,禁止忙轮询)。
验收:
  - 四态: live / paused / waitsForPerson / ended
  - paused 必须携带合法子因(waiting_event/waiting_job/waiting_person)
  - 合法迁移: live→paused/waitsForPerson/ended; paused→live(事件唤醒)/ended;
    waitsForPerson→live/ended; ended 终态不可转出
  - 非法迁移 → None(FAIL-OPEN),不改原 Ticket
  - 迁移留痕: history 追加 {from, to, reason, ts},trace_id 全链一致
  - Worker 不占槽: paused/waitsForPerson 时 worker_id 释放(None)
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from core.ticket_state import (  # noqa: E402
    PAUSED_REASONS,
    TICKET_STATES,
    create_ticket,
    transition_ticket,
)


class TestConstants:
    def test_four_states(self):
        assert set(TICKET_STATES) == {"live", "paused", "waitsForPerson", "ended"}

    def test_paused_reasons(self):
        assert set(PAUSED_REASONS) == {"waiting_event", "waiting_job", "waiting_person"}


class TestCreate:
    def test_create_live(self):
        t = create_ticket("TK-1", trace_id="tr-1")
        assert t["ticket_id"] == "TK-1"
        assert t["state"] == "live"
        assert t["paused_reason"] is None
        assert t["trace_id"] == "tr-1"
        assert t["history"] == []

    def test_create_fail_open(self):
        assert create_ticket(None) is None
        assert create_ticket("") is None


class TestLegalTransitions:
    def test_live_to_paused_with_reason(self):
        t = create_ticket("TK-1")
        out = transition_ticket(t, "paused", paused_reason="waiting_job", now=1000.0)
        assert out["state"] == "paused"
        assert out["paused_reason"] == "waiting_job"

    def test_live_to_waits_for_person(self):
        t = create_ticket("TK-1")
        out = transition_ticket(t, "waitsForPerson")
        assert out["state"] == "waitsForPerson"

    def test_live_to_ended(self):
        t = create_ticket("TK-1")
        out = transition_ticket(t, "ended")
        assert out["state"] == "ended"

    def test_paused_to_live_resume(self):
        t = create_ticket("TK-1")
        t = transition_ticket(t, "paused", paused_reason="waiting_event")
        out = transition_ticket(t, "live")  # 事件驱动 resume(禁忙轮询)
        assert out["state"] == "live"
        assert out["paused_reason"] is None  # 唤醒即清子因

    def test_paused_to_ended(self):
        t = create_ticket("TK-1")
        t = transition_ticket(t, "paused", paused_reason="waiting_job")
        out = transition_ticket(t, "ended")
        assert out["state"] == "ended"

    def test_waits_for_person_to_live(self):
        t = create_ticket("TK-1")
        t = transition_ticket(t, "waitsForPerson")
        out = transition_ticket(t, "live")
        assert out["state"] == "live"


class TestIllegalTransitions:
    def test_ended_is_terminal(self):
        t = create_ticket("TK-1")
        t = transition_ticket(t, "ended")
        assert transition_ticket(t, "live") is None
        assert transition_ticket(t, "paused", paused_reason="waiting_job") is None

    def test_paused_without_reason_rejected(self):
        t = create_ticket("TK-1")
        assert transition_ticket(t, "paused") is None
        assert transition_ticket(t, "paused", paused_reason="busy_poll") is None

    def test_unknown_state_rejected(self):
        t = create_ticket("TK-1")
        assert transition_ticket(t, "sleeping") is None

    def test_paused_to_waits_for_person_rejected(self):
        # 两态语义不同(等人是独立态),不允许互跳,须先回 live
        t = create_ticket("TK-1")
        t = transition_ticket(t, "paused", paused_reason="waiting_person")
        assert transition_ticket(t, "waitsForPerson") is None

    def test_fail_open_bad_ticket(self):
        assert transition_ticket(None, "live") is None
        assert transition_ticket({"no_state": True}, "live") is None

    def test_original_not_mutated(self):
        t = create_ticket("TK-1")
        transition_ticket(t, "ended")
        assert t["state"] == "live"  # 纯函数,不改原对象


class TestHistoryAndTrace:
    def test_history_appended(self):
        t = create_ticket("TK-1", trace_id="tr-9")
        t = transition_ticket(t, "paused", paused_reason="waiting_event", now=1000.0)
        t = transition_ticket(t, "live", now=1001.0)
        assert len(t["history"]) == 2
        assert t["history"][0]["from"] == "live"
        assert t["history"][0]["to"] == "paused"
        assert t["history"][0]["reason"] == "waiting_event"
        assert t["history"][0]["ts"] == 1000.0
        assert t["history"][1]["from"] == "paused"
        assert t["history"][1]["to"] == "live"

    def test_trace_id_preserved(self):
        t = create_ticket("TK-1", trace_id="tr-9")
        t = transition_ticket(t, "ended")
        assert t["trace_id"] == "tr-9"


class TestWorkerSlotRelease:
    def test_paused_releases_worker(self):
        t = create_ticket("TK-1")
        t["worker_id"] = "w-res-1"
        out = transition_ticket(t, "paused", paused_reason="waiting_job")
        assert out["worker_id"] is None  # 不占槽: 并行度的关键

    def test_waits_for_person_releases_worker(self):
        t = create_ticket("TK-1")
        t["worker_id"] = "w-res-1"
        out = transition_ticket(t, "waitsForPerson")
        assert out["worker_id"] is None

    def test_live_keeps_worker(self):
        t = create_ticket("TK-1")
        t["worker_id"] = "w-res-1"
        out = transition_ticket(t, "ended")
        assert out["worker_id"] == "w-res-1"  # ended 只结态,槽由编排侧回收
