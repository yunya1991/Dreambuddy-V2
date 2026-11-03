# -*- coding: utf-8 -*-
"""Thread 亲和表 + TTL 直通(T-DSH-P1 P1-2)。

依据: DESIGN-DSH-ARCH-UPGRADE v0.2 ADR-3 修订(thread_id + 续跑锚点——同一
Thread 的后续事件直接送原 Worker,不经 Router) + P1 交付物(Thread 亲和直通:
亲和表+TTL) + DD3(TTL 初值 30 分钟) + ADR-3(paused/waitsForPerson 释放
Worker 槽,亲和绑定必须同步解除,否则直通指向空槽)。

定位: 纯内存运行时缓存(非权威状态——权威 Ticket 状态在 L0,ADR-2;亲和表
丢失仅退化为走 Router 分派,不产生状态分歧)。事件带 thread_id 时先查亲和:
命中且未过期 → 直通原 Worker;未命中/过期/已解除 → None,由 Router 分派。

硬约束:
  HC-1 FAIL-OPEN: 坏输入 → False/None,不抛错
  HC-2 开关 enable_thread_affinity 默认 False
  容量有界: max_entries 满员逐出最久未活跃绑定(LRU),防内存膨胀
"""

from __future__ import annotations

import time
from typing import Any, Dict, Optional

# 模块化开关(HC-2,默认 False)
AFFINITY_SWITCH = "enable_thread_affinity"

# DD3: TTL 初值 30 分钟(按实测命中率调)
DEFAULT_TTL_SEC = 1800.0

# 容量上限(防长尾 Thread 无限膨胀;逐出策略 = 最久未活跃)
DEFAULT_MAX_ENTRIES = 4096

# 释放 Worker 槽的状态(ADR-3): 进入这些态亲和同步解除
_RELEASE_STATES = {"paused", "waitsForPerson", "ended"}


def is_affinity_enabled(flags: Optional[Dict[str, Any]] = None) -> bool:
    """模块化开关读取(HC-2)。flags 非 dict / 缺键 → False(默认关)。"""
    try:
        if not isinstance(flags, dict):
            return False
        return bool(flags.get(AFFINITY_SWITCH, False))
    except Exception:
        return False


class AffinityTable:
    """thread_id → {worker_id, ticket_id, last_ts} 纯内存亲和表。

    lookup 命中即刷新活跃时刻(连续会话不过期,闲置超过 TTL 才过期);
    过期 lookup 返回 None 并驱逐。表容量有界,满员逐出最久未活跃绑定。
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
        self._binds: Dict[str, Dict[str, Any]] = {}

    def size(self) -> int:
        return len(self._binds)

    def bind(
        self,
        thread_id: Any,
        worker_id: Any,
        ticket_id: Any,
        now: Optional[float] = None,
    ) -> bool:
        """建立/刷新亲和绑定。坏输入 → False(FAIL-OPEN)。"""
        try:
            if not thread_id or not worker_id or not ticket_id:
                return False
            ts = float(now) if now is not None else time.time()
            key = str(thread_id)
            if key not in self._binds and len(self._binds) >= self._max:
                self._evict_lru()
            self._binds[key] = {
                "worker_id": str(worker_id),
                "ticket_id": str(ticket_id),
                "last_ts": ts,
            }
            return True
        except Exception:
            return False

    def lookup(self, thread_id: Any, now: Optional[float] = None) -> Optional[Dict[str, Any]]:
        """查亲和: 命中未过期 → {worker_id, ticket_id} 并刷新活跃;未命中/过期 → None。"""
        try:
            if not thread_id:
                return None
            key = str(thread_id)
            entry = self._binds.get(key)
            if entry is None:
                return None
            ts = float(now) if now is not None else time.time()
            if (ts - entry["last_ts"]) > self._ttl:
                del self._binds[key]  # 过期驱逐
                return None
            entry["last_ts"] = ts  # 命中刷新活跃
            return {"worker_id": entry["worker_id"], "ticket_id": entry["ticket_id"]}
        except Exception:
            return None

    def release(self, thread_id: Any) -> bool:
        """显式解除绑定。不存在/坏输入 → False。"""
        try:
            if not thread_id:
                return False
            return self._binds.pop(str(thread_id), None) is not None
        except Exception:
            return False

    def on_ticket_state(self, thread_id: Any, state: Any) -> None:
        """ADR-3 联动: Ticket 进入 paused/waitsForPerson/ended → 解除亲和(不占槽)。"""
        try:
            if not thread_id:
                return
            if state in _RELEASE_STATES:
                self._binds.pop(str(thread_id), None)
        except Exception:
            return

    def _evict_lru(self) -> None:
        """逐出最久未活跃绑定(容量有界)。"""
        try:
            if not self._binds:
                return
            oldest = min(self._binds, key=lambda k: self._binds[k]["last_ts"])
            del self._binds[oldest]
        except Exception:
            return
