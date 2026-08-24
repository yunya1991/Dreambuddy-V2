"""
dreambuddy_dal.implementations.sqlite_unified.rotate
-----------------------------------------------------
P3-3 WAL checkpoint + 旧备份轮转保留 N 份

入口：
  wal_checkpoint(db_path) → int (checkpointed_pages)
  rotate_backups(backup_dir, keep=7) → list[Path] deleted_files

设计（对齐 MIGRATION_PLAN §4.3）：
  1. PRAGMA wal_checkpoint(TRUNCATE) → 合并 WAL 到主库
  2. 扫描 backup_dir 下 dreambuddy_core_*.db[.enc] 文件
  3. 按 mtime 排序，保留最新 keep 份，其余删除（含 .sha256 sidecar）
"""
from __future__ import annotations

from pathlib import Path

from dreambuddy_dal.connection import get_sqlite_connection


def wal_checkpoint(db_path: str) -> int:
    """PRAGMA wal_checkpoint(TRUNCATE) → 返回 checkpointed page count。"""
    with get_sqlite_connection(db_path) as conn:
        row = conn.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone()
    # row = (busy, log, checkpointed)
    if row and len(row) >= 3:
        return int(row[2] or 0)
    return 0


def rotate_backups(backup_dir: str, keep: int = 7) -> list[Path]:
    """保留最新 keep 份备份，删除其余（含 .sha256 sidecar）。返回被删文件列表。"""
    d = Path(backup_dir)
    if not d.exists():
        return []

    # 扫描所有备份文件（.db 和 .enc，排除 .sha256 sidecar）
    backups = sorted(
        [f for f in d.glob("dreambuddy_core_*.*") if f.suffix in (".db", ".enc")],
        key=lambda f: f.stat().st_mtime,
        reverse=True,  # 最新在前
    )

    deleted: list[Path] = []
    for f in backups[keep:]:
        f.unlink()
        deleted.append(f)
        # 删 sidecar
        sha = Path(str(f) + ".sha256")
        if sha.exists():
            sha.unlink()
            deleted.append(sha)

    return deleted


__all__ = ["wal_checkpoint", "rotate_backups"]
