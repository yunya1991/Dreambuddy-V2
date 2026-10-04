"""vector_memory_interface 事务纪律单测（P0 修复 2026-09-29）。

背景：生产 polling_trader 经 VectorMemoryInterface 写认知库时，
隐式事务在异常路径下未回滚 → RESERVED 锁长期持有 → 全系统认知写入
（MCP record / daemon 蒸馏）被 "database is locked" 阻断 15+ 分钟。

修复目标（三条硬约束）：
1. 文件库启用 WAL —— 读写不互斥，读不再被写事务阻塞；
2. busy_timeout 显式 ≥ 30s —— 写争用时等待而非立即失败；
3. 所有写方法异常路径必须 rollback —— 事务零泄漏（in_transaction == False）。
"""
import sqlite3
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from vector_memory_interface import VectorMemoryInterface


def _make_file_interface() -> VectorMemoryInterface:
    """临时文件库（WAL 只对文件库生效，:memory: 不适用）。"""
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    return VectorMemoryInterface(storage_path=tmp.name, engine="numpy")


def _make_memory_interface() -> VectorMemoryInterface:
    return VectorMemoryInterface(storage_path=None, engine="numpy")


def test_wal_mode_enabled_on_file_db():
    """文件库连接必须启用 WAL（当前为默认 journal 模式，RED）。"""
    iface = _make_file_interface()
    try:
        mode = iface.db.execute("PRAGMA journal_mode").fetchone()[0]
        assert mode.lower() == "wal", f"journal_mode 应为 wal，实际 {mode}"
    finally:
        iface.db.close()


def test_busy_timeout_at_least_30s():
    """busy_timeout 显式 ≥ 30000ms（当前为 Python 默认 5000ms，RED）。"""
    iface = _make_memory_interface()
    try:
        timeout = iface.db.execute("PRAGMA busy_timeout").fetchone()[0]
        assert timeout >= 30000, f"busy_timeout 应 ≥30000ms，实际 {timeout}ms"
    finally:
        iface.db.close()


class _FailingConnProxy:
    """连接代理：注入失败模拟写路径异常。

    sqlite3.Connection 是 C 实现，execute 属性只读，无法直接
    monkeypatch，故用代理替换 iface.db。

    fail_commit=True 时 commit() 抛异常 —— 精确复现生产事故形态：
    execute 成功（隐式事务已开）→ commit 失败 → 事务泄漏锁全局。
    """

    def __init__(self, conn, fail_commit: bool = True):
        self._conn = conn
        self._fail_commit = fail_commit

    def commit(self):
        if self._fail_commit:
            raise sqlite3.OperationalError("simulated commit failure")
        return self._conn.commit()

    def __getattr__(self, name):
        return getattr(self._conn, name)


def _fail_commit(iface: VectorMemoryInterface):
    """将 iface.db 替换为 commit 必败的代理（execute 正常）。"""
    iface.db = _FailingConnProxy(iface.db, fail_commit=True)


def test_add_rollback_on_failure():
    """add() commit 失败 → 必须回滚，事务不得泄漏（RED）。"""
    iface = _make_memory_interface()
    try:
        _fail_commit(iface)
        try:
            iface.add(content="事务纪律测试", quality_level="C", tags=["test"])
            raise AssertionError("应抛出 OperationalError")
        except sqlite3.OperationalError:
            pass
        assert not iface.db.in_transaction, "异常后事务仍持有 —— 锁泄漏复现"
    finally:
        iface.db.close()


def test_update_quality_rollback_on_failure():
    """update_quality() commit 失败 → 必须回滚（RED）。"""
    iface = _make_memory_interface()
    try:
        mem_id = iface.add(content="待更新记忆", quality_level="C", tags=["test"])
        _fail_commit(iface)
        try:
            iface.update_quality(mem_id, "B", 0.5)
        except sqlite3.OperationalError:
            pass
        assert not iface.db.in_transaction, "update_quality 异常后事务仍持有"
    finally:
        iface.db.close()


def test_delete_rollback_on_failure():
    """delete() commit 失败 → 必须回滚（RED）。"""
    iface = _make_memory_interface()
    try:
        mem_id = iface.add(content="待删除记忆", quality_level="C", tags=["test"])
        _fail_commit(iface)
        try:
            iface.delete(mem_id)
        except sqlite3.OperationalError:
            pass
        assert not iface.db.in_transaction, "delete 异常后事务仍持有"
    finally:
        iface.db.close()


def test_writers_do_not_block_readers_after_wal():
    """WAL 生效后：写事务持有时，另一连接仍可读（集成验证）。"""
    import threading
    import time

    iface = _make_file_interface()
    try:
        iface.add(content="WAL 读写并发验证", quality_level="C", tags=["test"])
        # 另一个连接开写事务但不提交
        blocker = sqlite3.connect(iface.storage_path, timeout=1.0)
        try:
            blocker.execute("BEGIN IMMEDIATE")
            blocker.execute(
                "INSERT INTO memories (id, content, quality_level, confidence, tags,"
                " memory_type, source, created_at, updated_at, verify_count)"
                " VALUES ('VM-blocker', 'x', 'C', 0.1, '[]', 't', '', '', '', 0)"
            )
            # 主连接此时应仍能读到旧数据（WAL 快照读）
            reader = sqlite3.connect(iface.storage_path, timeout=1.0)
            try:
                row = reader.execute("SELECT COUNT(*) FROM memories").fetchone()[0]
                assert row >= 1, "写事务持有时读被阻塞 —— WAL 未生效"
            finally:
                reader.close()
        finally:
            blocker.rollback()
            blocker.close()
    finally:
        iface.db.close()
