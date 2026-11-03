# -*- coding: utf-8 -*-
"""RED: 19-DAL 连接上限(ALIGNMENT-46-47 B3, P1 前置)。

业务逻辑断言(非仅导入):
  ConnectionLimiter 有界信号量语义、超限明确拒绝(非静默排队)、
  release 复用、guard 上下文计数对称、default_limiter env 规约、
  两个连接工厂可选 limiter 接入且 limiter=None 字节等价。
"""

from __future__ import annotations

import threading
import time

import pytest

from dreambuddy_dal.conn_limit import (
    ConnectionLimiter,
    ConnectionLimitExceeded,
    default_limiter,
    limited_connection_guard,
)
from dreambuddy_dal.connection import get_sqlite_connection

# ---------------------------------------------------------------------------
# ConnectionLimiter 基础语义
# ---------------------------------------------------------------------------


class TestConnectionLimiter:
    def test_acquire_within_limit(self):
        lim = ConnectionLimiter(2)
        assert lim.acquire(timeout=0) is True
        assert lim.acquire(timeout=0) is True
        assert lim.in_use == 2

    def test_over_limit_rejected_immediately(self):
        """超限 → 明确拒绝(抛 ConnectionLimitExceeded),不静默排队。"""
        lim = ConnectionLimiter(1)
        assert lim.acquire(timeout=0) is True
        with pytest.raises(ConnectionLimitExceeded):
            lim.acquire(timeout=0)

    def test_release_frees_slot(self):
        lim = ConnectionLimiter(1)
        lim.acquire(timeout=0)
        lim.release()
        assert lim.in_use == 0
        assert lim.acquire(timeout=0) is True

    def test_release_without_acquire_raises(self):
        lim = ConnectionLimiter(1)
        with pytest.raises(ValueError):
            lim.release()

    def test_invalid_max_raises(self):
        """上限必须为正整数;0/负数/非int → ValueError(配置错误不静默)。"""
        for bad in (0, -1, "8", None, 2.5):
            with pytest.raises(ValueError):
                ConnectionLimiter(bad)  # type: ignore[arg-type]

    def test_concurrent_over_limit(self):
        """并发抢:上限 2,4 线程同时 acquire(timeout=0.2) → 恰好 2 成功 2 拒。"""
        lim = ConnectionLimiter(2)
        results = {"ok": 0, "rejected": 0}
        lock = threading.Lock()

        def worker():
            try:
                lim.acquire(timeout=0.2)
                with lock:
                    results["ok"] += 1
                time.sleep(0.3)  # 持槽足够久,让其余线程超时
                lim.release()
            except ConnectionLimitExceeded:
                with lock:
                    results["rejected"] += 1

        threads = [threading.Thread(target=worker) for _ in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert results["ok"] == 2
        assert results["rejected"] == 2


# ---------------------------------------------------------------------------
# limited_connection_guard
# ---------------------------------------------------------------------------


class TestGuard:
    def test_guard_acquire_release_symmetric(self):
        lim = ConnectionLimiter(1)
        with limited_connection_guard(lim, timeout=0):
            assert lim.in_use == 1
        assert lim.in_use == 0

    def test_guard_releases_on_exception(self):
        lim = ConnectionLimiter(1)
        with pytest.raises(RuntimeError):
            with limited_connection_guard(lim, timeout=0):
                raise RuntimeError("boom")
        assert lim.in_use == 0

    def test_guard_over_limit_raises(self):
        lim = ConnectionLimiter(1)
        lim.acquire(timeout=0)
        with pytest.raises(ConnectionLimitExceeded):
            with limited_connection_guard(lim, timeout=0):
                pass
        lim.release()


# ---------------------------------------------------------------------------
# default_limiter env 规约
# ---------------------------------------------------------------------------


class TestDefaultLimiter:
    def test_env_unset_returns_limiter_default_8(self, monkeypatch):
        monkeypatch.delenv("DAL_MAX_CONNECTIONS", raising=False)
        lim = default_limiter()
        assert isinstance(lim, ConnectionLimiter)

    def test_env_custom_value(self, monkeypatch):
        monkeypatch.setenv("DAL_MAX_CONNECTIONS", "3")
        lim = default_limiter()
        assert isinstance(lim, ConnectionLimiter)
        for _ in range(3):
            assert lim.acquire(timeout=0) is True
        with pytest.raises(ConnectionLimitExceeded):
            lim.acquire(timeout=0)

    def test_env_zero_disables(self, monkeypatch):
        """DAL_MAX_CONNECTIONS=0 → 显式禁用,返回 None(不启用上限)。"""
        monkeypatch.setenv("DAL_MAX_CONNECTIONS", "0")
        assert default_limiter() is None

    def test_env_invalid_disables(self, monkeypatch):
        """非法值(非数字/负数) → None(不启用),不崩。"""
        monkeypatch.setenv("DAL_MAX_CONNECTIONS", "abc")
        assert default_limiter() is None
        monkeypatch.setenv("DAL_MAX_CONNECTIONS", "-2")
        assert default_limiter() is None


# ---------------------------------------------------------------------------
# 工厂接入: get_sqlite_connection(limiter=...)
# ---------------------------------------------------------------------------


class TestFactoryIntegration:
    def test_sqlite_factory_without_limiter_unchanged(self, tmp_path):
        """limiter=None(默认) → 行为与现状字节等价(可正常拿连接)。"""
        db = tmp_path / "t.db"
        with get_sqlite_connection(str(db)) as conn:
            assert conn.execute("SELECT 1").fetchone()[0] == 1

    def test_sqlite_factory_respects_limiter(self, tmp_path):
        db = tmp_path / "t.db"
        lim = ConnectionLimiter(1)
        lim.acquire(timeout=0)  # 占满
        try:
            with pytest.raises(ConnectionLimitExceeded):
                with get_sqlite_connection(str(db), limiter=lim, limiter_timeout=0):
                    pass
        finally:
            lim.release()

    def test_sqlite_factory_releases_slot_after_use(self, tmp_path):
        db = tmp_path / "t.db"
        lim = ConnectionLimiter(1)
        with get_sqlite_connection(str(db), limiter=lim, limiter_timeout=0) as conn:
            assert lim.in_use == 1
            assert conn is not None
        assert lim.in_use == 0
