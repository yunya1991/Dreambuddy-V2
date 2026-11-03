# -*- coding: utf-8 -*-
"""dreambuddy_dal.conn_limit — 19-DAL 连接上限治理(ALIGNMENT-46-47 B3, 47-P1 前置)。

背景: stdio 壳 1 宿主 = 1 壳进程 = N×DB 连接;ADR-10/G2 进程级按域共享单壳后
连接数 = 域数,但跨进程(云端/本地)与既有直连调用方仍可能放大连接。本模块在
DAL 层提供有界信号量上限——连接治理唯一落点(SPEC-L0-MCP-PACKAGING §3.1:
壳内禁止自建连接池,治理下沉 19-DAL)。

规约:
  - 上限值: env DAL_MAX_CONNECTIONS,默认 8;0/非法值 → default_limiter() 返回
    None(显式不启用),不抛错。
  - 超限语义: 明确拒绝,抛 ConnectionLimitExceeded(非静默排队到永远);
    timeout 参数控制等待窗口,timeout=0 立即判定。
  - 接入方式: 连接工厂可选参数 limiter=None(默认不接,既有行为字节等价)。
"""

from __future__ import annotations

import os
import threading
from contextlib import contextmanager
from typing import Iterator, Optional

_DEFAULT_MAX = 8
_ENV_KEY = "DAL_MAX_CONNECTIONS"


class ConnectionLimitExceeded(RuntimeError):
    """连接数达上限且等待超时 → 明确拒绝(非静默降级/排队)。"""


class ConnectionLimiter:
    """进程级连接有界信号量。线程安全;release 必须配对 acquire。"""

    def __init__(self, max_connections: int):
        if (
            not isinstance(max_connections, int)
            or isinstance(max_connections, bool)
            or max_connections <= 0
        ):
            raise ValueError("max_connections 必须为正整数, got %r" % (max_connections,))
        self._max = max_connections
        self._sem = threading.BoundedSemaphore(max_connections)
        self._lock = threading.Lock()
        self._in_use = 0

    @property
    def max_connections(self) -> int:
        return self._max

    @property
    def in_use(self) -> int:
        with self._lock:
            return self._in_use

    def acquire(self, timeout: Optional[float] = None) -> bool:
        """占一个连接槽;超时未得 → ConnectionLimitExceeded(明确拒绝)。"""
        ok = self._sem.acquire(timeout=timeout) if timeout is not None else self._sem.acquire()
        if not ok:
            raise ConnectionLimitExceeded("DAL 连接数达上限(%d),acquire 超时拒绝" % self._max)
        with self._lock:
            self._in_use += 1
        return True

    def release(self) -> None:
        """释放一个槽。未配对 release → BoundedSemaphore ValueError。"""
        self._sem.release()
        with self._lock:
            self._in_use -= 1


@contextmanager
def limited_connection_guard(
    limiter: ConnectionLimiter, timeout: Optional[float] = None
) -> Iterator[None]:
    """acquire→yield→finally release 的对称守卫。"""
    limiter.acquire(timeout=timeout)
    try:
        yield
    finally:
        limiter.release()


def default_limiter() -> Optional[ConnectionLimiter]:
    """按 env 构造默认 limiter。

    DAL_MAX_CONNECTIONS 未设 → 默认 8;0 或非法值 → None(显式不启用)。
    """
    raw = os.environ.get(_ENV_KEY)
    if raw is None:
        return ConnectionLimiter(_DEFAULT_MAX)
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return None
    if value <= 0:
        return None
    return ConnectionLimiter(value)


__all__ = [
    "ConnectionLimiter",
    "ConnectionLimitExceeded",
    "limited_connection_guard",
    "default_limiter",
]
