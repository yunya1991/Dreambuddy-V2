"""
dreambuddy_dal.connection — SQLite 连接生命周期管理 + 异常分类 + auto_retry_locked
对齐：
- SCHEMA_DESIGN.md §0.2 PRAGMA 配置表（8 条，其中 critical 4 条 ASSERTION 校验）
- TECHNICAL_DESIGN.md §4.2 异常分类矩阵（BUSY / CONSTRAINT / CORRUPT / IO_ERROR / OTHER）
- TECHNICAL_DESIGN.md §4.3 auto_retry_locked 指数退避：0.1s / 0.3s / 0.9s 三次重试
"""
from __future__ import annotations

import functools
import os
import sqlite3
import time
from contextlib import contextmanager
from decimal import Decimal
from enum import Enum
from typing import Callable, Iterator, Optional, TypeVar

_T = TypeVar("_T")


# ---------------------------------------------------------------------------
# 5 类异常分类（TECHNICAL_DESIGN §4.2 表）
# ---------------------------------------------------------------------------

class SQLiteErrorCategory(str, Enum):
    BUSY = "BUSY"               # 并发写冲突：database is locked → Fail-Open（双写场景不阻塞）
    CONSTRAINT = "CONSTRAINT"   # UNIQUE / FK / CHECK 冲突 → Fail-Closed（返回 False 不重试）
    CORRUPT = "CORRUPT"         # DB 损坏 malformed → 立即 Kill-Switch 切 json_legacy + 飞书 CRITICAL
    IO_ERROR = "IO_ERROR"       # 磁盘 IO / 权限 / 无空间 → 告警 + 重试 1 次
    OTHER = "OTHER"             # 兜底：未分类 → 抛原异常


def classify_sqlite_exception(exc: BaseException) -> SQLiteErrorCategory:
    """按异常类型 + error message 关键词匹配 → SQLiteErrorCategory"""
    msg = str(exc).lower()

    if isinstance(exc, (sqlite3.OperationalError, sqlite3.DatabaseError)):
        if "locked" in msg or "busy" in msg:
            return SQLiteErrorCategory.BUSY
        if "malformed" in msg or "corrupt" in msg or "not a database" in msg:
            return SQLiteErrorCategory.CORRUPT
        if "disk i/o" in msg or "read-only" in msg or "no space" in msg or "permission" in msg:
            return SQLiteErrorCategory.IO_ERROR
    if isinstance(exc, sqlite3.IntegrityError):
        # UNIQUE / FK / CHECK 全算 CONSTRAINT
        return SQLiteErrorCategory.CONSTRAINT
    if isinstance(exc, sqlite3.OperationalError):
        return SQLiteErrorCategory.IO_ERROR

    return SQLiteErrorCategory.OTHER


# ---------------------------------------------------------------------------
# auto_retry_locked：BUSY 指数退避装饰器（仅 BUSY 重试，其它异常直通）
# ---------------------------------------------------------------------------

def auto_retry_locked(max_retries: int = 3, backoff_ms: tuple = (100, 300, 900)):
    """
    @auto_retry_locked 或 @auto_retry_locked(max_retries=3, backoff_ms=(100,300,900))
    支持两种调用：
      - @auto_retry_locked           → max_retries 被传为 fn（callable），自动识别
      - @auto_retry_locked(...)      → 显式传参
    仅当 classify == BUSY 才 retry；其它异常立刻抛出不重试。
    """
    # 处理无括号场景：@auto_retry_locked 直接装饰 → 第一个参数是 fn（callable）
    if callable(max_retries) and isinstance(backoff_ms, tuple) and backoff_ms == (100, 300, 900):
        fn = max_retries
        return _build_wrapper(fn, max_retries=3, backoff_ms=backoff_ms)

    # 正常带参数场景
    def decorator(fn: Callable[..., _T]) -> Callable[..., _T]:
        return _build_wrapper(fn, max_retries=max_retries, backoff_ms=backoff_ms)
    return decorator


def _build_wrapper(fn: Callable[..., _T], max_retries: int, backoff_ms: tuple) -> Callable[..., _T]:
    assert len(backoff_ms) >= max_retries, "backoff_ms 长度 < max_retries"

    @functools.wraps(fn)
    def wrapper(*args, **kwargs) -> _T:
        last_exc: Optional[BaseException] = None
        for attempt in range(max_retries + 1):  # 0..max_retries = 1 次正跑 + max_retries 次重试
            try:
                return fn(*args, **kwargs)
            except (sqlite3.OperationalError, sqlite3.DatabaseError) as e:
                cat = classify_sqlite_exception(e)
                last_exc = e
                if cat != SQLiteErrorCategory.BUSY:
                    raise  # 非 BUSY 直通不重试
                # BUSY：还剩尝试次数 → sleep
                if attempt < max_retries:
                    time.sleep(backoff_ms[attempt] / 1000.0)
                    continue
                # 重试耗尽 → 抛原异常
                raise
        # unreachable
        if last_exc:
            raise last_exc
        raise RuntimeError("unreachable in auto_retry_locked")
    return wrapper


# ---------------------------------------------------------------------------
# PRAGMA 配置（SCHEMA_DESIGN §0.2 表）
# ---------------------------------------------------------------------------

# 连接后立刻按顺序 PRAGMA（critical 4 条后有断言）
_DEFAULT_PRAGMAS: tuple[tuple[str, Optional[int]], ...] = (
    # ─── critical（ASSERTION 校验）───
    ("journal_mode=WAL", None),       # 写前日志，并发读不阻塞
    ("foreign_keys=ON", 1),           # FK 约束开启
    ("busy_timeout=5000", 5000),      # 5s busy_timeout（与 fcntl 旧机制共存）
    ("synchronous=NORMAL", 1),        # NORMAL = 只在 CHECKPOINT 时 fsync（WAL 场景安全平衡性能）
    # ─── performance（可接受小差异，不 assertion）───
    ("temp_store=MEMORY", 2),         # 临时表全内存
    ("mmap_size=268435456", 268435456),  # 256MB 内存映射（读性能 ↑）
    ("cache_size=-20000", None),      # 20MB 页缓存（负值=KB）
    ("soft_heap_limit=134217728", None), # 128MB 软内存上限（防止极端 SQL 撑爆）
)


def _apply_pragmas(conn: sqlite3.Connection, *, assert_critical: bool = True) -> None:
    """按顺序执行 8 条 PRAGMA；对 critical 4 条回读断言（SCHEMA_DESIGN §0.2）。"""
    for stmt, _expected in _DEFAULT_PRAGMAS:
        conn.execute(f"PRAGMA {stmt};")
    # 断言 critical
    if assert_critical:
        checks = [
            ("journal_mode", lambda r: r[0].lower() == "wal"),
            ("foreign_keys", lambda r: r[0] == 1),
            ("busy_timeout", lambda r: r[0] == 5000),
            ("synchronous", lambda r: r[0] == 1),
        ]
        for pragma_name, predicate in checks:
            row = conn.execute(f"PRAGMA {pragma_name}").fetchone()
            if not predicate(row):
                raise AssertionError(
                    f"CRITICAL PRAGMA {pragma_name} 设置失败：期望值≠实际值，row={row}"
                )


# ---------------------------------------------------------------------------
# 对外主入口：get_sqlite_connection 上下文管理器
# ---------------------------------------------------------------------------

@contextmanager
def get_sqlite_connection(
    db_path: str,
    *,
    check_same_thread: bool = False,
    timeout: float = 10.0,
    apply_pragmas: bool = True,
    assert_critical_pragmas: bool = True,
) -> Iterator[sqlite3.Connection]:
    """
    SQLite 连接工厂：每次 with 返回一个连接；__exit__ 自动 commit+close。
    """
    # 父目录不存在则创建
    parent = os.path.dirname(os.path.abspath(db_path))
    os.makedirs(parent, exist_ok=True)

    conn = sqlite3.connect(
        db_path,
        check_same_thread=check_same_thread,
        timeout=timeout,
        isolation_level=None,  # 自动提交关闭；业务层显式 BEGIN / COMMIT
    )
    # Decimal 适配：SELECT 时 REAL → Decimal（精度保护），TEXT 也当 Decimal
    sqlite3.register_adapter(Decimal, lambda d: str(d))
    sqlite3.register_converter("DECIMAL", lambda b: Decimal(b.decode("utf-8")))

    try:
        if apply_pragmas:
            _apply_pragmas(conn, assert_critical=assert_critical_pragmas)
        yield conn
        # 正常结束：commit
        conn.commit()
    except BaseException:
        conn.rollback()
        raise
    finally:
        conn.close()


__all__ = [
    "SQLiteErrorCategory", "classify_sqlite_exception",
    "auto_retry_locked", "get_sqlite_connection",
]
