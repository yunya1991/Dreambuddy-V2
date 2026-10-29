"""
db.py — PostgreSQL 连接池与 schema 版本管理
============================================
SPEC-41-文件索引系统 v0.6 §4.1（存储层 PostgreSQL 迁移）
职责：
  1. 读取 config/database.yaml 连接配置（环境变量注入，密码不落盘）
  2. psycopg_pool 连接池（进程内池化，min=1/max=10）
  3. schema 版本校验（meta.schema_version）——不兼容触发全量重建，兼容走增量迁移
设计原则（对齐 SPEC §1.3）：
  1. 轻量可控：复用 dreambuddy-pg 实例，独立 fis 数据库
  2. FAIL-OPEN：连接失败返回明确异常，由上层降级处理（对齐 §5.5/§11）
位置: 41-文件索引系统/core/db.py
"""
from __future__ import annotations
import os
import re
import threading
from pathlib import Path
from typing import Optional

import yaml
from psycopg_pool import ConnectionPool

# 当前代码对应的 schema 版本（与 config/schema.sql 中 meta 初始值一致）
SCHEMA_VERSION = "0.6"

_ENV_PATTERN = re.compile(r"\$\{([A-Z_]+)(?::([^}]*))?\}")


def _resolve_env(value: str) -> str:
    """解析 ${VAR} / ${VAR:default} 形式的环境变量引用。"""
    def _sub(m: re.Match) -> str:
        var, default = m.group(1), m.group(2)
        return os.environ.get(var, default if default is not None else "")
    return _ENV_PATTERN.sub(_sub, value)


class Database:
    """PostgreSQL 连接池单例管理器。

    用法::
        db = Database()          # 读取 config/database.yaml
        db.initialize()          # 建池 + schema 校验
        with db.connection() as conn:
            ...
    """

    _instance: Optional["Database"] = None
    _lock = threading.Lock()

    def __init__(self, config_path: Optional[str] = None) -> None:
        project_root = Path(__file__).resolve().parent.parent
        self.config_path = Path(config_path) if config_path else project_root / "config" / "database.yaml"
        cfg = yaml.safe_load(self.config_path.read_text(encoding="utf-8"))
        self.host = _resolve_env(cfg["host"])
        self.port = int(_resolve_env(str(cfg["port"])))
        self.database = _resolve_env(cfg["database"])
        self.user = _resolve_env(cfg["user"])
        self.password = _resolve_env(cfg["password"])
        pool_cfg = cfg.get("pool", {})
        self.pool_min = int(pool_cfg.get("min_size", 1))
        self.pool_max = int(pool_cfg.get("max_size", 10))
        opts = cfg.get("options", {})
        self.connect_timeout = int(opts.get("connect_timeout", 5))
        self.fail_open = bool(opts.get("fail_open", True))
        self.schema_file = Path(opts.get("schema_file", "config/schema.sql"))
        if not self.schema_file.is_absolute():
            self.schema_file = project_root / self.schema_file
        self._pool: Optional[ConnectionPool] = None

    @classmethod
    def instance(cls) -> "Database":
        """进程内单例（多模块共享同一连接池）。"""
        with cls._lock:
            if cls._instance is None:
                cls._instance = cls()
            return cls._instance

    # ---------- 连接池 ----------

    def initialize(self) -> None:
        """创建连接池并执行 schema 校验。幂等。"""
        if self._pool is not None:
            return
        conninfo = (
            f"host={self.host} port={self.port} dbname={self.database} "
            f"user={self.user} password={self.password} "
            f"connect_timeout={self.connect_timeout}"
        )
        self._pool = ConnectionPool(
            conninfo=conninfo,
            min_size=self.pool_min,
            max_size=self.pool_max,
            timeout=self.connect_timeout,
            open=True,
        )
        self._check_schema()

    def connection(self):
        """从池中获取连接（上下文管理器）。"""
        if self._pool is None:
            self.initialize()
        return self._pool.connection()

    def close(self) -> None:
        """关闭连接池（进程退出时调用）。"""
        if self._pool is not None:
            self._pool.close()
            self._pool = None

    # ---------- schema 版本管理（SPEC v0.6 §4.1） ----------

    def _check_schema(self) -> None:
        """校验 meta.schema_version：
        - 表不存在或版本为空 → 执行 schema.sql 初始化
        - 版本一致 → 通过
        - 版本不一致 → 由上层 rebuild() 决定（此处仅返回版本号）
        """
        with self.connection() as conn:
            exists = conn.execute(
                "SELECT 1 FROM information_schema.tables "
                "WHERE table_schema='public' AND table_name='meta'"
            ).fetchone()
            if not exists:
                self._apply_schema_sql(conn)
                return
            row = conn.execute(
                "SELECT value FROM meta WHERE key='schema_version'"
            ).fetchone()
            if row is None:
                self._apply_schema_sql(conn)

    def _apply_schema_sql(self, conn) -> None:
        """在事务内执行 schema.sql（DDL 事务，失败自动回滚）。"""
        sql = self.schema_file.read_text(encoding="utf-8")
        with conn.transaction():
            conn.execute(sql)

    def query_files(self, root=None, type=None, limit=500):
        """L1 元数据清单查询（A1，SPEC §5.6）。

        - root：根目录名前缀过滤（如 '0-系统文档管理'）
        - type：文件类型过滤
        - 返回：[{path, type, size, indexed_at}, ...]
        """
        sql = "SELECT path, type, size, indexed_at FROM files"
        conds, params = [], []
        if root:
            conds.append("path LIKE %s")
            params.append(root.rstrip("/") + "/%")
        if type:
            conds.append("type = %s")
            params.append(type)
        if conds:
            sql += " WHERE " + " AND ".join(conds)
        sql += " ORDER BY path LIMIT %s"
        params.append(int(limit))
        with self.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(sql, params)
                cols = [d[0] for d in cur.description]
                return [dict(zip(cols, row)) for row in cur.fetchall()]

    def schema_version(self) -> str:
        """返回当前库中记录的 schema 版本（status() 暴露）。"""
        with self.connection() as conn:
            row = conn.execute(
                "SELECT value FROM meta WHERE key='schema_version'"
            ).fetchone()
            return row[0] if row else ""
