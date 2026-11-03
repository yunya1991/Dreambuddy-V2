# -*- coding: utf-8 -*-
"""T-DSH-P1 P1-2: Thread 亲和表 + TTL 直通测试（RED）。

依据: DESIGN-DSH-ARCH-UPGRADE v0.2 ADR-3 修订(thread_id + 续跑锚点——同一
Thread 的后续事件可直接送原 Worker,不经 Router) + P1 交付物(Thread 亲和
直通: 亲和表+TTL) + DD3(TTL 初值 30 分钟,按实测命中率调) + ADR-3(paused
/waitsForPerson 释放 Worker 槽——亲和绑定必须同步解除,否则直通指向空槽)。

定位: 纯内存亲和表(运行时缓存,非权威状态——权威 Ticket 状态在 L0,
ADR-2);事件带 thread_id 时先查亲和,命中且未过期 → 直通原 Worker;
未命中/过期/已解除 → None,走 Router 分派。

验收:
  - bind/lookup/release;TTL 默认 1800s,可注入;过期 lookup → None 且驱逐
  - 直通语义: 命中返回 {worker_id, ticket_id};线程隔离(不同 thread_id 互不影响)
  - ADR-3 联动: Ticket 进入 paused/waitsForPerson → 亲和解除(不占槽);
    ended → 亲和解除(线程完结)
  - FAIL-OPEN: 坏输入 → False/None;容量有界(逐出最久未用,防内存膨胀)
  - 开关 enable_thread_affinity 默认 False
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from core.thread_affinity import (  # noqa: E402
    DEFAULT_TTL_SEC,
    AffinityTable,
    is_affinity_enabled,
)


class TestSwitch:
    def test_default_off(self):
        assert is_affinity_enabled() is False
        assert is_affinity_enabled({}) is False
        assert is_affinity_enabled(None) is False

    def test_on(self):
        assert is_affinity_enabled({"enable_thread_affinity": True}) is True

    def test_default_ttl(self):
        assert DEFAULT_TTL_SEC == 1800.0  # DD3 初值 30 分钟


class TestBindLookup:
    def test_bind_then_lookup(self):
        tbl = AffinityTable()
        assert tbl.bind("TH-1", "w-res-1", "TK-1", now=1000.0) is True
        hit = tbl.lookup("TH-1", now=1001.0)
        assert hit["worker_id"] == "w-res-1"
        assert hit["ticket_id"] == "TK-1"

    def test_lookup_miss(self):
        tbl = AffinityTable()
        assert tbl.lookup("TH-NOPE", now=1000.0) is None

    def test_threads_isolated(self):
        tbl = AffinityTable()
        tbl.bind("TH-1", "w-res-1", "TK-1", now=1000.0)
        tbl.bind("TH-2", "w-eng-1", "TK-2", now=1000.0)
        assert tbl.lookup("TH-1", now=1001.0)["worker_id"] == "w-res-1"
        assert tbl.lookup("TH-2", now=1001.0)["worker_id"] == "w-eng-1"
        assert tbl.size() == 2

    def test_rebind_overwrites(self):
        """同一 Thread 换绑(原 Ticket ended 后新 Ticket)以最新为准。"""
        tbl = AffinityTable()
        tbl.bind("TH-1", "w-res-1", "TK-1", now=1000.0)
        tbl.bind("TH-1", "w-res-2", "TK-9", now=2000.0)
        hit = tbl.lookup("TH-1", now=2001.0)
        assert hit["worker_id"] == "w-res-2"
        assert hit["ticket_id"] == "TK-9"
        assert tbl.size() == 1

    def test_bind_fail_open(self):
        tbl = AffinityTable()
        assert tbl.bind(None, "w-1", "TK-1", now=1.0) is False
        assert tbl.bind("TH-1", None, "TK-1", now=1.0) is False
        assert tbl.bind("", "w-1", "TK-1", now=1.0) is False


class TestTTL:
    def test_expired_lookup_returns_none_and_evicts(self):
        tbl = AffinityTable(ttl_sec=1800.0)
        tbl.bind("TH-1", "w-res-1", "TK-1", now=1000.0)
        tbl.bind("TH-2", "w-res-2", "TK-2", now=1000.0)
        assert tbl.lookup("TH-1", now=1000.0 + 1799.0) is not None  # 未过期(TH-1 刷新)
        # 过期: lookup → None 且从表内驱逐(TH-2 自绑定后无活动)
        assert tbl.lookup("TH-2", now=1000.0 + 1801.0) is None
        assert tbl.size() == 1

    def test_custom_ttl(self):
        tbl = AffinityTable(ttl_sec=60.0)
        tbl.bind("TH-1", "w-1", "TK-1", now=0.0)
        assert tbl.lookup("TH-1", now=59.0) is not None
        # 另起一条不查中间态的绑定,验证自定义 TTL 生效
        tbl.bind("TH-2", "w-2", "TK-2", now=0.0)
        assert tbl.lookup("TH-2", now=61.0) is None

    def test_lookup_refreshes_activity(self):
        """命中即刷新活跃时刻(连续会话不过期,闲置 30 分钟才过期)。"""
        tbl = AffinityTable(ttl_sec=100.0)
        tbl.bind("TH-1", "w-1", "TK-1", now=0.0)
        assert tbl.lookup("TH-1", now=90.0) is not None  # 刷新 → 新基准 90
        assert tbl.lookup("TH-1", now=185.0) is not None  # 距上次活跃 95s < 100,刷新 → 185
        assert tbl.lookup("TH-1", now=286.0) is None  # 距上次活跃 101s > 100 → 过期


class TestRelease:
    def test_release(self):
        tbl = AffinityTable()
        tbl.bind("TH-1", "w-1", "TK-1", now=1.0)
        assert tbl.release("TH-1") is True
        assert tbl.lookup("TH-1", now=2.0) is None
        assert tbl.release("TH-1") is False  # 已不存在

    def test_release_fail_open(self):
        tbl = AffinityTable()
        assert tbl.release(None) is False


class TestTicketStateLinkage:
    """ADR-3 联动: 非 live 态不占槽,亲和必须同步解除。"""

    def test_paused_releases_affinity(self):
        tbl = AffinityTable()
        tbl.bind("TH-1", "w-res-1", "TK-1", now=1000.0)
        tbl.on_ticket_state("TH-1", "paused")
        assert tbl.lookup("TH-1", now=1001.0) is None

    def test_waits_for_person_releases_affinity(self):
        tbl = AffinityTable()
        tbl.bind("TH-1", "w-res-1", "TK-1", now=1000.0)
        tbl.on_ticket_state("TH-1", "waitsForPerson")
        assert tbl.lookup("TH-1", now=1001.0) is None

    def test_ended_releases_affinity(self):
        tbl = AffinityTable()
        tbl.bind("TH-1", "w-res-1", "TK-1", now=1000.0)
        tbl.on_ticket_state("TH-1", "ended")
        assert tbl.lookup("TH-1", now=1001.0) is None

    def test_live_keeps_affinity(self):
        tbl = AffinityTable()
        tbl.bind("TH-1", "w-res-1", "TK-1", now=1000.0)
        tbl.on_ticket_state("TH-1", "live")
        assert tbl.lookup("TH-1", now=1001.0) is not None

    def test_on_ticket_state_fail_open(self):
        tbl = AffinityTable()
        tbl.on_ticket_state(None, "paused")  # 不抛错
        tbl.on_ticket_state("TH-NOPE", "paused")  # 不存在也不抛错


class TestBoundedCapacity:
    def test_evict_lru_when_full(self):
        """容量有界: 满员时逐出最久未活跃绑定(防内存膨胀)。"""
        tbl = AffinityTable(max_entries=3)
        tbl.bind("TH-1", "w-1", "TK-1", now=1.0)
        tbl.bind("TH-2", "w-2", "TK-2", now=2.0)
        tbl.bind("TH-3", "w-3", "TK-3", now=3.0)
        tbl.lookup("TH-1", now=4.0)  # TH-1 刷新活跃 → TH-2 成为最久未用
        tbl.bind("TH-4", "w-4", "TK-4", now=5.0)  # 逐出 TH-2
        assert tbl.size() == 3
        assert tbl.lookup("TH-2", now=6.0) is None
        assert tbl.lookup("TH-1", now=6.0) is not None
        assert tbl.lookup("TH-4", now=6.0) is not None
