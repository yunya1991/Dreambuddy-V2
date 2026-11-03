# -*- coding: utf-8 -*-
"""T-DSH-P1 P1-1: Ticket 状态 L0 持久化测试（RED）。

依据: DESIGN-DSH-ARCH-UPGRADE v0.2 ADR-2(状态单一事实源=L0,禁止 DSH 内
第二套权威状态;DSH storages 仅作运行时缓存) + 验收 V5(状态一致: 任意时刻
DSH 侧无权威状态副本;重启后 Ticket 可从 L0 恢复)。

定位: ticket_state.py 是纯函数状态机(不持存储);本模块负责把每次迁移结果
追加写入 L0(jsonl 快照,latest-wins),并提供恢复能力。存储后端可注入
(默认 JsonlTicketStore;云端 PG 后端以同接口注入,不在本范围)。

验收:
  - save/load/list/recover 四操作;latest-wins(同 ticket_id 取最后一条)
  - 重启恢复: 新 store 实例读同一路径可恢复全部 Ticket(V5)
  - 迁移留痕不丢: history/trace_id 原样持久化
  - FAIL-OPEN: 坏输入 → None/[];坏行跳过不抛错
  - 开关 enable_ticket_store 默认 False
"""

import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from core.ticket_state import create_ticket, transition_ticket  # noqa: E402
from core.ticket_store import (  # noqa: E402
    JsonlTicketStore,
    is_ticket_store_enabled,
    list_tickets,
    load_ticket,
    recover_tickets,
    save_ticket,
)


def _make_store(tmp_path):
    return JsonlTicketStore(root=str(tmp_path))


class TestSwitch:
    def test_default_off(self):
        assert is_ticket_store_enabled() is False
        assert is_ticket_store_enabled({}) is False
        assert is_ticket_store_enabled(None) is False

    def test_on(self):
        assert is_ticket_store_enabled({"enable_ticket_store": True}) is True


class TestSaveLoad:
    def test_save_then_load(self, tmp_path):
        store = _make_store(tmp_path)
        t = create_ticket("TK-1", trace_id="tr-1")
        assert save_ticket(t, store) is not None
        loaded = load_ticket("TK-1", store)
        assert loaded["ticket_id"] == "TK-1"
        assert loaded["state"] == "live"
        assert loaded["trace_id"] == "tr-1"

    def test_latest_wins(self, tmp_path):
        store = _make_store(tmp_path)
        t = create_ticket("TK-1", trace_id="tr-1")
        save_ticket(t, store)
        t = transition_ticket(t, "paused", paused_reason="waiting_job", now=1000.0)
        save_ticket(t, store)
        t = transition_ticket(t, "live", now=1001.0)
        save_ticket(t, store)
        loaded = load_ticket("TK-1", store)
        assert loaded["state"] == "live"
        assert len(loaded["history"]) == 2  # 迁移留痕完整持久化

    def test_load_missing(self, tmp_path):
        store = _make_store(tmp_path)
        assert load_ticket("TK-NOPE", store) is None

    def test_save_fail_open(self, tmp_path):
        store = _make_store(tmp_path)
        assert save_ticket(None, store) is None
        assert save_ticket({"no_id": True}, store) is None
        assert save_ticket(create_ticket("TK-1"), None) is None

    def test_multi_tickets_isolated(self, tmp_path):
        store = _make_store(tmp_path)
        save_ticket(create_ticket("TK-1", trace_id="tr-1"), store)
        t2 = create_ticket("TK-2", trace_id="tr-2")
        t2 = transition_ticket(t2, "ended", now=1000.0)
        save_ticket(t2, store)
        assert load_ticket("TK-1", store)["state"] == "live"
        assert load_ticket("TK-2", store)["state"] == "ended"


class TestListAndRecover:
    def test_list_all_and_by_state(self, tmp_path):
        store = _make_store(tmp_path)
        save_ticket(create_ticket("TK-1"), store)
        t2 = create_ticket("TK-2")
        t2 = transition_ticket(t2, "paused", paused_reason="waiting_event", now=1.0)
        save_ticket(t2, store)
        t3 = create_ticket("TK-3")
        t3 = transition_ticket(t3, "ended", now=2.0)
        save_ticket(t3, store)
        all_t = list_tickets(store)
        assert {t["ticket_id"] for t in all_t} == {"TK-1", "TK-2", "TK-3"}
        live = list_tickets(store, state="live")
        assert [t["ticket_id"] for t in live] == ["TK-1"]
        paused = list_tickets(store, state="paused")
        assert [t["ticket_id"] for t in paused] == ["TK-2"]

    def test_recover_after_restart(self, tmp_path):
        """V5: 重启后 Ticket 可从 L0 恢复(新实例读同一路径)。"""
        store1 = _make_store(tmp_path)
        t = create_ticket("TK-1", trace_id="tr-r")
        t["worker_id"] = "w-res-1"
        save_ticket(t, store1)
        t = transition_ticket(t, "paused", paused_reason="waiting_event", now=10.0)
        save_ticket(t, store1)
        # 模拟重启: 全新 store 实例,无任何内存状态
        store2 = _make_store(tmp_path)
        recovered = recover_tickets(store2)
        assert set(recovered.keys()) == {"TK-1"}
        assert recovered["TK-1"]["state"] == "paused"
        assert recovered["TK-1"]["paused_reason"] == "waiting_event"
        assert recovered["TK-1"]["worker_id"] is None  # paused 不占槽也已持久化
        assert recovered["TK-1"]["trace_id"] == "tr-r"

    def test_recover_empty_store(self, tmp_path):
        assert recover_tickets(_make_store(tmp_path)) == {}

    def test_corrupted_lines_skipped(self, tmp_path):
        store = _make_store(tmp_path)
        save_ticket(create_ticket("TK-OK"), store)
        path = store.path
        with open(path, "a", encoding="utf-8") as f:
            f.write("not-a-json-line\n")
            f.write(json.dumps({"no_ticket_id": 1}) + "\n")
        # 坏行跳过,好行仍可读
        assert load_ticket("TK-OK", store)["state"] == "live"
        assert len(list_tickets(store)) == 1
