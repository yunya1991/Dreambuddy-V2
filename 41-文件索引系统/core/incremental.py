"""
incremental.py — 增量更新与 L2 内容索引
========================================
SPEC-41-文件索引系统 v0.6 §2.3/§3（P1 阶段）
职责：
  1. L2 内容索引构建：chunker 分块 → tokenizer 分词 → chunks/tokens/documents 写入
  2. 惰性校验：search/recall 调用前 mtime 快速比对（<10ms/千文件，仅 stat）
  3. 超预算（>50ms）降级跳过，差异留给定时对账修复（SPEC §2.3）
设计原则：
  1. 事务原子性：文件的 chunks/tokens 更新在事务内先删后插
  2. Evidence-First：tokens.positions 记录命中位置
性能优化（全量重建路径，v0.6 实施补充）：
  1. 多进程分词（spawn 上下文，避免 fork 继承数据库连接池）
  2. chunks 单语句多行插入（一次往返取回全部 chunk id）
  3. tokens executemany 批量插入（psycopg3 pipeline 模式）
  4. 多文件合并事务（每波文件一次提交，降低 fsync 开销）
位置: 41-文件索引系统/core/incremental.py
"""
from __future__ import annotations
import multiprocessing
import os
import time
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from .chunker import Chunk, Chunker
from .db import Database
from .indexer import L1Indexer
from .scanner import FileMeta
from .tokenizer import tokenize

# 惰性校验预算（SPEC §2.3）
LAZY_CHECK_BUDGET_MS = 50      # 超过则降级跳过

# tokens 批量插入 SQL（executemany 走 psycopg3 pipeline 模式）
_TOKEN_INSERT_SQL = (
    "INSERT INTO tokens (token, chunk_id, positions, tf) VALUES (%s, %s, %s, %s)"
)


def _tokenize_file(abs_path: Path) -> List[tuple]:
    """读取单个文件并完成分块 + 分词（纯计算，无数据库访问）。

    返回 [(heading, position, boundary_kind, content, tf), ...]，
    tf 为 {token: [出现位置]}。
    """
    text = abs_path.read_text(encoding="utf-8", errors="replace").replace("\x00", "")
    chunker = Chunker()
    chunks = chunker.chunk(abs_path, text)
    payload: List[tuple] = []
    for chunk in chunks:
        tf: Dict[str, List[int]] = {}
        for i, tok in enumerate(tokenize(chunk.content)):
            tf.setdefault(tok, []).append(i)
        payload.append((chunk.heading, chunk.position, chunk.boundary_kind, chunk.content, tf))
    return payload


def _tokenize_file_worker(args: Tuple[str, str]) -> Tuple[str, object]:
    """多进程分词 worker（spawn 上下文，子进程独立加载 jieba 词典）。

    返回 (rel_path, payload)：
    - payload 为 list：正常结果
    - payload 为 None：文件已不存在（应删除索引）
    - payload 为 "ERROR"：处理异常（计入 errors）
    """
    root, rel_path = args
    abs_path = Path(root) / rel_path
    if not abs_path.is_file():
        return (rel_path, None)
    try:
        return (rel_path, _tokenize_file(abs_path))
    except Exception:
        return (rel_path, "ERROR")



class L2Indexer:
    """L2 内容索引器：分块 + 分词 + 倒排写入。

    用法::

        l2 = L2Indexer(root="/path/to/project")
        stats = l2.rebuild()          # 全量（依赖 L1 已就绪）
        stats = l2.update_changed()   # 仅变更文件
    """

    # 多进程分词并行度（保留 1 核给主进程写库）
    _WORKERS = max(1, (os.cpu_count() or 2) - 1)
    # 每波提交给进程池的文件数（同时限制内存中未写入的结果量）
    _WAVE = 100
    # tokens 批量插入阈值（行）
    _TOKEN_BATCH = 5000
    # chunks 单语句插入行数上限（远离 PostgreSQL 65535 参数上限）
    _CHUNK_SLICE = 8000

    def __init__(self, root: str, db: Optional[Database] = None) -> None:
        self.root = Path(root).resolve()
        self.db = db or Database.instance()
        self.chunker = Chunker()
        self.l1 = L1Indexer(root=root, db=self.db)

    # ---------- L2 全量重建 ----------

    def rebuild(self) -> Dict[str, int]:
        """全量重建 L2：先跑 L1 rebuild，再多进程分词 + 批量写入内容索引。"""
        l1_stats = self.l1.rebuild()
        stats = {"scanned": l1_stats.scanned, "chunked": 0, "tokens": 0, "errors": 0}
        with self.db.connection() as conn:
            rows = conn.execute("SELECT path, id FROM files").fetchall()
        if not rows:
            return stats
        paths = [r[0] for r in rows]
        file_ids = {r[0]: r[1] for r in rows}
        # spawn 上下文：子进程重新导入模块，避免 fork 继承父进程数据库连接池
        ctx = multiprocessing.get_context("spawn")
        with ProcessPoolExecutor(max_workers=self._WORKERS, mp_context=ctx) as ex:
            with self.db.connection() as conn:
                for i in range(0, len(paths), self._WAVE):
                    futures = [
                        ex.submit(_tokenize_file_worker, (str(self.root), p))
                        for p in paths[i : i + self._WAVE]
                    ]
                    results = [f.result() for f in futures]
                    self._write_results(conn, file_ids, results, stats)
        return stats

    def _write_results(
        self, conn, file_ids: Dict[str, int], results: list, stats: Dict[str, int]
    ) -> None:
        """批量写入一波分词结果：单事务内先删后插 + tokens 批量插入。"""
        pending: List[tuple] = []
        with conn.transaction():
            for rel_path, payload in results:
                if payload == "ERROR":
                    stats["errors"] += 1
                    continue
                fid = file_ids.get(rel_path)
                if fid is None:
                    continue
                if payload is None:
                    conn.execute("DELETE FROM files WHERE id=%s", (fid,))
                    continue
                # 先删后插（事务原子，SPEC v0.6 §4.1）
                conn.execute("DELETE FROM documents WHERE file_id=%s", (fid,))
                conn.execute("DELETE FROM chunks WHERE file_id=%s", (fid,))
                self._write_chunks_and_tokens(conn, fid, payload, pending)
                self._write_document(conn, fid, payload)
                stats["chunked"] += len(payload)
                if len(pending) >= self._TOKEN_BATCH:
                    self._flush_tokens(conn, pending, stats)
            self._flush_tokens(conn, pending, stats)


    # ---------- 批量写入辅助 ----------

    def _write_chunks_and_tokens(self, conn, fid: int, payload: list, pending_tokens: list) -> None:
        """chunks 单语句多行插入（一次往返取回 chunk id），tokens 暂存待批量插入。"""
        for start in range(0, len(payload), self._CHUNK_SLICE):
            part = payload[start : start + self._CHUNK_SLICE]
            values_sql = ",".join(["(%s, %s, %s, %s, %s)"] * len(part))
            params: list = []
            for heading, position, boundary_kind, content, _tf in part:
                params.extend([fid, heading or None, position, boundary_kind, content])
            cids = [
                r[0]
                for r in conn.execute(
                    "INSERT INTO chunks (file_id, heading, position, boundary_kind, content) "
                    f"VALUES {values_sql} RETURNING id",
                    params,
                ).fetchall()
            ]
            for cid, (_heading, _position, _boundary_kind, _content, tf) in zip(cids, part):
                for tok, positions in tf.items():
                    pending_tokens.append((tok, cid, positions, len(positions)))

    @staticmethod
    def _flush_tokens(conn, pending_tokens: list, stats: Optional[Dict[str, int]] = None) -> None:
        """批量插入暂存的 token 行（executemany，psycopg3 pipeline 模式）。"""
        if pending_tokens:
            conn.cursor().executemany(_TOKEN_INSERT_SQL, pending_tokens)
            if stats is not None:
                stats["tokens"] += len(pending_tokens)
            pending_tokens.clear()

    @staticmethod
    def _write_document(conn, fid: int, payload: list) -> None:
        """documents 摘要（标题取首个标题块，摘要取首块前 200 字符）。"""
        title = next((h for h, _p, _b, _c, _t in payload if h), "")
        summary = payload[0][3][:200] if payload else ""
        conn.execute(
            "INSERT INTO documents (file_id, title, summary, lang) VALUES (%s, %s, %s, %s)",
            (fid, title or None, summary or None, None),
        )

    # ---------- 变更文件增量更新 ----------

    def update_changed(self) -> Dict[str, int]:
        """对 L1 增量更新后，重建变更文件的 L2 内容索引。"""
        l1_stats = self.l1.update()
        stats = {
            "scanned": l1_stats.scanned,
            "changed": l1_stats.indexed + l1_stats.updated,
            "chunked": 0,
            "tokens": 0,
            "errors": 0,
        }
        # 变更文件 = 新写入 + 更新（L1 stats 不带 path 明细，这里按 mtime 重新比对）
        changed_paths = self._detect_changed_paths()
        for path in changed_paths:
            try:
                c, t = self._index_file_content(path)
                stats["chunked"] += c
                stats["tokens"] += t
            except Exception:
                stats["errors"] += 1
        return stats

    def _detect_changed_paths(self) -> List[str]:
        """mtime 比对检测变更文件（与 L1 表记录比对）。"""
        changed: List[str] = []
        with self.db.connection() as conn:
            rows = conn.execute("SELECT id, path, mtime FROM files").fetchall()
            indexed = {r[1]: (r[0], r[2]) for r in rows}
        for meta in self.l1.scanner.scan():
            prev = indexed.get(meta.path)
            if prev is None or abs(prev[1] - meta.mtime) >= 1e-6:
                changed.append(meta.path)
        return changed

    # ---------- 单文件内容索引（事务内先删后插，批量写入） ----------

    def _index_file_content(self, rel_path: str) -> tuple:
        """对单文件构建 chunks/tokens/documents（事务原子）。返回 (chunk 数, token 数)。"""
        abs_path = self.root / rel_path
        if not abs_path.is_file():
            self._delete_file_content(rel_path)
            return (0, 0)
        payload = _tokenize_file(abs_path)
        token_count = 0
        with self.db.connection() as conn:
            with conn.transaction():
                fid_row = conn.execute(
                    "SELECT id FROM files WHERE path=%s", (rel_path,)
                ).fetchone()
                if fid_row is None:
                    return (0, 0)
                fid = fid_row[0]
                # 先删后插（事务原子，SPEC v0.6 §4.1）
                conn.execute("DELETE FROM documents WHERE file_id=%s", (fid,))
                conn.execute("DELETE FROM chunks WHERE file_id=%s", (fid,))
                pending: List[tuple] = []
                self._write_chunks_and_tokens(conn, fid, payload, pending)
                token_count = len(pending)
                self._flush_tokens(conn, pending)
                self._write_document(conn, fid, payload)
        return (len(payload), token_count)

    def _delete_file_content(self, rel_path: str) -> None:
        """清理已删除文件的内容索引（级联删除 chunks/tokens）。"""
        with self.db.connection() as conn:
            conn.execute("DELETE FROM files WHERE path=%s", (rel_path,))



class LazyValidator:
    """惰性校验器：search/recall 调用前快速 mtime 比对（SPEC §2.3）。

    - 预算：<10ms/千文件（仅 stat，不读内容）
    - 超预算（>50ms）降级跳过，差异留给定时对账修复
    """

    def __init__(self, root: str, db: Optional[Database] = None) -> None:
        self.root = Path(root).resolve()
        self.db = db or Database.instance()
        self.l1 = L1Indexer(root=root, db=self.db)

    def check(self) -> Dict[str, int]:
        """执行惰性校验。返回 {"changed": n, "took_ms": n, "degraded": 0|1}。"""
        t0 = time.monotonic()
        changed = 0
        degraded = 0
        with self.db.connection() as conn:
            indexed: Dict[str, float] = {
                r[0]: r[1] for r in conn.execute("SELECT path, mtime FROM files").fetchall()
            }
        for meta in self.l1.scanner.scan():
            if (time.monotonic() - t0) * 1000 > LAZY_CHECK_BUDGET_MS:
                degraded = 1  # 超预算降级：跳过剩余校验
                break
            prev = indexed.get(meta.path)
            if prev is None or abs(prev - meta.mtime) >= 1e-6:
                changed += 1
        took_ms = int((time.monotonic() - t0) * 1000)
        return {"changed": changed, "took_ms": took_ms, "degraded": degraded}

