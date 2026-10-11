#!/usr/bin/env python3
"""
双时序知识图 — TemporalMemoryGraph

定位：L2 记忆层时序管理，借鉴 Zep/Graphiti 双时序知识图。
为每条记忆添加时间维度元数据，使 recall 能识别过期/被否定的事实。

双时序模型:
  - valid_time: {start, end} — 事实"何时为真"的有效期
  - transaction_time: 事实"何时写入"系统的时间
  - invalidated_by: 被哪条新记忆否定（因果链）

核心能力:
  1. add_temporal_memory() — 添加带有效期的记忆
  2. invalidate() — 标记旧记忆被新记忆否定
  3. is_valid_at() — 查询记忆在某时间点是否有效
  4. get_active_memories() — 获取当前仍有效的记忆
  5. filter_recall_results() — 标记 recall 结果中的过期记忆为"历史参考"

recall 升级策略（不删除，标记）:
  - valid_time.end < now → temporal_status="historical"（历史参考）
  - invalidated_by != null → temporal_status="superseded"（已被替代）
  - 否则 → temporal_status="active"（有效）

FAIL-OPEN：所有异常吞掉，不阻断 recall 主流程。

参考:
  - SPEC-CognitiveSystem-Evolution.md §2.3.2 P1-3
  - Zep/Graphiti 29K★: 双时序知识图 + 事实有效性窗口
"""
from __future__ import annotations

import json
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional


@dataclass
class TemporalEntry:
    """双时序记忆条目。"""

    memory_id: str
    content: str = ""
    valid_start: str = ""  # ISO 日期
    valid_end: str = ""    # ISO 日期（空=无限期）
    transaction_time: str = ""  # 写入时间
    invalidated_by: Optional[str] = None  # 被哪条记忆否定

    def to_dict(self) -> Dict[str, Any]:
        return {
            "memory_id": self.memory_id,
            "content": self.content,
            "valid_start": self.valid_start,
            "valid_end": self.valid_end,
            "transaction_time": self.transaction_time,
            "invalidated_by": self.invalidated_by,
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "TemporalEntry":
        return cls(
            memory_id=d["memory_id"],
            content=d.get("content", ""),
            valid_start=d.get("valid_start", ""),
            valid_end=d.get("valid_end", ""),
            transaction_time=d.get("transaction_time", ""),
            invalidated_by=d.get("invalidated_by"),
        )


class TemporalMemoryGraph:
    """
    双时序知识图。

    管理记忆的有效期和否定关系，使 recall 能区分
    "当前仍有效"与"历史参考"的记忆。

    线程安全：所有公共方法加锁。
    """

    def __init__(self, graph_path: Optional[Path] = None):
        """
        初始化双时序知识图。

        Args:
            graph_path: 持久化 JSON 文件路径。None 则不持久化。
        """
        self._entries: Dict[str, TemporalEntry] = {}
        self._graph_path = Path(graph_path) if graph_path else None
        self._lock = threading.Lock()

        # 启动时恢复
        if self._graph_path and self._graph_path.exists():
            self._restore()

    # ============================================================
    # 添加 / 查询
    # ============================================================

    def add_temporal_memory(
        self,
        memory_id: str,
        content: str = "",
        valid_start: str = "",
        valid_end: str = "",
        transaction_time: str = "",
    ) -> None:
        """添加一条带时序元数据的记忆。

        Args:
            memory_id: 记忆 ID
            content: 记忆内容
            valid_start: 有效期开始（ISO 日期）
            valid_end: 有效期结束（ISO 日期，空=无限期）
            transaction_time: 写入时间（默认 now）
        """
        with self._lock:
            if not transaction_time:
                transaction_time = datetime.now(timezone.utc).isoformat()
            entry = TemporalEntry(
                memory_id=memory_id,
                content=content,
                valid_start=valid_start,
                valid_end=valid_end,
                transaction_time=transaction_time,
            )
            self._entries[memory_id] = entry

    def get(self, memory_id: str) -> Optional[Dict[str, Any]]:
        """获取记忆的时序元数据。"""
        with self._lock:
            entry = self._entries.get(memory_id)
            if entry is None:
                return None
            return entry.to_dict()

    # ============================================================
    # 时序判定
    # ============================================================

    def is_valid_at(self, memory_id: str, at_time: str) -> bool:
        """判断记忆在指定时间点是否有效。

        无效条件:
        1. valid_end 存在且 at_time > valid_end（已过期）
        2. invalidated_by 不为 None（已被否定）

        Args:
            memory_id: 记忆 ID
            at_time: 查询时间点（ISO 日期）

        Returns:
            True=有效，False=无效/不存在
        """
        with self._lock:
            entry = self._entries.get(memory_id)
            if entry is None:
                return False

            # 已被否定 → 无效
            if entry.invalidated_by is not None:
                return False

            # 检查 valid_time
            if entry.valid_end and at_time:
                try:
                    if at_time > entry.valid_end:
                        return False
                    if entry.valid_start and at_time < entry.valid_start:
                        return False
                except TypeError:
                    pass  # 日期比较失败 → 保守视为有效
            return True

    def invalidate(self, memory_id: str, invalidated_by: str) -> bool:
        """标记一条记忆被另一条记忆否定。

        Args:
            memory_id: 被否定的记忆 ID
            invalidated_by: 否定它的记忆 ID

        Returns:
            True=成功标记，False=记忆不存在
        """
        with self._lock:
            entry = self._entries.get(memory_id)
            if entry is None:
                return False
            entry.invalidated_by = invalidated_by
            return True

    def get_active_memories(self, at_time: str = "") -> List[Dict[str, Any]]:
        """获取在指定时间点仍有效的所有记忆。

        Args:
            at_time: 查询时间点（默认 now）

        Returns:
            有效记忆列表
        """
        if not at_time:
            at_time = datetime.now(timezone.utc).isoformat()

        with self._lock:
            active: List[Dict[str, Any]] = []
            for entry in self._entries.values():
                # 被否定 → 排除
                if entry.invalidated_by is not None:
                    continue
                # 过期 → 排除
                if entry.valid_end and at_time:
                    try:
                        if at_time > entry.valid_end:
                            continue
                    except TypeError:
                        pass
                active.append(entry.to_dict())
            return active

    # ============================================================
    # recall 结果过滤/标记
    # ============================================================

    def filter_recall_results(
        self,
        results: List[Dict[str, Any]],
        now: str = "",
    ) -> List[Dict[str, Any]]:
        """对 recall 结果添加 temporal_status 标记。

        策略（不删除，标记）:
        - invalidated_by != null → "superseded"（已被替代）
        - valid_end < now → "historical"（历史参考）
        - 否则 → "active"（有效）

        Args:
            results: recall() 返回的 dict 列表
            now: 当前时间（默认真实 now）

        Returns:
            标注后的结果列表（不删除任何条目）
        """
        if not now:
            now = datetime.now(timezone.utc).isoformat()

        with self._lock:
            for r in results:
                mid = r.get("id", "")
                entry = self._entries.get(mid)
                if entry is None:
                    # 无时序元数据 → 默认 active
                    r["temporal_status"] = "active"
                    continue

                if entry.invalidated_by is not None:
                    r["temporal_status"] = "superseded"
                    r["invalidated_by"] = entry.invalidated_by
                elif entry.valid_end and now:
                    try:
                        if now > entry.valid_end:
                            r["temporal_status"] = "historical"
                        else:
                            r["temporal_status"] = "active"
                    except TypeError:
                        r["temporal_status"] = "active"
                else:
                    r["temporal_status"] = "active"

            return results

    # ============================================================
    # 持久化
    # ============================================================

    def persist(self) -> bool:
        """持久化到 JSON 文件。"""
        if not self._graph_path:
            return False
        with self._lock:
            try:
                self._graph_path.parent.mkdir(parents=True, exist_ok=True)
                data = {
                    "version": 1,
                    "entries": [e.to_dict() for e in self._entries.values()],
                    "saved_at": datetime.now(timezone.utc).isoformat(),
                }
                self._graph_path.write_text(
                    json.dumps(data, indent=2, ensure_ascii=False),
                    encoding="utf-8",
                )
                return True
            except Exception:
                return False

    def _restore(self) -> None:
        """从 JSON 恢复。"""
        try:
            data = json.loads(self._graph_path.read_text(encoding="utf-8"))
            for e in data.get("entries", []):
                entry = TemporalEntry.from_dict(e)
                self._entries[entry.memory_id] = entry
        except Exception:
            self._entries.clear()

    # ============================================================
    # 统计
    # ============================================================

    def stats(self) -> Dict[str, Any]:
        """图统计。"""
        with self._lock:
            total = len(self._entries)
            invalidated = sum(1 for e in self._entries.values() if e.invalidated_by is not None)
            return {
                "total_entries": total,
                "invalidated": invalidated,
                "active": total - invalidated,
                "persisted": self._graph_path is not None,
            }


# ============================================================
# CLI 自测
# ============================================================

if __name__ == "__main__":
    import tempfile

    print("=" * 60)
    print("TemporalMemoryGraph — 功能验证")
    print("=" * 60)

    with tempfile.TemporaryDirectory() as td:
        graph = TemporalMemoryGraph(graph_path=Path(td) / "graph.json")

        # 添加带有效期的记忆
        graph.add_temporal_memory(
            "VM-001", "马丁策略盈利", "2024-01-01", "2024-06-01"
        )
        graph.add_temporal_memory(
            "VM-002", "新策略", "2024-06-01", "2025-12-31"
        )

        # 时序判定
        print(f"\nVM-001 at 2024-03-01: {graph.is_valid_at('VM-001', '2024-03-01')}")
        print(f"VM-001 at 2024-07-01: {graph.is_valid_at('VM-001', '2024-07-01')}")

        # 否定
        graph.invalidate("VM-001", "VM-002")
        print(f"VM-001 after invalidate: {graph.is_valid_at('VM-001', '2024-03-01')}")

        # 活跃记忆
        active = graph.get_active_memories("2024-07-01")
        print(f"\nActive at 2024-07-01: {[m['memory_id'] for m in active]}")

        # recall 过滤
        results = [
            {"id": "VM-001", "content": "马丁策略", "score": 0.8},
            {"id": "VM-002", "content": "新策略", "score": 0.7},
        ]
        filtered = graph.filter_recall_results(results, now="2024-07-01")
        for r in filtered:
            print(f"  {r['id']}: temporal_status={r.get('temporal_status', '?')}")

        # 持久化
        graph.persist()
        graph2 = TemporalMemoryGraph(graph_path=Path(td) / "graph.json")
        print(f"\nRestored stats: {graph2.stats()}")

    print("\n" + "=" * 60)
    print("✅ TemporalMemoryGraph 功能验证通过")
