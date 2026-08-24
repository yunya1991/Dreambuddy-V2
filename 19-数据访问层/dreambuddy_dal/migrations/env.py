"""
Alembic env.py — 19-数据访问层

使用 SQLAlchemy engine（Alembic 原生兼容），PRAGMA 在 connect 后执行。
"""
from __future__ import annotations

import os
import sys
from logging.config import fileConfig

from alembic import context
from sqlalchemy import create_engine, event

# 确保 dreambuddy_dal 可导入
this_dir = os.path.dirname(os.path.abspath(__file__))
parent = os.path.dirname(this_dir)       # dreambuddy_dal/
project_root = os.path.dirname(parent)   # 19-数据访问层/
for p in (parent, project_root):
    if p not in sys.path:
        sys.path.insert(0, p)

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = None


def get_db_path() -> str:
    data_dir = os.environ.get("DATA_DIR", "./data")
    return os.environ.get(
        "DAL_DB_PATH",
        os.path.join(data_dir, "dreambuddy_core.db"),
    )


def _apply_sqlite_pragmas(dbapi_conn, conn_record):
    """PRAGMA 对齐 connection.py 8 条 critical。"""
    cursor = dbapi_conn.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.execute("PRAGMA busy_timeout=5000")
    cursor.execute("PRAGMA synchronous=NORMAL")
    cursor.close()


def run_migrations_offline() -> None:
    url = f"sqlite:///{get_db_path()}"
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    db_path = get_db_path()
    url = f"sqlite:///{db_path}"
    connectable = create_engine(url, future=True)
    event.listen(connectable, "connect", _apply_sqlite_pragmas)

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
