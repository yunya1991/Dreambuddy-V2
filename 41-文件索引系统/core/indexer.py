"""
indexer.py — L1 元数据索引构建
================================
SPEC-41-文件索引系统 v0.6 §3/§4.1（P0 阶段）
职责：
  1. 将 scanner 产出的 FileMeta 流写入 PostgreSQL files 表（L1 元数据索引）
  2. rebuild()：全量重建（事务内先清后导，失败自动回滚）
  3. update()：增量更新（按 path upsert，mtime/hash 变更才写）
设计原则：
  1. Evidence-First：files 表携带完整来源证据（path/mtime/size/hash）
  2. 事务原子性：写事务内先删后插，提交原子生效（SPEC v0.6 §4.1）
位置: 41-文件索引系统/core/indexer.py
"""
from __future__ import annotations
import hashlib
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, List, Optional

from .scanner import FileMeta, FileScanner
from .db import Database


@dataclass
class IndexStats:
    """索引操作统计（rebuild/update 返回值）。"""
    scanned: int = 0        # 扫描文件数
    indexed: int = 0        # 新写入数
    updated: int = 0        # 更新数
    skipped: int = 0        # 跳过数（未变更）
    removed: int = 0        # 清理数（库中存在但文件系统已删除）
    took_ms: int = 0        # 耗时（毫秒）
    errors: List[str] = field(default_factory=list)


class L1Indexer:
    """L1 元数据索引器。

    用法::
        indexer = L1Indexer(root="/path/to/project")
        stats = indexer.rebuild()      # 全量重建
        stats = indexer.update()       # 增量更新
    """

    def __init__(self, root: str, db: Optional[Database] = None) -> None:
        self.root = Path(root).resolve()
        self.db = db or Database.instance()
        self.scanner = FileScanner(root=str(self.root))

    # ---------- 文件类型推断（SPEC §6 索引范围） ----------

    @staticmethod
    def infer_type(meta: FileMeta) -> str:
        """按路径/扩展名推断类型标记（doc/report/strategy/memory/case/code）。"""
        p = meta.path
        parts = p.lower().split("/")
        if any(seg in ("reports", "artifacts") for seg in parts):
            return "report"
        if "5-case-study" in p.lower() or "/cases/" in p.lower():
            return "case"
        # v1.1：wiki 类型（2-KNOWLEDGE/wiki 目录，SPEC §6/§7.11）
        if "2-knowledge/wiki/" in p.lower() or (len(parts) >= 2 and parts[-2] == "wiki"):
            return "wiki"
        # v1.1：skill 类型（SKILL.md 定义文件，SPEC §6/§7.12）
        if meta.name.lower() == "skill.md":
            return "skill"
        if any(seg in ("memory", "memories") for seg in parts):
            return "memory"
        if meta.ext in (".py", ".ts", ".tsx", ".js", ".jsx", ".sh", ".go", ".rs"):
            return "code"
        if "strategy" in parts or "strategies" in parts:
            return "strategy"
        return "doc"

    # ---------- hash 计算（mtime+hash 双重校验依据，SPEC §11） ----------

    @staticmethod
    def file_hash(abs_path: Path) -> str:
        """内容 SHA-256（前 16 位十六进制，对账用轻量指纹）。"""
        h = hashlib.sha256()
        with open(abs_path, "rb") as f:
            for chunk in iter(lambda: f.read(1 << 20), b""):
                h.update(chunk)
        return h.hexdigest()[:16]

    # ---------- 全量重建（SPEC v0.6 §4.1：事务内重建） ----------

    def rebuild(self) -> IndexStats:
        """全量重建 L1 索引：事务内清空 files 后重导，失败自动回滚。"""
        t0 = time.monotonic()
        stats = IndexStats()
        metas: List[FileMeta] = []
        for meta in self.scanner.scan():
            metas.append(meta)
            stats.scanned += 1
        with self.db.connection() as conn:
            with conn.transaction():
                conn.execute("DELETE FROM files")
                conn.execute("ALTER SEQUENCE files_id_seq RESTART WITH 1")
                for meta in metas:
                    try:
                        file_hash = self.file_hash(self.root / meta.path)
                        conn.execute(
                            "INSERT INTO files (path, type, mtime, size, hash) "
                            "VALUES (%s, %s, %s, %s, %s)",
                            (meta.path, self.infer_type(meta), meta.mtime, meta.size, file_hash),
                        )
                        stats.indexed += 1
                    except Exception as e:  # 单文件失败不阻断整体
                        stats.errors.append(f"{meta.path}: {e}")
        stats.took_ms = int((time.monotonic() - t0) * 1000)
        return stats

    # ---------- 增量更新（SPEC §2.3 惰性校验/对账共用） ----------

    def update(self) -> IndexStats:
        """增量更新：mtime/hash 变更文件 upsert；库中已删除文件清理。"""
        t0 = time.monotonic()
        stats = IndexStats()
        with self.db.connection() as conn:
            existing = {
                row[0]: (row[1], row[2])  # path -> (id, hash)
                for row in conn.execute("SELECT path, id, hash FROM files").fetchall()
            }
        seen: set = set()
        for meta in self.scanner.scan():
            stats.scanned += 1
            seen.add(meta.path)
            prev = existing.get(meta.path)
            try:
                if prev is None:
                    file_hash = self.file_hash(self.root / meta.path)
                    with self.db.connection() as conn:
                        conn.execute(
                            "INSERT INTO files (path, type, mtime, size, hash) "
                            "VALUES (%s, %s, %s, %s, %s)",
                            (meta.path, self.infer_type(meta), meta.mtime, meta.size, file_hash),
                        )
                    stats.indexed += 1
                else:
                    fid, prev_hash = prev
                    if prev_hash is None:  # 无 hash 记录，补算
                        file_hash = self.file_hash(self.root / meta.path)
                        if file_hash != prev_hash:
                            with self.db.connection() as conn:
                                conn.execute(
                                    "UPDATE files SET mtime=%s, size=%s, hash=%s, indexed_at=now() WHERE id=%s",
                                    (meta.mtime, meta.size, file_hash, fid),
                                )
                            stats.updated += 1
                        else:
                            stats.skipped += 1
                    else:
                        # mtime 未变 → 跳过（惰性校验仅 stat 的依据）
                        with self.db.connection() as conn:
                            row = conn.execute(
                                "SELECT mtime FROM files WHERE id=%s", (fid,)
                            ).fetchone()
                        if row and abs(row[0] - meta.mtime) < 1e-6:
                            stats.skipped += 1
                        else:
                            file_hash = self.file_hash(self.root / meta.path)
                            with self.db.connection() as conn:
                                conn.execute(
                                    "UPDATE files SET mtime=%s, size=%s, hash=%s, indexed_at=now() WHERE id=%s",
                                    (meta.mtime, meta.size, file_hash, fid),
                                )
                            stats.updated += 1
            except Exception as e:
                stats.errors.append(f"{meta.path}: {e}")
        # 清理：库中存在但文件系统已删除
        stale = set(existing) - seen
        if stale:
            with self.db.connection() as conn:
                with conn.transaction():
                    for path in stale:
                        conn.execute("DELETE FROM files WHERE path=%s", (path,))
                        stats.removed += 1
        stats.took_ms = int((time.monotonic() - t0) * 1000)
        return stats
