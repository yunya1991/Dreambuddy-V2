# -*- coding: utf-8 -*-
"""投机预取(T-DSH-P3 P3-3)。

依据: DESIGN-DSH-ARCH-UPGRADE v0.2 P3·常驻(投机预取: L1 零 token 预取上下文)
+ U7(预取仅 L1 零 token 路径;未命中静默丢弃) + H2(开关默认关)
+ HC-4(零 token: 纯组装,无生成式 LLM——复用 l0_context_assembler)
+ 退出判据(同类事件 recall 命中率提升可测 → hits/misses/hit_rate 口径)。

定位: 事件到达 L1 分流时,投机地把六维上下文信封提前组装进 TTL 缓存;
后续同 (source, kind, thread_id) 事件真实需要时 consume 命中即用,
未命中/过期 → None 静默丢弃(预取作废零副作用)。纯内存运行时缓存
(非权威状态,ADR-2;丢失仅退化为现场组装)。

硬约束:
  HC-1 FAIL-OPEN: 坏输入 → False/None,不抛错
  HC-2 开关 enable_context_prefetch 默认 False
  HC-4 零 token: 只调 L0 fetch_context 组装,无生成式 LLM
  容量有界: max_entries 满员逐出最久未活跃项(LRU)
"""

from __future__ import annotations

import time
from typing import Any, Dict, Optional

from .l0_context_assembler import build_six_dim_context

# 模块化开关(HC-2,默认 False)
PREFETCH_SWITCH = "enable_context_prefetch"

# 预取缓存 TTL(短于亲和 TTL——预取是投机,过期即作废)
DEFAULT_TTL_SEC = 300.0

# 容量上限(防事件风暴撑爆内存;逐出最久未活跃)
DEFAULT_MAX_ENTRIES = 1024


def is_prefetch_enabled(flags: Optional[Dict[str, Any]] = None) -> bool:
    """模块化开关读取(HC-2)。flags 非 dict / 缺键 → False(默认关)。"""
    try:
        if not isinstance(flags, dict):
            return False
        return bool(flags.get(PREFETCH_SWITCH, False))
    except Exception:
        return False


def prefetch_key(raw_trigger: Any) -> Optional[str]:
    """由 trigger 派生稳定缓存键: source|kind|thread_id。

    trigger_id 不参与(每次事件唯一);同 source+kind+thread 的后续事件
    命中同一预取。缺 source/kind → None(FAIL-OPEN)。
    """
    try:
        if not isinstance(raw_trigger, dict):
            return None
        source = raw_trigger.get("source")
        kind = raw_trigger.get("kind")
        if not source or not kind:
            return None
        return "%s|%s|%s" % (source, kind, raw_trigger.get("thread_id"))
    except Exception:
        return None


class PrefetchCache:
    """key → {envelope, ts} 投机缓存(TTL + LRU + 命中统计)。

    consume 命中即取出(一次性投机,消费后不再占用);过期按未命中计。
    stats() 提供命中率口径(HC: 空统计 hit_rate=0.0 不除零)。
    """

    def __init__(
        self,
        ttl_sec: float = DEFAULT_TTL_SEC,
        max_entries: int = DEFAULT_MAX_ENTRIES,
    ) -> None:
        try:
            self._ttl = float(ttl_sec)
        except (TypeError, ValueError):
            self._ttl = DEFAULT_TTL_SEC
        try:
            self._max = int(max_entries)
        except (TypeError, ValueError):
            self._max = DEFAULT_MAX_ENTRIES
        if self._max < 1:
            self._max = 1
        self._items: Dict[str, Dict[str, Any]] = {}
        self._hits = 0
        self._misses = 0

    def size(self) -> int:
        return len(self._items)

    def put(self, key: Any, envelope: Any, now: Optional[float] = None) -> bool:
        """写入预取信封。坏输入 → False(FAIL-OPEN)。"""
        try:
            if not key or not isinstance(envelope, dict):
                return False
            ts = float(now) if now is not None else time.time()
            k = str(key)
            if k not in self._items and len(self._items) >= self._max:
                self._evict_lru()
            self._items[k] = {"envelope": envelope, "ts": ts}
            return True
        except Exception:
            return False

    def consume(self, key: Any, now: Optional[float] = None) -> Optional[Dict[str, Any]]:
        """取出预取信封: 命中未过期 → envelope(hits+1);未命中/过期 → None(misses+1)。"""
        try:
            if not key:
                return None
            k = str(key)
            entry = self._items.get(k)
            if entry is None:
                self._misses += 1
                return None
            ts = float(now) if now is not None else time.time()
            if (ts - entry["ts"]) > self._ttl:
                del self._items[k]  # 过期驱逐
                self._misses += 1
                return None
            del self._items[k]  # 一次性消费
            self._hits += 1
            return entry["envelope"]
        except Exception:
            return None

    def stats(self) -> Dict[str, Any]:
        """命中率口径(退出判据: recall 命中率提升可测)。"""
        total = self._hits + self._misses
        return {
            "hits": self._hits,
            "misses": self._misses,
            "hit_rate": (self._hits / total) if total else 0.0,
        }

    def _evict_lru(self) -> None:
        try:
            if not self._items:
                return
            oldest = min(self._items, key=lambda k: self._items[k]["ts"])
            del self._items[oldest]
        except Exception:
            return


def prefetch_context(
    raw_trigger: Any,
    l0: Optional[Any],
    cache: Optional[Any],
    now: Optional[float] = None,
    trace_id: Optional[str] = None,
) -> bool:
    """投机预取: 组六维信封(零 token)→ 写缓存。l0=None 时逐维降级信封仍可缓存。"""
    try:
        if cache is None or not hasattr(cache, "put"):
            return False
        key = prefetch_key(raw_trigger)
        if key is None:
            return False
        envelope = build_six_dim_context(raw_trigger, l0=l0, trace_id=trace_id)
        if not isinstance(envelope, dict):
            return False
        return cache.put(key, envelope, now=now)
    except Exception:
        return False


def consume_prefetched(
    raw_trigger: Any,
    cache: Optional[Any],
    now: Optional[float] = None,
) -> Optional[Dict[str, Any]]:
    """消费预取: 命中 → 六维信封;未命中/过期 → None(U7 静默丢弃)。"""
    try:
        if cache is None or not hasattr(cache, "consume"):
            return None
        key = prefetch_key(raw_trigger)
        if key is None:
            return None
        return cache.consume(key, now=now)
    except Exception:
        return None
