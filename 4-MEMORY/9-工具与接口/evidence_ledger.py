"""Evidence Ledger — 集中化决策审计 trail

SPEC: SPEC-CognitiveSystem-Evolution.md §2.3.4 P0-3 + §3.5 M3（Merkle树）

将散在 record 和 33-REA 中的 evidence 集中化，提供不可篡改的决策审计 trail。
使用 Merkle 树结构（局部断裂可隔离），替代原始链式哈希设计。

与 33-REA evidence.py 的关系：
  - 33-REA 的 Evidence 是单条逆向分析证据单元（result/level/provenance/confidence）
  - 本模块的 EvidenceEntry 是决策审计条目（SPO三元组 + source + receipt_hash）
  - EvidenceEntry.source 可引用 33-REA 的 evidence_id，建立跨系统追溯

工程约束：FAIL-OPEN / 零外部依赖 / 纯 Python 标准库
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


# ============================================================
# EvidenceEntry — 决策审计条目
# ============================================================

@dataclass
class EvidenceEntry:
    """Evidence Ledger 条目 — 集中化决策审计 trail。

    Attributes:
        entry_id: 唯一标识，格式 el_<64hex>
        subject: 决策主体（如 "record_hook"）
        relation: 决策关系（如 "调用了"）
        object: 决策对象（如 "skill_indexer.record_hook"）
        timestamp: ns 级时间戳
        source: 来源（file:line / memory_id / SKILL_name / evidence_id）
        confidence: 置信度 0.0-1.0
        level: 事实分级 (observation/derivation/inference/unknown)
        receipt_hash: 本条目的 Merkle 叶子哈希（append 时计算）
        prev_hash: 前一条目的 receipt_hash（链式兼容，首条为 "0"*64）
        git_commit_hash: P1-5 链式溯源等价物（git commit hash，SPEC §2.1）
    """

    subject: str
    relation: str
    object: str
    source: str
    confidence: float = 0.5
    level: str = "observation"
    entry_id: str = field(default_factory=lambda: f"el_{uuid.uuid4().hex}")
    timestamp: int = field(default_factory=lambda: time.time_ns())
    receipt_hash: str = ""  # append 时计算
    prev_hash: str = ""    # append 时填充
    git_commit_hash: str = ""  # P1-5: 链式溯源等价物（git commit hash）

    def to_ledger_json(self) -> str:
        """序列化为用于哈希计算的 JSON（排除 receipt_hash 和 prev_hash）。"""
        data = {
            "entry_id": self.entry_id,
            "subject": self.subject,
            "relation": self.relation,
            "object": self.object,
            "timestamp": self.timestamp,
            "source": self.source,
            "confidence": self.confidence,
            "level": self.level,
            "git_commit_hash": self.git_commit_hash,
        }
        return json.dumps(data, sort_keys=True, ensure_ascii=False)

    def to_dict(self) -> dict[str, Any]:
        return {
            "entry_id": self.entry_id,
            "subject": self.subject,
            "relation": self.relation,
            "object": self.object,
            "timestamp": self.timestamp,
            "source": self.source,
            "confidence": self.confidence,
            "level": self.level,
            "receipt_hash": self.receipt_hash,
            "prev_hash": self.prev_hash,
            "git_commit_hash": self.git_commit_hash,
        }


# ============================================================
# Merkle 树辅助函数
# ============================================================

def _sha256(data: str) -> str:
    """计算字符串的 SHA-256 哈希。"""
    return hashlib.sha256(data.encode("utf-8")).hexdigest()


def _compute_leaf_hash(entry: EvidenceEntry, prev_hash: str) -> str:
    """计算叶子节点哈希 = sha256(entry_json + prev_hash)。"""
    return _sha256(entry.to_ledger_json() + prev_hash)


def _compute_merkle_root(leaf_hashes: list[str]) -> str:
    """从叶子哈希列表计算 Merkle 根哈希。

    逐层两两配对向上计算：
    - 0 个叶子 → "0"*64（空树根）
    - 1 个叶子 → 该叶子本身
    - N 个叶子 → 两两 sha256(left+right) 向上计算
    - 奇数个叶子 → 最后一个叶子直接提升到上层
    """
    if not leaf_hashes:
        return "0" * 64
    if len(leaf_hashes) == 1:
        return leaf_hashes[0]

    current = list(leaf_hashes)
    while len(current) > 1:
        next_level: list[str] = []
        for i in range(0, len(current), 2):
            if i + 1 < len(current):
                next_level.append(_sha256(current[i] + current[i + 1]))
            else:
                # 奇数个叶子，最后一个直接提升
                next_level.append(current[i])
        current = next_level
    return current[0]


# ============================================================
# EvidenceLedger — 审计 trail 主体
# ============================================================

_GENESIS_HASH = "0" * 64  # 创世哈希（prev_hash 的初始值）


class EvidenceLedger:
    """Evidence Ledger — 集中化决策审计 trail。

    使用 SQLite 持久化，Merkle 树保证不可篡改。
    FAIL-OPEN：存储失败不阻塞主流程。
    """

    def __init__(self, db_path: Path | str | None = None):
        """初始化 Ledger。

        Args:
            db_path: SQLite 数据库路径。None 表示内存数据库（测试用）。
        """
        self._db_path = str(db_path) if db_path else ":memory:"
        self._conn: sqlite3.Connection | None = None
        self._init_db()

    def _init_db(self):
        """初始化数据库表。FAIL-OPEN：失败时不抛异常。

        P0-5（SPEC §3.2 并发安全）：
          - SQLite WAL 模式（PRAGMA journal_mode=WAL）支持多进程并发读写
          - ledger_counters 表（跨进程共享计数器，atomic UPDATE）
          - 索引 idx_subject_object 加速 receipt 查询（替代全表扫描）
        """
        try:
            self._conn = sqlite3.connect(self._db_path)
            # P0-5: WAL 模式（内存 DB 不支持，FAIL-OPEN 跳过）
            if self._db_path != ":memory:":
                try:
                    self._conn.execute("PRAGMA journal_mode=WAL")
                except Exception:
                    pass  # 内存或不支持 → FAIL-OPEN
            self._conn.execute("""
                CREATE TABLE IF NOT EXISTS evidence_entries (
                    entry_id        TEXT PRIMARY KEY,
                    subject         TEXT,
                    relation        TEXT,
                    object          TEXT,
                    timestamp       INTEGER,
                    source          TEXT,
                    confidence      REAL,
                    level           TEXT,
                    receipt_hash    TEXT,
                    prev_hash       TEXT,
                    git_commit_hash TEXT DEFAULT ''
                )
            """)
            # P1-5: 对已存在的 DB 做 migration（ADD COLUMN IF NOT EXISTS 不被 SQLite 支持）
            try:
                self._conn.execute(
                    "ALTER TABLE evidence_entries ADD COLUMN git_commit_hash TEXT DEFAULT ''"
                )
            except Exception:
                pass  # 列已存在 → 静默
            # P0-1: 索引加速 _check_poe_trust 的 receipt 查询（替代全表扫描）
            self._conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_entries_subject_object "
                "ON evidence_entries(subject, object)"
            )
            # P0-5: 计数器表（跨进程共享，atomic UPDATE）
            self._conn.execute("""
                CREATE TABLE IF NOT EXISTS ledger_counters (
                    name        TEXT PRIMARY KEY,
                    value       INTEGER NOT NULL DEFAULT 0
                )
            """)
            # P1-3: trust_state 表（6 信任失效条件跟踪，SPEC §2.3）
            self._conn.execute("""
                CREATE TABLE IF NOT EXISTS trust_state (
                    memory_id           TEXT PRIMARY KEY,
                    first_verified_at   INTEGER,
                    git_commit_hash     TEXT DEFAULT '',
                    dependency_fp       TEXT DEFAULT '',
                    scope               TEXT DEFAULT '',
                    verify_failures     INTEGER DEFAULT 0,
                    last_reverify_status TEXT DEFAULT ''
                )
            """)
            self._conn.commit()
        except Exception:
            self._conn = None  # FAIL-OPEN

    def _get_last_receipt(self) -> str:
        """获取最后一条目的 receipt_hash，无条目返回创世哈希。"""
        if self._conn is None:
            return _GENESIS_HASH
        try:
            cursor = self._conn.execute(
                "SELECT receipt_hash FROM evidence_entries "
                "ORDER BY timestamp DESC LIMIT 1"
            )
            row = cursor.fetchone()
            return row[0] if row else _GENESIS_HASH
        except Exception:
            return _GENESIS_HASH

    def append(self, entry: EvidenceEntry) -> str:
        """追加条目到 Ledger。

        计算 receipt_hash（Merkle 叶子哈希）并持久化。
        FAIL-OPEN：存储失败返回空字符串。

        Returns:
            receipt_hash（条目的哈希），失败返回 ""
        """
        if self._conn is None:
            return ""  # FAIL-OPEN

        try:
            prev_hash = self._get_last_receipt()
            receipt = _compute_leaf_hash(entry, prev_hash)
            entry.receipt_hash = receipt
            entry.prev_hash = prev_hash

            self._conn.execute(
                """INSERT INTO evidence_entries
                   (entry_id, subject, relation, object, timestamp,
                    source, confidence, level, receipt_hash, prev_hash, git_commit_hash)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    entry.entry_id,
                    entry.subject,
                    entry.relation,
                    entry.object,
                    entry.timestamp,
                    entry.source,
                    entry.confidence,
                    entry.level,
                    entry.receipt_hash,
                    entry.prev_hash,
                    entry.git_commit_hash,
                ),
            )
            self._conn.commit()
            return receipt
        except Exception:
            return ""  # FAIL-OPEN

    def get_merkle_root(self) -> str:
        """计算当前所有条目的 Merkle 根哈希。"""
        if self._conn is None:
            return _GENESIS_HASH
        try:
            cursor = self._conn.execute(
                "SELECT entry_id, subject, relation, object, timestamp, "
                "source, confidence, level, prev_hash, git_commit_hash "
                "FROM evidence_entries ORDER BY timestamp ASC"
            )
            leaf_hashes: list[str] = []
            for row in cursor.fetchall():
                entry = EvidenceEntry(
                    entry_id=row[0],
                    subject=row[1],
                    relation=row[2],
                    object=row[3],
                    timestamp=row[4],
                    source=row[5],
                    confidence=row[6],
                    level=row[7],
                    prev_hash=row[8],
                    git_commit_hash=row[9],
                )
                leaf_hashes.append(_compute_leaf_hash(entry, entry.prev_hash))
            return _compute_merkle_root(leaf_hashes)
        except Exception:
            return _GENESIS_HASH

    def verify_integrity(self) -> bool:
        """全量完整性验证：重新计算所有叶子哈希并验证 Merkle 根。"""
        if self._conn is None:
            return True  # 空数据库视为有效

        try:
            cursor = self._conn.execute(
                "SELECT entry_id, subject, relation, object, timestamp, "
                "source, confidence, level, receipt_hash, prev_hash, git_commit_hash "
                "FROM evidence_entries ORDER BY timestamp ASC"
            )
            rows = cursor.fetchall()

            expected_prev = _GENESIS_HASH
            for row in rows:
                entry = EvidenceEntry(
                    entry_id=row[0],
                    subject=row[1],
                    relation=row[2],
                    object=row[3],
                    timestamp=row[4],
                    source=row[5],
                    confidence=row[6],
                    level=row[7],
                    receipt_hash=row[8],
                    prev_hash=row[9],
                    git_commit_hash=row[10] if len(row) > 10 else "",
                )
                # 验证 prev_hash 链
                if entry.prev_hash != expected_prev:
                    return False
                # 验证 receipt_hash
                expected_receipt = _compute_leaf_hash(entry, entry.prev_hash)
                if entry.receipt_hash != expected_receipt:
                    return False
                expected_prev = entry.receipt_hash

            return True
        except Exception:
            return False

    def query(
        self,
        subject: str | None = None,
        source: str | None = None,
    ) -> list[EvidenceEntry]:
        """按条件查询条目。"""
        if self._conn is None:
            return []
        try:
            sql = (
                "SELECT entry_id, subject, relation, object, timestamp, "
                "source, confidence, level, receipt_hash, prev_hash, git_commit_hash "
                "FROM evidence_entries WHERE 1=1"
            )
            params: list = []
            if subject is not None:
                sql += " AND subject = ?"
                params.append(subject)
            if source is not None:
                sql += " AND source = ?"
                params.append(source)
            sql += " ORDER BY timestamp ASC"

            cursor = self._conn.execute(sql, params)
            results: list[EvidenceEntry] = []
            for row in cursor.fetchall():
                results.append(EvidenceEntry(
                    entry_id=row[0],
                    subject=row[1],
                    relation=row[2],
                    object=row[3],
                    timestamp=row[4],
                    source=row[5],
                    confidence=row[6],
                    level=row[7],
                    receipt_hash=row[8],
                    prev_hash=row[9],
                    git_commit_hash=row[10] if len(row) > 10 else "",
                ))
            return results
        except Exception:
            return []

    def query_all(self) -> list[EvidenceEntry]:
        """查询全部条目。"""
        return self.query()

    # ============================================================
    # P0-2: O(1) receipt 存在性查询（替代全量 verify_integrity）
    # ============================================================

    def verify_receipt_exists(self, entry_id: str) -> bool:
        """P0-2: 检查指定 entry_id 的 receipt 是否存在（O(1) 索引查询）。

        SPEC §3.2：日常路径只验 receipt 存在性，不跑全量验证。
        用于有界信任传递场景（P1）+ _check_poe_trust 简化路径。

        Args:
            entry_id: EvidenceEntry.entry_id（el_<64hex>）

        Returns:
            True=存在 receipt，False=不存在或存储不可用
        """
        if self._conn is None or not entry_id:
            return False
        try:
            cursor = self._conn.execute(
                "SELECT 1 FROM evidence_entries WHERE entry_id = ? LIMIT 1",
                (entry_id,),
            )
            return cursor.fetchone() is not None
        except Exception:
            return False  # FAIL-OPEN

    def get_receipt_for(self, subject: str, object_id: str) -> str:
        """P0-1: 按 (subject, object) 索引查询最新 receipt_hash（O(log N)）。

        替代 _check_poe_trust 原有的 query() + 遍历逻辑（O(N) 全表扫描）。
        SPEC §3.2：日常只验 receipt 存在性。

        Args:
            subject: EvidenceEntry.subject（如 "record"）
            object_id: EvidenceEntry.object（如 memory_id）

        Returns:
            receipt_hash 非空字符串=存在；空字符串=不存在或存储不可用
        """
        if self._conn is None or not subject or not object_id:
            return ""
        try:
            cursor = self._conn.execute(
                "SELECT receipt_hash FROM evidence_entries "
                "WHERE subject = ? AND object = ? "
                "ORDER BY timestamp DESC LIMIT 1",
                (subject, object_id),
            )
            row = cursor.fetchone()
            return row[0] if row else ""
        except Exception:
            return ""  # FAIL-OPEN

    # ============================================================
    # P0-5: 计数器（跨进程共享，atomic UPDATE）
    # ============================================================

    def increment_counter(self, name: str) -> int:
        """P0-5: 原子自增计数器并返回新值。

        SPEC §3.2：计数器落库，跨进程共享，不用文件 flock。
        使用 INSERT ... ON CONFLICT + UPDATE RETURNING 实现原子性。

        Args:
            name: 计数器名（如 "integrity_check_count"）

        Returns:
            自增后的新值；失败返回 0（FAIL-OPEN）
        """
        if self._conn is None or not name:
            return 0
        try:
            # 原子 upsert + 自增（SQLite >= 3.24 支持 ON CONFLICT）
            self._conn.execute(
                "INSERT INTO ledger_counters(name, value) VALUES(?, 1) "
                "ON CONFLICT(name) DO UPDATE SET value = value + 1",
                (name,),
            )
            self._conn.commit()
            cursor = self._conn.execute(
                "SELECT value FROM ledger_counters WHERE name = ?",
                (name,),
            )
            row = cursor.fetchone()
            return row[0] if row else 0
        except Exception:
            return 0  # FAIL-OPEN

    def get_counter(self, name: str) -> int:
        """P0-5: 读取计数器当前值（跨进程可见）。

        Args:
            name: 计数器名

        Returns:
            当前值；不存在或存储不可用返回 0
        """
        if self._conn is None or not name:
            return 0
        try:
            cursor = self._conn.execute(
                "SELECT value FROM ledger_counters WHERE name = ?",
                (name,),
            )
            row = cursor.fetchone()
            return row[0] if row else 0
        except Exception:
            return 0  # FAIL-OPEN

    # ============================================================
    # P1-3: 6 信任失效条件（SPEC §2.3 有界信任传递）
    # ============================================================

    # 超时阈值（ns 秒级）：代码类 1 天，文档类 30 天
    _TIMEOUT_CODE_NS = 1 * 24 * 3600 * 10**9
    _TIMEOUT_DOC_NS = 30 * 24 * 3600 * 10**9

    def record_trust_state(
        self,
        memory_id: str,
        git_commit_hash: str = "",
        dependency_fp: str = "",
        scope: str = "",
    ) -> bool:
        """P1-3: 记录信任状态（首次验证或重新验证时调用）。

        SPEC §2.3：已通过重型 PoE 验证的产出，记录 trust_state 用于后续失效条件检查。

        Args:
            memory_id: 记忆/产出 ID
            git_commit_hash: 验证时的 git commit hash（失效条件 1）
            dependency_fp: 依赖指纹（失效条件 4）
            scope: 验证 scope（失效条件 5，含 'code' 关键词=代码类，含 'doc'=文档类）

        Returns:
            True=记录成功，False=失败（FAIL-OPEN）
        """
        if self._conn is None or not memory_id:
            return False
        try:
            now_ns = time.time_ns()
            self._conn.execute(
                """INSERT INTO trust_state
                   (memory_id, first_verified_at, git_commit_hash,
                    dependency_fp, scope, verify_failures, last_reverify_status)
                   VALUES (?, ?, ?, ?, ?, 0, '')
                   ON CONFLICT(memory_id) DO UPDATE SET
                     first_verified_at = ?,
                     git_commit_hash = ?,
                     dependency_fp = ?,
                     scope = ?,
                     verify_failures = 0,
                     last_reverify_status = ''""",
                (memory_id, now_ns, git_commit_hash, dependency_fp, scope,
                 now_ns, git_commit_hash, dependency_fp, scope),
            )
            self._conn.commit()
            return True
        except Exception:
            return False  # FAIL-OPEN

    def mark_verify_failure(self, memory_id: str) -> bool:
        """P1-3 失效条件 2: 标记 verify 失败（verify_failures += 1）。"""
        if self._conn is None or not memory_id:
            return False
        try:
            self._conn.execute(
                "UPDATE trust_state SET verify_failures = verify_failures + 1 "
                "WHERE memory_id = ?",
                (memory_id,),
            )
            self._conn.commit()
            return True
        except Exception:
            return False  # FAIL-OPEN

    def mark_sample_reverify_failure(self, memory_id: str) -> bool:
        """P1-3 失效条件 6: 标记抽样重验失败（last_reverify_status='failed'）。"""
        if self._conn is None or not memory_id:
            return False
        try:
            self._conn.execute(
                "UPDATE trust_state SET last_reverify_status = 'failed' "
                "WHERE memory_id = ?",
                (memory_id,),
            )
            self._conn.commit()
            return True
        except Exception:
            return False  # FAIL-OPEN

    def check_trust_validity(
        self,
        memory_id: str,
        current_git_hash: str,
        current_dependency_fp: str,
        current_scope: str,
    ) -> tuple[bool, str]:
        """P1-3: 检查 6 信任失效条件。

        SPEC §2.3 有界信任传递的 6 个失效条件：
          1. 代码变更（git_commit_hash 不匹配）
          2. verify 失败（verify_failures > 0）
          3. 超时（按 scope 分级：代码 1 天 / 文档 30 天）
          4. 依赖指纹变化（dependency_fp 不匹配）
          5. scope 漂移（scope 不匹配）
          6. 抽样重验失败（last_reverify_status == 'failed'）

        Args:
            memory_id: 记忆/产出 ID
            current_git_hash: 当前 git commit hash
            current_dependency_fp: 当前依赖指纹
            current_scope: 当前请求 scope

        Returns:
            (is_valid, reason)：
                (True, 'valid') = 所有条件满足
                (False, 'no_trust_state') = 无 trust_state 记录
                (False, 'code_change') = 失效条件 1
                (False, 'verify_failed') = 失效条件 2
                (False, 'timeout') = 失效条件 3
                (False, 'dependency_changed') = 失效条件 4
                (False, 'scope_drift') = 失效条件 5
                (False, 'sample_reverify_failed') = 失效条件 6
                (True, 'fail_open') = 异常时 FAIL-OPEN
        """
        if self._conn is None or not memory_id:
            return (True, "fail_open")  # FAIL-OPEN
        try:
            cursor = self._conn.execute(
                "SELECT first_verified_at, git_commit_hash, dependency_fp, "
                "scope, verify_failures, last_reverify_status "
                "FROM trust_state WHERE memory_id = ?",
                (memory_id,),
            )
            row = cursor.fetchone()
            if row is None:
                return (False, "no_trust_state")

            first_verified_at, stored_hash, stored_dep_fp, \
                stored_scope, verify_failures, last_reverify = (
                    row[0], row[1], row[2], row[3], row[4], row[5],
                )

            # 失效条件 1: 代码变更（git_commit_hash 不匹配）
            if stored_hash and current_git_hash and stored_hash != current_git_hash:
                return (False, "code_change")

            # 失效条件 2: verify 失败
            if verify_failures and verify_failures > 0:
                return (False, "verify_failed")

            # 失效条件 3: 超时（按 scope 分级）
            if first_verified_at:
                now_ns = time.time_ns()
                elapsed_ns = now_ns - first_verified_at
                # scope 含 'doc' 关键词 → 30 天；其他 → 1 天
                timeout_threshold = (
                    self._TIMEOUT_DOC_NS
                    if stored_scope and "doc" in stored_scope.lower()
                    else self._TIMEOUT_CODE_NS
                )
                if elapsed_ns > timeout_threshold:
                    return (False, "timeout")

            # 失效条件 4: 依赖指纹变化
            if stored_dep_fp and current_dependency_fp and \
               stored_dep_fp != current_dependency_fp:
                return (False, "dependency_changed")

            # 失效条件 5: scope 漂移
            if stored_scope and current_scope and stored_scope != current_scope:
                return (False, "scope_drift")

            # 失效条件 6: 抽样重验失败
            if last_reverify == "failed":
                return (False, "sample_reverify_failed")

            return (True, "valid")
        except Exception:
            return (True, "fail_open")  # FAIL-OPEN

    def _tamper_for_test(self, index: int, **fields: str):
        """测试用：篡改指定索引的条目（破坏 receipt_hash 的正确性）。"""
        if self._conn is None:
            return
        try:
            cursor = self._conn.execute(
                "SELECT entry_id FROM evidence_entries "
                "ORDER BY timestamp ASC"
            )
            rows = cursor.fetchall()
            if index >= len(rows):
                return
            entry_id = rows[index][0]
            sets = ", ".join(f"{k} = ?" for k in fields)
            values = list(fields.values()) + [entry_id]
            self._conn.execute(
                f"UPDATE evidence_entries SET {sets} WHERE entry_id = ?",
                values,
            )
            self._conn.commit()
        except Exception:
            pass

    def close(self):
        """关闭数据库连接。"""
        if self._conn is not None:
            try:
                self._conn.close()
            except Exception:
                pass
            self._conn = None
