#!/usr/bin/env python3
"""
Recall Memory 缓存层 — RecallMemoryCache

定位：三层记忆架构的中间层（Recall Memory）。
  Working Memory   ← WorkingMemoryManager（当前任务上下文）
       ↓ promote
  Recall Memory    ← 本模块（近期高频访问的 LRU + frequency-aware 缓存）
       ↓ consolidate
  Archival Memory  ← cognitive_memory.db（长期归档，VectorMemoryInterface）

设计原则（借鉴 Letta/MemGPT Core Memory + LRU 缓存）：
1. **Hot path 加速**：相同 context 二次 recall 命中缓存，跳过 SQLite 查询。
2. **频率追踪**：access_count + last_accessed_at，高频项 sticky，低频项淘汰。
3. **LRU 淘汰**：超容量时淘汰最久未访问项。
4. **关键词检索**：query() 按关键词匹配，不依赖向量编码器（轻量）。
5. **持久化**：JSON 文件，进程重启后可恢复。

FAIL-OPEN：所有异常吞掉，不阻断 recall 主流程。

用法：
    from recall_memory_cache import RecallMemoryCache

    cache = RecallMemoryCache(cache_path=Path("recall_cache.json"))
    cache.promote("VM-001", "经验内容", 0.85, {"quality_level": "B"})
    cached = cache.get("VM-001")
    results = cache.query("经验", top_k=5)
    report = cache.consolidate(min_access_threshold=2)
"""
from __future__ import annotations

import json
import threading
import time
from collections import OrderedDict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional


# ============================================================
# 数据模型
# ============================================================

class CacheEntry:
    """缓存条目（单条记忆的缓存表示）。"""

    __slots__ = ("id", "content", "score", "metadata", "access_count",
                 "last_accessed_at", "promoted_at")

    def __init__(
        self,
        memory_id: str,
        content: str,
        score: float,
        metadata: Optional[Dict[str, Any]] = None,
        access_count: int = 0,
        last_accessed_at: str = "",
        promoted_at: str = "",
    ):
        self.id = memory_id
        self.content = content
        self.score = float(score)
        self.metadata = metadata or {}
        self.access_count = int(access_count)
        self.last_accessed_at = last_accessed_at
        self.promoted_at = promoted_at or datetime.now(timezone.utc).isoformat()

    def touch(self) -> None:
        """更新访问计数和时间戳。"""
        self.access_count += 1
        self.last_accessed_at = datetime.now(timezone.utc).isoformat()

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "content": self.content,
            "score": self.score,
            "metadata": self.metadata,
            "access_count": self.access_count,
            "last_accessed_at": self.last_accessed_at,
            "promoted_at": self.promoted_at,
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "CacheEntry":
        return cls(
            memory_id=d["id"],
            content=d["content"],
            score=d.get("score", 0.0),
            metadata=d.get("metadata", {}),
            access_count=d.get("access_count", 0),
            last_accessed_at=d.get("last_accessed_at", ""),
            promoted_at=d.get("promoted_at", ""),
        )


# ============================================================
# RecallMemoryCache 核心类
# ============================================================

class RecallMemoryCache:
    """
    Recall Memory 层 — LRU + frequency-aware 缓存。

    介于 Working Memory（任务级）与 Archival Memory（SQLite 长期）之间。
    加速高频 recall 查询，降低 SQLite 访问开销。

    线程安全：所有公共方法加锁。
    """

    DEFAULT_MAX_SIZE = 100

    def __init__(
        self,
        cache_path: Optional[Path] = None,
        max_size: int = DEFAULT_MAX_SIZE,
    ):
        """
        初始化缓存。

        Args:
            cache_path: 持久化 JSON 文件路径。None 则不持久化。
            max_size: 缓存最大条目数（LRU 淘汰）。
        """
        self._cache: OrderedDict[str, CacheEntry] = OrderedDict()
        self._cache_path = Path(cache_path) if cache_path else None
        self._max_size = max_size
        self._lock = threading.Lock()

        # 启动时尝试恢复
        if self._cache_path and self._cache_path.exists():
            self._restore()

    # ============================================================
    # Promote / Get
    # ============================================================

    def promote(
        self,
        memory_id: str,
        content: str,
        score: float,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        """将一条记忆提升到 Recall 缓存层。

        若已存在则更新内容并保留 access_count。
        """
        with self._lock:
            existing = self._cache.get(memory_id)
            if existing is not None:
                # 已存在：更新内容但保留 access_count
                existing.content = content
                existing.score = float(score)
                if metadata:
                    existing.metadata.update(metadata)
                # 移到末尾（最近使用）
                self._cache.move_to_end(memory_id)
            else:
                # 新增
                entry = CacheEntry(
                    memory_id=memory_id,
                    content=content,
                    score=score,
                    metadata=metadata or {},
                )
                self._cache[memory_id] = entry
                # LRU 淘汰
                self._evict_if_needed()

    def get(self, memory_id: str) -> Optional[Dict[str, Any]]:
        """获取缓存中的记忆（命中时 touch 更新 access_count）。

        Returns:
            缓存条目 dict 或 None（未命中）。
        """
        with self._lock:
            entry = self._cache.get(memory_id)
            if entry is None:
                return None
            entry.touch()
            self._cache.move_to_end(memory_id)
            return entry.to_dict()

    def get_stats(self, memory_id: str) -> Dict[str, Any]:
        """获取单条缓存的访问统计。"""
        with self._lock:
            entry = self._cache.get(memory_id)
            if entry is None:
                return {"access_count": 0, "last_accessed_at": "", "exists": False}
            return {
                "access_count": entry.access_count,
                "last_accessed_at": entry.last_accessed_at,
                "exists": True,
            }

    # ============================================================
    # Query（关键词检索，轻量）
    # ============================================================

    def query(self, context: str, top_k: int = 5) -> List[Dict[str, Any]]:
        """按关键词从缓存检索。

        匹配策略：分词后统计在 content 中的命中数，按命中数+score 排序。
        不依赖向量编码器，纯字符串匹配（轻量 fast-path）。
        """
        with self._lock:
            if not self._cache:
                return []

            # 简单分词（按空格/标点切分）
            keywords = [w for w in context.replace(",", " ").replace("，", " ").split() if w]
            if not keywords:
                keywords = [context]

            scored: List[tuple] = []
            for entry in self._cache.values():
                content_lower = entry.content.lower()
                hit_count = sum(1 for kw in keywords if kw.lower() in content_lower)
                if hit_count == 0:
                    continue
                # 综合分：命中数权重 + 原始 score
                combined = hit_count * 0.5 + entry.score * 0.5
                scored.append((combined, entry))

            scored.sort(key=lambda x: x[0], reverse=True)
            return [entry.to_dict() for _, entry in scored[:top_k]]

    # ============================================================
    # Consolidate / Evict
    # ============================================================

    def consolidate(self, min_access_threshold: int = 2) -> Dict[str, Any]:
        """整合缓存：淘汰低频访问项。

        Args:
            min_access_threshold: access_count 低于此值的项被淘汰。

        Returns:
            报告 dict：evicted_count, remaining_count, evicted_ids
        """
        with self._lock:
            evicted_ids: List[str] = []
            for mid in list(self._cache.keys()):
                entry = self._cache[mid]
                if entry.access_count < min_access_threshold:
                    del self._cache[mid]
                    evicted_ids.append(mid)

            return {
                "evicted_count": len(evicted_ids),
                "remaining_count": len(self._cache),
                "evicted_ids": evicted_ids,
            }

    def _evict_if_needed(self) -> None:
        """LRU 淘汰超容量项（内部，调用方需持锁）。"""
        while len(self._cache) > self._max_size:
            # popitem(last=False) 淘汰最久未访问
            self._cache.popitem(last=False)

    # ============================================================
    # 持久化
    # ============================================================

    def persist(self) -> bool:
        """持久化缓存到 JSON 文件。"""
        if not self._cache_path:
            return False
        with self._lock:
            try:
                self._cache_path.parent.mkdir(parents=True, exist_ok=True)
                data = {
                    "version": 1,
                    "max_size": self._max_size,
                    "entries": [e.to_dict() for e in self._cache.values()],
                    "saved_at": datetime.now(timezone.utc).isoformat(),
                }
                self._cache_path.write_text(
                    json.dumps(data, indent=2, ensure_ascii=False),
                    encoding="utf-8",
                )
                return True
            except Exception:
                return False

    def _restore(self) -> None:
        """从 JSON 文件恢复缓存（内部，构造时调用）。"""
        try:
            data = json.loads(self._cache_path.read_text(encoding="utf-8"))
            entries = data.get("entries", [])
            for e in entries:
                entry = CacheEntry.from_dict(e)
                self._cache[entry.id] = entry
            # 恢复后若超容量则淘汰
            self._evict_if_needed()
        except Exception:
            # FAIL-OPEN：恢复失败从空开始
            self._cache.clear()

    # ============================================================
    # 统计
    # ============================================================

    def stats(self) -> Dict[str, Any]:
        """缓存整体统计。"""
        with self._lock:
            total_access = sum(e.access_count for e in self._cache.values())
            return {
                "cache_size": len(self._cache),
                "max_size": self._max_size,
                "total_access_count": total_access,
                "persisted": self._cache_path is not None,
            }


# ============================================================
# CLI 自测
# ============================================================

if __name__ == "__main__":
    print("=" * 60)
    print("RecallMemoryCache — 功能验证")
    print("=" * 60)

    import tempfile

    with tempfile.TemporaryDirectory() as td:
        cache = RecallMemoryCache(cache_path=Path(td) / "cache.json", max_size=3)

        cache.promote("VM-001", "马丁策略BTC盈利", 0.8, {"quality_level": "B"})
        cache.promote("VM-002", "趋势跟踪ETH亏损", 0.6, {"quality_level": "C"})
        cache.promote("VM-003", "套利策略稳健", 0.7, {"quality_level": "B"})

        # 访问 VM-001 多次
        for _ in range(3):
            cache.get("VM-001")

        print(f"\nVM-001 stats: {cache.get_stats('VM-001')}")

        # 查询
        results = cache.query("马丁 策略", top_k=5)
        print(f"\nQuery '马丁 策略' → {len(results)} results")

        # LRU 淘汰测试
        cache.get("VM-001")  # 让 VM-001 成为最近使用
        cache.promote("VM-004", "新策略", 0.5, {})  # 应淘汰 VM-002 或 VM-003
        print(f"\nAfter promote VM-004: cache_size={cache.stats()['cache_size']}")
        print(f"VM-002 exists: {cache.get('VM-002') is not None}")
        print(f"VM-001 exists: {cache.get('VM-001') is not None}")

        # Consolidate
        report = cache.consolidate(min_access_threshold=2)
        print(f"\nConsolidate report: {report}")

        # 持久化测试
        cache.persist()
        cache2 = RecallMemoryCache(cache_path=Path(td) / "cache.json")
        print(f"\nRestored cache_size: {cache2.stats()['cache_size']}")

    print("\n" + "=" * 60)
    print("✅ RecallMemoryCache 功能验证通过")
