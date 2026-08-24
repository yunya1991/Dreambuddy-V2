"""
dreambuddy_dal.implementations.sqlite_unified.integrity
--------------------------------------------------------
P3-2 PRAGMA integrity_check + ma_integrity_log 审计

入口：
  run_integrity_check(db_path) → IntegrityResult

设计（对齐 MIGRATION_PLAN §4.2）：
  1. PRAGMA integrity_check → ok / error list
  2. PRAGMA foreign_key_check → FK 违规列表
  3. 结果写入 ma_integrity_log 表
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone

from dreambuddy_dal.connection import get_sqlite_connection


@dataclass
class IntegrityResult:
    ok: bool = True
    errors: list = field(default_factory=list)
    fk_violations: list = field(default_factory=list)
    checked_at: str = ""


def run_integrity_check(db_path: str) -> IntegrityResult:
    """执行完整性检查并写入 ma_integrity_log。"""
    now = datetime.now(timezone.utc).isoformat()
    with get_sqlite_connection(db_path) as conn:
        # PRAGMA integrity_check
        rows = conn.execute("PRAGMA integrity_check").fetchall()
        if len(rows) == 1 and rows[0][0] == "ok":
            errors = []
            ok = True
        else:
            errors = [r[0] for r in rows]
            ok = False

        # PRAGMA foreign_key_check
        fk_rows = conn.execute("PRAGMA foreign_key_check").fetchall()
        fk_violations = [list(r) for r in fk_rows] if fk_rows else []
        if fk_violations:
            ok = False

        # 写 ma_integrity_log（适配 schema: run_at, integrity_result, db_size_bytes, wal_size_bytes, schema_version, checkpoint_result）
        import os
        db_size = os.path.getsize(db_path) if os.path.exists(db_path) else 0
        wal_path = db_path + "-wal"
        wal_size = os.path.getsize(wal_path) if os.path.exists(wal_path) else 0
        schema_ver_row = conn.execute(
            "SELECT schema_semver FROM ma_schema_version WHERE id=1"
        ).fetchone()
        schema_ver = schema_ver_row[0] if schema_ver_row else "unknown"
        checkpoint_str = json.dumps({
            "errors": errors[:20],
            "fk_violations": fk_violations[:20],
        }, default=str, ensure_ascii=False)
        conn.execute(
            """
            INSERT INTO ma_integrity_log
                (run_at, integrity_result, db_size_bytes, wal_size_bytes, schema_version, checkpoint_result)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (now, "ok" if ok else "fail", db_size, wal_size, schema_ver, checkpoint_str),
        )

    return IntegrityResult(
        ok=ok,
        errors=errors,
        fk_violations=fk_violations,
        checked_at=now,
    )


__all__ = ["IntegrityResult", "run_integrity_check"]
