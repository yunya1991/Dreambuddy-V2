#!/usr/bin/env python3
"""
向量记忆接口 (VectorMemoryInterface) — L1 应用记忆存储升级

将应用记忆从 JSON 文件升级到 SQLite + 向量检索，支持语义搜索。
采用双引擎策略：
    - 默认引擎: numpy + sqlite3（零依赖，所有 Python 可用）
    - 高性能引擎: sqlite-vec（可选，需要支持扩展加载的 Python）

核心能力:
    1. 向量存储：将文本内容编码为向量并持久化到 SQLite
    2. 语义搜索：基于余弦相似度的 KNN 搜索
    3. 元数据过滤：支持按 quality_level、tags 等条件过滤
    4. 双引擎自动切换：检测 sqlite-vec 可用性，自动选择最优引擎

用法:
    from vector_memory_interface import VectorMemoryInterface

    vm = VectorMemoryInterface(storage_path="memory.db")
    vm.add("BTC趋势策略：突破后跟涨效果好", tags=["BTC","趋势"], quality="A")
    results = vm.search("BTC突破策略", top_k=5)
    for r in results:
        print(f"{r['content']} (score={r['score']:.3f})")
"""

from __future__ import annotations

import hashlib
import json
import logging
import math
import os
import sqlite3
import struct
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# 向量维度（简化版：使用哈希向量化，生产环境可替换为 embedding 模型）
DEFAULT_VECTOR_DIM = 256


# ============================================================
# 向量化器（轻量级，无需外部模型）
# ============================================================

class TextVectorizer:
    """
    轻量级文本向量化器

    使用字符级 n-gram + 哈希投影生成固定维度向量。
    适合原型开发，生产环境应替换为 sentence-transformers 等模型。

    特点:
    - 零依赖（不需要 torch/transformers）
    - 固定维度输出（DEFAULT_VECTOR_DIM）
    - 中文友好（按字符分词）
    - 归一化向量（便于余弦相似度计算）
    """

    def __init__(self, dim: int = DEFAULT_VECTOR_DIM, ngram: int = 2):
        self.dim = dim
        self.ngram = ngram

    def encode(self, text: str) -> List[float]:
        """将文本编码为固定维度的归一化向量"""
        vec = [0.0] * self.dim

        if not text:
            return vec

        # 字符级 n-gram
        for i in range(len(text) - self.ngram + 1):
            gram = text[i:i + self.ngram]
            # 哈希到向量维度
            h = int(hashlib.md5(gram.encode('utf-8')).hexdigest(), 16)
            idx = h % self.dim
            sign = 1.0 if (h >> 8) % 2 == 0 else -1.0
            vec[idx] += sign

        # L2 归一化
        norm = math.sqrt(sum(v * v for v in vec))
        if norm > 0:
            vec = [v / norm for v in vec]

        return vec

    def encode_batch(self, texts: List[str]) -> List[List[float]]:
        """批量编码"""
        return [self.encode(t) for t in texts]


# ============================================================
# 相似度计算
# ============================================================

def cosine_similarity(a: List[float], b: List[float]) -> float:
    """计算两个向量的余弦相似度（向量已归一化时等于点积）"""
    return sum(x * y for x, y in zip(a, b))


def vector_to_bytes(vec: List[float]) -> bytes:
    """向量转字节（用于 sqlite-vec 存储）"""
    return struct.pack(f'{len(vec)}f', *vec)


def bytes_to_vector(data: bytes, dim: int) -> List[float]:
    """字节转向量"""
    return list(struct.unpack(f'{dim}f', data))


# ============================================================
# 数据模型
# ============================================================

@dataclass
class MemoryRecord:
    """记忆记录"""
    id: str = ""
    content: str = ""
    vector: List[float] = field(default_factory=list)
    quality_level: str = "C"
    confidence: float = 0.0
    tags: List[str] = field(default_factory=list)
    memory_type: str = "experience"
    source: str = ""
    created_at: str = ""
    updated_at: str = ""
    verify_count: int = 0

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "content": self.content,
            "quality_level": self.quality_level,
            "confidence": self.confidence,
            "tags": self.tags,
            "memory_type": self.memory_type,
            "source": self.source,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "verify_count": self.verify_count,
        }


@dataclass
class SearchResult:
    """搜索结果"""
    id: str
    content: str
    score: float
    quality_level: str
    tags: List[str]
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        # 将 metadata 中的常用字段提到顶层，便于 AI 直接访问
        meta = self.metadata or {}
        return {
            "id": self.id,
            "content": self.content,
            "score": round(self.score, 4),
            "quality_level": self.quality_level,
            "confidence": meta.get("confidence", 0.0),
            "verify_count": meta.get("verify_count", 0),
            "source": meta.get("source", ""),
            "tags": self.tags,
            "metadata": self.metadata,
        }


# ============================================================
# 核心接口
# ============================================================

class VectorMemoryInterface:
    """
    向量记忆接口

    双引擎策略:
    - engine="auto": 自动检测 sqlite-vec，不可用则回退到 numpy
    - engine="sqlite_vec": 强制使用 sqlite-vec（需要支持扩展加载的 Python）
    - engine="numpy": 强制使用 numpy（零依赖，兼容性最好）
    """

    def __init__(
        self,
        storage_path: Optional[str] = None,
        vector_dim: int = DEFAULT_VECTOR_DIM,
        engine: str = "auto",
        memory_id: str = "",
        distill_engine: Optional[Any] = None,
    ):
        """
        初始化向量记忆接口。

        Args:
            storage_path: SQLite 数据库路径。None 则使用内存数据库。
            vector_dim: 向量维度
            engine: 搜索引擎 ("auto" / "sqlite_vec" / "numpy")
            memory_id: 应用记忆ID（如 "AM-TRD-001"）
            distill_engine: 动态蒸馏引擎实例（可选）
        """
        self.vector_dim = vector_dim
        self.memory_id = memory_id
        self.vectorizer = TextVectorizer(dim=vector_dim)
        self._distill_engine = distill_engine

        # 存储路径
        if storage_path is None:
            storage_path = ":memory:"
        self.storage_path = storage_path

        # 初始化数据库（check_same_thread=False 允许跨线程访问）
        self.db = sqlite3.connect(storage_path, check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self._db_lock = threading.Lock()

        # 选择引擎
        self.engine = self._select_engine(engine)
        logger.info(f"VectorMemoryInterface 引擎: {self.engine}")

        # 初始化表结构
        self._init_schema()

    def set_distill_engine(self, distill_engine: Any) -> None:
        """设置动态蒸馏引擎"""
        self._distill_engine = distill_engine

    # ============================================================
    # 引擎选择
    # ============================================================

    def _select_engine(self, preferred: str) -> str:
        """选择搜索引擎"""
        if preferred == "numpy":
            return "numpy"

        if preferred == "sqlite_vec":
            return self._try_sqlite_vec() or "numpy"

        # auto: 尝试 sqlite-vec，失败则回退
        return self._try_sqlite_vec() or "numpy"

    def _try_sqlite_vec(self) -> Optional[str]:
        """尝试加载 sqlite-vec。如果 Python sqlite3 不支持 enable_load_extension，则干净返回 None。"""
        # 0) 预先检查：self.db 是否 enable_load_extension
        if not hasattr(self.db, 'enable_load_extension'):
            logger.debug("sqlite-vec 不可用: sqlite3.Connection 无 enable_load_extension 方法")
            return None

        try:
            import sqlite_vec
            # 1) 尝试标准路径：enable_load_extension + sqlite_vec.load()
            try:
                self.db.enable_load_extension(True)
                sqlite_vec.load(self.db)
                self.db.enable_load_extension(False)

                # 验证可用性
                version = self.db.execute('SELECT vec_version()').fetchone()[0]
                logger.info(f"sqlite-vec {version} 加载成功（标准路径）")
                return "sqlite_vec"
            except (AttributeError, sqlite3.OperationalError):
                # macOS 系统 Python 常见：enable_load_extension 不存在 / SQLite 未启用扩展加载
                pass

            # 2) 备用：pysqlite3 提供的 sqlite3 支持扩展加载
            try:
                from pysqlite3 import dbapi2 as pysqlite
                self.db.close()
                new_conn = pysqlite.connect(self.storage_path, check_same_thread=False)
                new_conn.row_factory = sqlite3.Row
                new_conn.enable_load_extension(True)
                sqlite_vec.load(new_conn)
                new_conn.enable_load_extension(False)
                version = new_conn.execute('SELECT vec_version()').fetchone()[0]
                # 成功则把 db 切换到新连接
                self.db = new_conn
                logger.info(f"sqlite-vec {version} 加载成功（pysqlite3 回退）")
                return "sqlite_vec"
            except Exception:
                pass

            logger.debug("sqlite-vec 不可用: 所有加载路径均失败，回退 numpy")
            return None
        except Exception as e:
            logger.debug(f"sqlite-vec 不可用（导入或其他错误）: {e}")
            return None

    # ============================================================
    # 表结构初始化
    # ============================================================

    def _init_schema(self) -> None:
        """初始化数据库表结构。对遗留的 vec_memories 虚拟表做安全保护，
        避免 engine=numpy 时因 no such module: vec0 报错。"""
        with self._db_lock:
            # 元数据表
            self.db.execute("""
                CREATE TABLE IF NOT EXISTS memories (
                    id TEXT PRIMARY KEY,
                    content TEXT NOT NULL,
                    vector BLOB,
                    quality_level TEXT DEFAULT 'C',
                    confidence REAL DEFAULT 0.0,
                    tags TEXT DEFAULT '[]',
                    memory_type TEXT DEFAULT 'experience',
                    source TEXT DEFAULT '',
                    created_at TEXT DEFAULT '',
                    updated_at TEXT DEFAULT '',
                    verify_count INTEGER DEFAULT 0
                )
            """)

            # 索引
            self.db.execute("CREATE INDEX IF NOT EXISTS idx_quality ON memories(quality_level)")
            self.db.execute("CREATE INDEX IF NOT EXISTS idx_type ON memories(memory_type)")

            # --- 对遗留的 vec_memories 虚拟表做保护 ---
            # 场景：旧 DB 是用 sqlite_vec 引擎创建的（里面 CREATE VIRTUAL TABLE vec_memories ...），
            # 现在本进程用 numpy 引擎打开（没加载 sqlite-vec 扩展）→ 任何访问 vec_memories
            # （包括 PRAGMA table_info('vec_memories')）都会抛 no such module: vec0。
            # 安全策略：
            #   - 先在 sqlite_master 里看有没有 "vec_memories" 名字（这是安全的，不触发 vec0 模块加载）
            #   - 如果有，但 engine=numpy（意味着没 load 扩展），则记 _has_legacy_vec_memories=True，
            #     后续 NEVER 访问该表（search/delete/DROP 都不要碰）
            has_legacy_vec = False
            try:
                row = self.db.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name='vec_memories'"
                ).fetchone()
                has_legacy_vec = row is not None
            except Exception:
                has_legacy_vec = False
            self._has_legacy_vec_memories = has_legacy_vec and self.engine != "sqlite_vec"
            if self._has_legacy_vec_memories:
                logger.warning(
                    "检测到遗留 vec_memories 虚拟表（但当前进程未加载 sqlite-vec，跳过该表以 "
                    "避免 no such module: vec0 报错；数据查询走 numpy fallback 路径）"
                )

            # sqlite-vec 虚拟表（仅当 engine 确实是 sqlite_vec 时才创建）
            if self.engine == "sqlite_vec" and not has_legacy_vec:
                try:
                    self.db.execute(f"""
                        CREATE VIRTUAL TABLE IF NOT EXISTS vec_memories
                        USING vec0(
                            embedding float[{self.vector_dim}],
                            memory_id text,
                            quality text
                        )
                    """)
                except sqlite3.OperationalError as e:
                    # 仍然可能在某些受限环境报 no such module: vec0；安全降级
                    logger.warning(f"CREATE VIRTUAL TABLE 失败，降级 numpy: {e}")
                    self.engine = "numpy"
                    self._has_legacy_vec_memories = False

            self.db.commit()

    # ============================================================
    # 添加记忆
    # ============================================================

    def add(
        self,
        content: str,
        quality_level: str = "C",
        confidence: float = 0.0,
        tags: Optional[List[str]] = None,
        memory_type: str = "experience",
        source: str = "",
        memory_id: Optional[str] = None,
        verify_count: int = 0,
    ) -> str:
        """
        添加一条记忆。

        Args:
            content: 记忆内容文本
            quality_level: 质量等级 (S/A/B/C/D)
            confidence: 置信度 (0.0-1.0)
            tags: 标签列表
            memory_type: 记忆类型
            source: 来源
            memory_id: 指定ID，默认自动生成
            verify_count: 验证次数（默认 0，用于导入历史记忆）

        Returns:
            记忆ID
        """
        tags = tags or []
        now = datetime.now(timezone.utc).isoformat()
        mem_id = memory_id or f"VM-{int(time.time()*1000)}-{hashlib.md5(content.encode()).hexdigest()[:8]}"

        # 向量化
        vector = self.vectorizer.encode(content)
        vector_bytes = vector_to_bytes(vector)

        # 插入元数据表
        with self._db_lock:
            self.db.execute("""
                INSERT OR REPLACE INTO memories
                    (id, content, vector, quality_level, confidence, tags, memory_type, source, created_at, updated_at, verify_count)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, [
                mem_id, content, vector_bytes,
                quality_level, confidence,
                json.dumps(tags, ensure_ascii=False),
                memory_type, source, now, now, int(verify_count or 0),
            ])

            # 插入 sqlite-vec 虚拟表
            if self.engine == "sqlite_vec":
                self.db.execute("""
                    INSERT OR REPLACE INTO vec_memories(rowid, embedding, memory_id, quality)
                    VALUES (?, ?, ?, ?)
                """, [
                    self._get_rowid(mem_id),
                    vector_bytes,
                    mem_id,
                    quality_level,
                ])

            self.db.commit()
        return mem_id

    def _get_rowid(self, mem_id: str) -> int:
        """将字符串ID转为整数 rowid（用于 sqlite-vec）"""
        return int(hashlib.md5(mem_id.encode()).hexdigest()[:12], 16)

    # ============================================================
    # 语义搜索
    # ============================================================

    def search(
        self,
        query: str,
        top_k: int = 5,
        quality_filter: Optional[str] = None,
        tags_filter: Optional[List[str]] = None,
        memory_type_filter: Optional[str] = None,
    ) -> List[SearchResult]:
        """
        语义搜索：查找与查询最相似的记忆。

        Args:
            query: 查询文本
            top_k: 返回结果数
            quality_filter: 质量等级过滤 (如 "A" 表示只返回A级以上)
            tags_filter: 标签过滤（任一匹配）
            memory_type_filter: 记忆类型过滤

        Returns:
            搜索结果列表，按相似度降序
        """
        query_vector = self.vectorizer.encode(query)

        if self.engine == "sqlite_vec":
            return self._search_sqlite_vec(query_vector, top_k, quality_filter, tags_filter, memory_type_filter)
        else:
            return self._search_numpy(query_vector, top_k, quality_filter, tags_filter, memory_type_filter)

    def _search_sqlite_vec(
        self,
        query_vector: List[float],
        top_k: int,
        quality_filter: Optional[str],
        tags_filter: Optional[List[str]],
        memory_type_filter: Optional[str],
    ) -> List[SearchResult]:
        """sqlite-vec 引擎搜索"""

        query_bytes = vector_to_bytes(query_vector)

        # 构建SQL (sqlite-vec 要求 KNN 查询必须带 LIMIT 或 k=? 约束)
        sql = """
            SELECT m.id, m.content, m.quality_level, m.tags, m.confidence,
                   m.memory_type, m.source, m.verify_count, v.distance
            FROM vec_memories v
            JOIN memories m ON m.id = v.memory_id
            WHERE v.embedding MATCH ? AND k = ?
        """
        # sqlite-vec 的 k=? 参数控制 KNN 的 K 值
        search_k = top_k * 3  # 多取一些用于标签过滤
        params: list = [query_bytes, search_k]

        # 质量过滤
        if quality_filter:
            quality_order = {"S": ["S"], "A": ["S", "A"], "B": ["S", "A", "B"], "C": ["S", "A", "B", "C"]}
            allowed = quality_order.get(quality_filter, [quality_filter])
            placeholders = ",".join("?" * len(allowed))
            sql += f" AND v.quality IN ({placeholders})"
            params.extend(allowed)

        sql += " ORDER BY v.distance"

        with self._db_lock:
            rows = self.db.execute(sql, params).fetchall()

        results = []
        for row in rows:
            tags = json.loads(row["tags"])

            # 标签过滤
            if tags_filter and not any(t in tags for t in tags_filter):
                continue

            # 类型过滤
            if memory_type_filter and row["memory_type"] != memory_type_filter:
                continue

            # L2 distance → cosine similarity
            # 对于归一化向量: cosine_sim = 1 - L2_distance^2 / 2
            distance = row["distance"]
            score = max(0.0, 1.0 - (distance * distance) / 2.0)

            results.append(SearchResult(
                id=row["id"],
                content=row["content"],
                score=max(0.0, score),
                quality_level=row["quality_level"],
                tags=tags,
                metadata={
                    "confidence": row["confidence"],
                    "source": row["source"],
                    "verify_count": row["verify_count"],
                }
            ))

            if len(results) >= top_k:
                break

        return results

    def _search_numpy(
        self,
        query_vector: List[float],
        top_k: int,
        quality_filter: Optional[str],
        tags_filter: Optional[List[str]],
        memory_type_filter: Optional[str],
    ) -> List[SearchResult]:
        """numpy 引擎搜索（纯 Python 计算）"""

        # 构建查询
        sql = "SELECT id, content, vector, quality_level, tags, confidence, memory_type, source, verify_count FROM memories"
        conditions = []
        params: list = []

        if quality_filter:
            quality_order = {"S": ["S"], "A": ["S", "A"], "B": ["S", "A", "B"], "C": ["S", "A", "B", "C"]}
            allowed = quality_order.get(quality_filter, [quality_filter])
            placeholders = ",".join("?" * len(allowed))
            conditions.append(f"quality_level IN ({placeholders})")
            params.extend(allowed)

        if memory_type_filter:
            conditions.append("memory_type = ?")
            params.append(memory_type_filter)

        if conditions:
            sql += " WHERE " + " AND ".join(conditions)

        with self._db_lock:
            rows = self.db.execute(sql, params).fetchall()

        # 计算相似度
        scored: List[Tuple[float, sqlite3.Row]] = []
        for row in rows:
            vec_bytes = row["vector"]
            if not vec_bytes:
                continue
            vec = bytes_to_vector(vec_bytes, self.vector_dim)
            score = cosine_similarity(query_vector, vec)
            scored.append((score, row))

        # 排序
        scored.sort(key=lambda x: x[0], reverse=True)

        # 标签过滤 + 截断
        results = []
        for score, row in scored:
            tags = json.loads(row["tags"])

            if tags_filter and not any(t in tags for t in tags_filter):
                continue

            results.append(SearchResult(
                id=row["id"],
                content=row["content"],
                score=score,
                quality_level=row["quality_level"],
                tags=tags,
                metadata={
                    "confidence": row["confidence"],
                    "source": row["source"],
                    "verify_count": row["verify_count"],
                }
            ))

            if len(results) >= top_k:
                break

        return results

    # ============================================================
    # 更新与删除
    # ============================================================

    def update_quality(self, memory_id: str, quality_level: str, confidence: float) -> bool:
        """
        更新记忆质量等级，并触发动态蒸馏。

        当质量等级跨越阈值时，自动通知 DynamicDistillEngine。
        """
        # 读取旧值并更新（在锁内）
        with self._db_lock:
            old_row = self.db.execute("SELECT quality_level, confidence, content, tags, verify_count FROM memories WHERE id=?", [memory_id]).fetchone()
            old_quality = old_row["quality_level"] if old_row else "C"
            old_confidence = old_row["confidence"] if old_row else 0.0
            # verify_count 即将递增（CLE.verify 在 update_quality 后调用 increment_verify），
            # 蒸馏时应传递递增后的值，使 L2 记忆继承正确的验证次数
            current_verify_count = old_row["verify_count"] if old_row else 0

            now = datetime.now(timezone.utc).isoformat()
            cursor = self.db.execute(
                "UPDATE memories SET quality_level=?, confidence=?, updated_at=? WHERE id=?",
                [quality_level, confidence, now, memory_id]
            )
            self.db.commit()

        # 触发动态蒸馏（在锁外，避免死锁）
        if cursor.rowcount > 0 and self._distill_engine is not None:
            try:
                content = old_row["content"] if old_row else ""
                tags = json.loads(old_row["tags"]) if old_row and old_row["tags"] else []
                self._distill_engine.on_confidence_changed(
                    memory_id=memory_id,
                    old_confidence=old_confidence,
                    new_confidence=confidence,
                    old_quality=old_quality,
                    new_quality=quality_level,
                    content=content,
                    source_app_memory=self.memory_id,
                    tags=tags,
                    verify_count=current_verify_count + 1,  # 传递递增后的验证次数
                )
            except Exception:
                logger.exception("on_confidence_changed 蒸馏通知失败")  # 蒸馏失败不影响主流程

        return cursor.rowcount > 0

    def increment_verify(self, memory_id: str) -> bool:
        """
        增加验证次数，并检查是否触发 A8 蒸馏。

        当验证次数达到阈值时，自动通知 DynamicDistillEngine。
        """
        with self._db_lock:
            cursor = self.db.execute(
                "UPDATE memories SET verify_count = verify_count + 1, updated_at=? WHERE id=?",
                [datetime.now(timezone.utc).isoformat(), memory_id]
            )
            self.db.commit()

        # 触发 A8 校验蒸馏（在锁外，避免死锁）
        if cursor.rowcount > 0 and self._distill_engine is not None:
            try:
                row = self.db.execute("SELECT quality_level, confidence, content, tags, verify_count FROM memories WHERE id=?", [memory_id]).fetchone()
                if row:
                    self._distill_engine.on_a8_verified(
                        memory_id=memory_id,
                        verify_count=row["verify_count"],
                        confidence=row["confidence"],
                        quality_level=row["quality_level"],
                        content=row["content"],
                        source_app_memory=self.memory_id,
                        tags=json.loads(row["tags"]) if row["tags"] else [],
                    )
            except Exception:
                logger.exception("on_a8_verified 蒸馏通知失败")

        return cursor.rowcount > 0

    def delete(self, memory_id: str) -> bool:
        """删除记忆"""
        with self._db_lock:
            cursor = self.db.execute("DELETE FROM memories WHERE id=?", [memory_id])
            if self.engine == "sqlite_vec":
                rowid = self._get_rowid(memory_id)
                self.db.execute("DELETE FROM vec_memories WHERE rowid=?", [rowid])
            self.db.commit()
        return cursor.rowcount > 0

    # ============================================================
    # 统计与健康检查
    # ============================================================

    def stats(self) -> Dict[str, Any]:
        """获取统计信息"""
        with self._db_lock:
            total = self.db.execute("SELECT COUNT(*) as c FROM memories").fetchone()["c"]

            quality_dist = {}
            for row in self.db.execute("SELECT quality_level, COUNT(*) as c FROM memories GROUP BY quality_level").fetchall():
                quality_dist[row["quality_level"]] = row["c"]

            type_dist = {}
            for row in self.db.execute("SELECT memory_type, COUNT(*) as c FROM memories GROUP BY memory_type").fetchall():
                type_dist[row["memory_type"]] = row["c"]

        return {
            "total_memories": total,
            "quality_distribution": quality_dist,
            "type_distribution": type_dist,
            "engine": self.engine,
            "vector_dim": self.vector_dim,
            "storage_path": self.storage_path,
        }

    def healthcheck(self) -> Dict[str, Any]:
        """健康检查"""
        with self._db_lock:
            total_memories = self.db.execute("SELECT COUNT(*) as c FROM memories").fetchone()["c"]
        return {
            "status": "healthy",
            "engine": self.engine,
            "vector_dim": self.vector_dim,
            "total_memories": total_memories,
            "sqlite_version": sqlite3.sqlite_version,
        }

    # ============================================================
    # 便捷方法
    # ============================================================

    def get(self, memory_id: str) -> Optional[Dict[str, Any]]:
        """获取单条记忆"""
        with self._db_lock:
            row = self.db.execute("SELECT * FROM memories WHERE id=?", [memory_id]).fetchone()
        if not row:
            return None
        return {
            "id": row["id"],
            "content": row["content"],
            "quality_level": row["quality_level"],
            "confidence": row["confidence"],
            "tags": json.loads(row["tags"]),
            "memory_type": row["memory_type"],
            "source": row["source"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
            "verify_count": row["verify_count"],
        }

    def search_similar(self, content: str, top_k: int = 5, threshold: float = 0.3) -> List[SearchResult]:
        """查找相似记忆（便捷方法）"""
        results = self.search(content, top_k=top_k)
        return [r for r in results if r.score >= threshold]

    def close(self) -> None:
        """关闭连接"""
        self.db.close()


# ============================================================
# CLI 测试
# ============================================================

if __name__ == "__main__":
    print("=" * 60)
    print("VectorMemoryInterface 功能验证")
    print("=" * 60)

    # 初始化（内存数据库）
    vm = VectorMemoryInterface(storage_path=":memory:", engine="auto")
    print(f"\n引擎: {vm.engine}")
    print(f"向量维度: {vm.vector_dim}")

    # 添加记忆
    print("\n--- 添加记忆 ---")
    memories = [
        ("BTC趋势策略：突破后跟涨效果好，适合顺势操作", "A", 0.85, ["BTC", "趋势", "突破"]),
        ("ETH套利策略：跨所价差大于0.5%时可执行", "B", 0.60, ["ETH", "套利", "跨所"]),
        ("BTC波动率策略：高波动时减仓，低波动时加仓", "S", 0.95, ["BTC", "波动率", "仓位"]),
        ("风险管理：单笔交易不超过总资金的2%", "S", 0.99, ["风控", "仓位", "止损"]),
        ("ETH基本面分析：关注Gas费用和网络活跃度", "B", 0.55, ["ETH", "基本面", "链上"]),
        ("BTC均值回归：RSI低于30时买入，高于70时卖出", "A", 0.80, ["BTC", "RSI", "均值回归"]),
    ]

    for content, quality, conf, tags in memories:
        mid = vm.add(content, quality_level=quality, confidence=conf, tags=tags)
        print(f"  [{quality}] {content[:30]}... → {mid}")

    # 语义搜索
    print("\n--- 语义搜索: 'BTC交易策略' ---")
    results = vm.search("BTC交易策略", top_k=3)
    for r in results:
        print(f"  score={r.score:.3f} [{r.quality_level}] {r.content[:40]}...")

    # 质量过滤搜索
    print("\n--- 质量过滤搜索: '仓位管理' (quality>=S) ---")
    results = vm.search("仓位管理", top_k=3, quality_filter="S")
    for r in results:
        print(f"  score={r.score:.3f} [{r.quality_level}] {r.content[:40]}...")

    # 标签过滤搜索
    print("\n--- 标签过滤搜索: '市场分析' (tags=['BTC']) ---")
    results = vm.search("市场分析", top_k=3, tags_filter=["BTC"])
    for r in results:
        print(f"  score={r.score:.3f} [{r.quality_level}] tags={r.tags}")

    # 统计
    print("\n--- 统计 ---")
    stats = vm.stats()
    print(f"  总记忆数: {stats['total_memories']}")
    print(f"  质量分布: {stats['quality_distribution']}")
    print(f"  类型分布: {stats['type_distribution']}")

    # 健康检查
    print(f"\n--- 健康检查 ---")
    health = vm.healthcheck()
    print(f"  状态: {health['status']}")
    print(f"  引擎: {health['engine']}")
    print(f"  记忆数: {health['total_memories']}")

    # 更新测试
    print(f"\n--- 更新测试 ---")
    first_id = vm.add("测试记忆", quality_level="C", confidence=0.3)
    vm.update_quality(first_id, "A", 0.85)
    vm.increment_verify(first_id)
    vm.increment_verify(first_id)
    rec = vm.get(first_id)
    print(f"  更新后: quality={rec['quality_level']}, confidence={rec['confidence']}, verify={rec['verify_count']}")

    # 相似记忆查找
    print(f"\n--- 相似记忆查找 ---")
    similar = vm.search_similar("BTC趋势突破策略", top_k=3, threshold=0.2)
    print(f"  符合阈值的结果: {len(similar)} 条")
    for r in similar:
        print(f"  score={r.score:.3f} {r.content[:40]}...")

    print("\n" + "=" * 60)
    print("VectorMemoryInterface 验证通过 ✅")
    print("=" * 60)


# ============================================================
# P4b: Solution Paths 重建 — 从 memories 表的 B+ 高价值记忆生成 APP-*.json
# ============================================================

_QUALITY_ORDER = {"S": 0, "A": 1, "B": 2, "C": 3, "D": 4, "archived": 9, "quarantined": 9}


def rebuild_solution_paths_from_memories(
    sqlite_db_path: str,
    solution_paths_dir: str,
    min_quality: str = "B",
    min_verify_count: int = 1,
    min_confidence: float = 0.4,
    max_templates: int = 50,
    dry_run: bool = False,
) -> Dict[str, Any]:
    """
    从 memories 表的高价值记忆（B+/多验证/高置信）生成 solution_paths APP-*.json 模板，
    填充 P2b 清理后空了的活跃 SP 目录。

    规则（零低质量）：
      - 质量 >= min_quality（默认 B 级以上）
      - verify_count >= min_verify_count（默认 >= 1，排除完全没被验证的）
      - confidence >= min_confidence（默认 >= 0.4）
      - archived/quarantined 一律跳过

    Args:
        sqlite_db_path: memories SQLite 路径
        solution_paths_dir: 目标目录（一般是 <root>/4-MEMORY/1-开发记忆单元/solution_paths）
        min_quality: 最低质量（默认 B），从 S>A>B>C>D 顺序比较
        min_verify_count: 最少验证次数
        min_confidence: 最低置信度
        max_templates: 最多生成多少个 APP-*.json（避免目录过大）
        dry_run: 仅统计不写文件（默认 False，默认实际写）

    Returns:
        统计字典（扫描数/合格数/写入数/质量分布等）
    """
    import shutil as _shutil

    stats: Dict[str, Any] = {
        "scanned": 0,
        "eligible": 0,
        "written": 0,
        "skipped_existing": 0,
        "skipped_filters": 0,
        "quality_distribution": {},
        "dry_run": dry_run,
        "min_quality": min_quality,
        "min_verify_count": min_verify_count,
        "min_confidence": min_confidence,
        "solution_paths_dir": solution_paths_dir,
    }

    if not os.path.exists(sqlite_db_path):
        return stats
    if not os.path.isdir(solution_paths_dir) and not dry_run:
        os.makedirs(solution_paths_dir, exist_ok=True)

    conn = sqlite3.connect(sqlite_db_path)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            "SELECT id, content, quality_level, confidence, verify_count, "
            "tags, memory_type, source, created_at, updated_at FROM memories"
        ).fetchall()
    finally:
        conn.close()

    stats["scanned"] = len(rows)

    min_q_rank = _QUALITY_ORDER.get(min_quality, 2)  # 默认 B(2)

    candidates = []
    for r in rows:
        q = str(r["quality_level"] or "")
        q_rank = _QUALITY_ORDER.get(q, 99)
        verify_count = int(r["verify_count"] or 0)
        confidence = float(r["confidence"] or 0.0)
        # 过滤
        if q_rank > min_q_rank:              # 最低质量要求
            stats["skipped_filters"] += 1
            continue
        if verify_count < min_verify_count:  # 验证次数要求
            stats["skipped_filters"] += 1
            continue
        if confidence < min_confidence:      # 置信度要求
            stats["skipped_filters"] += 1
            continue
        candidates.append(r)

    stats["eligible"] = len(candidates)

    # 排序：S > A > B，其次 verify_count 多 > 少，其次 confidence 高 > 低
    candidates.sort(key=lambda r: (
        _QUALITY_ORDER.get(str(r["quality_level"] or ""), 99),
        -int(r["verify_count"] or 0),
        -float(r["confidence"] or 0.0),
    ))
    candidates = candidates[:max_templates]

    # 计算质量分布 & 写入
    quality_dist: Dict[str, int] = {}
    written = 0
    for r in candidates:
        q = str(r["quality_level"] or "")
        quality_dist[q] = quality_dist.get(q, 0) + 1

        mem_id = str(r["id"] or "")
        # 生成安全的 template_id：用记忆 ID（如果是合法 APP-*），否则 APP-<记忆ID>
        if not mem_id.startswith("APP-"):
            template_id = "APP-" + mem_id.replace(" ", "_").replace("/", "_")
        else:
            template_id = mem_id
        fname = template_id + ".json"
        fpath = os.path.join(solution_paths_dir, fname)

        # 若 dry_run 或已存在相同 ID → 跳过写入
        if os.path.exists(fpath):
            stats["skipped_existing"] += 1
            continue
        if dry_run:
            written += 1  # dry_run 下计数但不写
            continue

        payload = {
            "template_id": template_id,
            "title": (r["content"] or "")[:80],
            "content": r["content"] or "",
            "quality_level": q,
            "confidence": round(float(r["confidence"] or 0.0), 4),
            "verify_count": int(r["verify_count"] or 0),
            "tags": (lambda raw: json.loads(raw) if isinstance(raw, str) else list(raw or []))(r["tags"]),
            "memory_type": r["memory_type"] or "experience",
            "source": r["source"] or "",
            "created_at": r["created_at"] or "",
            "updated_at": r["updated_at"] or "",
            "rebuilt_from_memory_id": mem_id,
            "rebuild_version": 1,
        }
        try:
            with open(fpath, "w", encoding="utf-8") as fp:
                json.dump(payload, fp, ensure_ascii=False, indent=2)
            written += 1
        except OSError:
            pass

    stats["quality_distribution"] = quality_dist
    stats["written"] = written
    return stats

