"""
SqliteConfigRepository：SQLite Unified 配置版本实现
--------------------------------------------------------
Protocol ↔ schema_init 的字段映射：
| Protocol                          | schema cv_config_versions              | 说明                     |
|-----------------------------------|----------------------------------------|-------------------------|
| config_name: str                  | config_family TEXT                     | CHECK 枚举同            |
| version: int (create 返回单调+)   | version TEXT (PK, 格式 "v{int}")        | 前缀 v+int 互转         |
| config_data: Dict                 | payload_json TEXT                      | json.dumps / json.loads |
| description: Optional[str]        | changelog TEXT                         |                         |
| created_by                        | created_by TEXT                        |                         |
| is_active=1 单激活不变量          | is_active INTEGER + 触发器             | 触发器保证，但不跨 family |

另外：Protocol 说"全局同一时刻只有 1 条 is_active=1"，但触发器是 `per config_family`；
      我们在 activate_version 显式取消同 family 所有旧激活即可满足"全局单激活 per family"语义。
"""
from __future__ import annotations

import json
import re
from datetime import datetime
from datetime import timezone as _tz_utc
from typing import Dict, Optional

from dreambuddy_dal.connection import get_sqlite_connection
from dreambuddy_dal.protocols.config_repo import ConfigRepository

# ===================================================================== helpers
_VER_RE = re.compile(r"^v(\d+)$")


def _ver_int_to_str(v: int) -> str:
    return f"v{v}"


def _ver_str_to_int(s: str) -> Optional[int]:
    m = _VER_RE.match(str(s))
    return int(m.group(1)) if m else None


def _iso_z(dt: object) -> str:
    if dt is None:
        dt = datetime.now(_tz_utc.utc)
    if isinstance(dt, datetime):
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=_tz_utc.utc)
        return dt.astimezone(_tz_utc.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
    return str(dt)


# ===================================================================== 实现
class SqliteConfigRepository(ConfigRepository):
    def __init__(self, db_path: str):
        self.db_path = db_path

    # ------------------------------------------------------------------ utils
    def _next_version_int(self, conn) -> int:
        """查表中同 config_family 的最大 version:int + 1（跨 family 不共享序列，不跨 family 单调）。"""
        rows = conn.execute("SELECT version FROM cv_config_versions").fetchall()
        max_v = 0
        for (v,) in rows:
            n = _ver_str_to_int(str(v))
            if n is not None and n > max_v:
                max_v = n
        return max_v + 1

    # ================================================================ 创建版本
    def create_version(
        self,
        config_name: str,
        config_data: Dict,
        *,
        created_by: str = "system",
        description: Optional[str] = None,
    ) -> int:
        # 处理 Decimal → JSON 可序列化：用 default=str
        def _default(o):
            from decimal import Decimal
            if isinstance(o, Decimal):
                return str(o)
            if isinstance(o, datetime):
                return _iso_z(o)
            return str(o)

        payload_s = json.dumps(config_data, ensure_ascii=False, default=_default)
        with get_sqlite_connection(self.db_path) as conn:
            next_int = self._next_version_int(conn)
            ver_str = _ver_int_to_str(next_int)
            # is_active 默认 0（不自动激活，Protocol 语义）
            conn.execute(
                """
                INSERT INTO cv_config_versions
                    (version, config_family, payload_json, changelog, created_by, notes)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    ver_str,
                    config_name,
                    payload_s,
                    description,
                    created_by,
                    None,
                ),
            )
        return next_int

    # ================================================================ 激活版本
    def activate_version(
        self,
        config_name: str,
        version: int,
        *,
        activated_by: str = "system",
        activated_at: Optional[datetime] = None,
    ) -> bool:
        ver_str = _ver_int_to_str(version)
        iso_at = _iso_z(activated_at) if activated_at else None
        with get_sqlite_connection(self.db_path) as conn:
            # 1) 版本必须存在 + config_family 匹配
            row = conn.execute(
                "SELECT 1 FROM cv_config_versions WHERE version=? AND config_family=?",
                (ver_str, config_name),
            ).fetchone()
            if row is None:
                return False
            # 2) 取消同 family 所有激活态（显式，触发器也会做，防御性加一层）
            conn.execute(
                "UPDATE cv_config_versions SET is_active=0 WHERE config_family=?",
                (config_name,),
            )
            # 3) 激活目标，附带 notes=激活信息（兼容 schema notes 列）
            conn.execute(
                """
                UPDATE cv_config_versions
                SET is_active=1, released_at=COALESCE(?, released_at)
                WHERE version=? AND config_family=?
                """,
                (iso_at, ver_str, config_name),
            )
        return True

    # ================================================================ 读激活版
    def get_active_version(self, config_name: str = "global") -> Optional[Dict]:
        with get_sqlite_connection(self.db_path) as conn:
            row = conn.execute(
                """
                SELECT payload_json
                FROM cv_config_versions
                WHERE config_family=? AND is_active=1 AND archived=0
                ORDER BY released_at DESC
                LIMIT 1
                """,
                (config_name,),
            ).fetchone()
        if row is None:
            return None
        try:
            return json.loads(row[0])
        except Exception:
            return None

    # ================================================================ 读指定历史版
    def get_specific_version(
        self, config_name: str, version: int
    ) -> Optional[Dict]:
        ver_str = _ver_int_to_str(version)
        with get_sqlite_connection(self.db_path) as conn:
            row = conn.execute(
                "SELECT payload_json FROM cv_config_versions WHERE config_family=? AND version=?",
                (config_name, ver_str),
            ).fetchone()
        if row is None:
            return None
        try:
            return json.loads(row[0])
        except Exception:
            return None


__all__ = ["SqliteConfigRepository"]
