"""dreambuddy_dal PG 连接（C4a）。

连接串来源（优先级由高到低）：
1. DAL_PG_URL 环境变量
2. DATABASE_URL 环境变量
3. /etc/dreambuddy-dal.env 中的 DATABASE_URL（存在才读取；luke 可读独立副本）

连接为每操作短连接（与 sqlite_unified 的 get_sqlite_connection 同生命周期语义），
context manager 退出时提交并关闭；异常时回滚。
"""
from __future__ import annotations

import os
from contextlib import contextmanager
from pathlib import Path

_PG_ENV_FALLBACK = "/etc/dreambuddy-dal.env"


def _load_pg_env_fallback() -> None:
    """从 /etc/dreambuddy-dal.env 读取 DATABASE_URL（不覆盖已有 env）。"""
    if os.environ.get("DAL_PG_URL") or os.environ.get("DATABASE_URL"):
        return
    p = Path(_PG_ENV_FALLBACK)
    if not p.exists():
        return
    try:
        for line in p.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line.startswith("DATABASE_URL=") and not os.environ.get("DATABASE_URL"):
                os.environ["DATABASE_URL"] = line.split("=", 1)[1].strip()
    except OSError:
        pass


def get_pg_dsn() -> str:
    """返回 PG 连接串（不回显）。"""
    _load_pg_env_fallback()
    dsn = os.environ.get("DAL_PG_URL") or os.environ.get("DATABASE_URL") or ""
    if not dsn:
        raise RuntimeError(
            "PG DSN 未配置：需要 DAL_PG_URL 或 DATABASE_URL 环境变量"
        )
    return dsn


@contextmanager
def get_pg_connection():
    """PG 短连接 context manager：正常退出 commit+close，异常 rollback+close。"""
    import psycopg2

    conn = psycopg2.connect(get_pg_dsn())
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


__all__ = ["get_pg_connection", "get_pg_dsn"]
