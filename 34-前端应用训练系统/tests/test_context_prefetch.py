# -*- coding: utf-8 -*-
"""投机预取(T-DSH-P3 P3-3) RED 测试。

依据: DESIGN-DSH-ARCH-UPGRADE v0.2 P3·常驻(投机预取: L1 零 token 预取上下文)
+ U7(预取仅 L1 零 token 路径;未命中静默丢弃) + H2(开关默认关)
+ HC-4(零 token: 纯组装,无生成式 LLM——复用 l0_context_assembler)。

断言:
  - 开关默认关
  - prefetch_key 由 trigger 稳定派生(同 thread/kind/source 同键)
  - prefetch → consume 命中返回同一信封;未命中/过期 → None 静默丢弃
  - 命中率可统计(hits/misses/hit_rate)——退出判据「recall 命中率提升可测」口径
  - 容量有界 LRU;坏输入 FAIL-OPEN
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from core.context_prefetch import (  # noqa: E402
    PREFETCH_SWITCH,
    PrefetchCache,
    consume_prefetched,
    is_prefetch_enabled,
    prefetch_context,
    prefetch_key,
)

_TRIG = {"trigger_id": "tg-1", "source": "cognitive", "kind": "mem_ready", "thread_id": "th-1"}


class _FakeL0:
    def __init__(self):
        self.calls = 0

    def fetch_context(self, scope, params):
        self.calls += 1
        return {
            "ok": True,
            "data": {"scope": scope},
            "source": "fake",
            "timestamp": "t",
            "degraded": False,
            "meta": {},
        }


def test_switch_default_off():
    assert is_prefetch_enabled(None) is False
    assert is_prefetch_enabled({}) is False
    assert is_prefetch_enabled({PREFETCH_SWITCH: True}) is True
    assert is_prefetch_enabled("bad") is False


def test_prefetch_key_stable():
    k1 = prefetch_key(_TRIG)
    k2 = prefetch_key(dict(_TRIG, trigger_id="tg-2"))  # trigger_id 不参与键
    assert k1 and k1 == k2
    assert prefetch_key(dict(_TRIG, kind="other")) != k1
    assert prefetch_key(None) is None
    assert prefetch_key({"kind": "x"}) is None  # 缺 source → None


def test_prefetch_then_consume_hit():
    l0 = _FakeL0()
    cache = PrefetchCache(ttl_sec=300.0)
    assert prefetch_context(_TRIG, l0, cache, now=1000.0) is True
    assert l0.calls >= 1  # 真实调了 L0 组六维
    env = consume_prefetched(_TRIG, cache, now=1001.0)
    assert env is not None
    assert env["source"] == "l0_context_assembler"
    assert "six_dims" in env["data"]
    st = cache.stats()
    assert st == {"hits": 1, "misses": 0, "hit_rate": 1.0}


def test_consume_miss_silent_discard():
    cache = PrefetchCache()
    assert consume_prefetched(_TRIG, cache, now=1.0) is None  # U7 静默丢弃
    assert cache.stats() == {"hits": 0, "misses": 1, "hit_rate": 0.0}
    # 空统计 hit_rate 0.0 不除零
    assert PrefetchCache().stats()["hit_rate"] == 0.0


def test_consume_expired_is_miss():
    l0 = _FakeL0()
    cache = PrefetchCache(ttl_sec=10.0)
    prefetch_context(_TRIG, l0, cache, now=100.0)
    assert consume_prefetched(_TRIG, cache, now=111.0) is None
    assert cache.stats()["misses"] == 1


def test_hit_rate_measurable():
    l0 = _FakeL0()
    cache = PrefetchCache(ttl_sec=300.0)
    for i in range(3):
        prefetch_context(dict(_TRIG, trigger_id=f"tg-{i}", kind=f"k{i}"), l0, cache, now=1.0)
    for i in range(2):
        consume_prefetched(dict(_TRIG, kind=f"k{i}"), cache, now=2.0)
    consume_prefetched(dict(_TRIG, kind="absent"), cache, now=2.0)
    st = cache.stats()
    assert st["hits"] == 2 and st["misses"] == 1
    assert abs(st["hit_rate"] - 2 / 3) < 1e-9


def test_cache_capacity_lru():
    cache = PrefetchCache(ttl_sec=300.0, max_entries=2)
    cache.put("a", {"v": 1}, now=1.0)
    cache.put("b", {"v": 2}, now=2.0)
    cache.put("c", {"v": 3}, now=3.0)  # 逐出最久未活跃 a
    assert cache.consume("a", now=4.0) is None
    assert cache.consume("b", now=4.0) == {"v": 2}


def test_fail_open():
    cache = PrefetchCache()
    assert prefetch_context(None, None, cache) is False
    assert prefetch_context(_TRIG, None, cache, now=1.0) is True  # l0 None → 逐维降级信封仍可缓存
    assert consume_prefetched(None, cache) is None
    assert consume_prefetched(_TRIG, None) is None
