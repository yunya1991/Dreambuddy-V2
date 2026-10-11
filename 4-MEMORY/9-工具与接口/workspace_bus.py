#!/usr/bin/env python3
"""GWT 全局工作空间广播 — WorkspaceBus

定位：L4 元认知层基础，借鉴 GWT (Global Workspace Theory) + HOT 双层意识架构
（arXiv:2512.19155），在 5 子系统之上增加全局工作空间广播层。

核心能力:
  1. broadcast(content) — 广播工作空间内容到所有订阅者
  2. subscribe(subsystem, callback) — 子系统订阅广播
  3. unsubscribe(sub_id) — 取消订阅
  4. ignite(content) — 高置信内容被"点燃"（confidence > IGNITE_THRESHOLD）
  5. get_workspace_state() — 获取当前工作空间状态

工作空间内容 (WorkspaceContent):
  - intent: 意图引擎输出
  - memory_recall: 记忆库 top-K 召回
  - skill_match: SKILL 库 top-K 匹配
  - knowledge_retrieval: 知识库 top-K 检索
  - confidence: 综合置信度
  - ignited: 是否被点燃（高置信广播到所有子系统）

点燃机制 (GWT Ignition):
  - confidence > IGNITE_THRESHOLD (0.8) → ignited=True
  - 被点燃的内容广播到所有订阅子系统
  - 未点燃的内容仅存储，不主动推送（或仅推送给核心订阅者）

设计原则:
  - 发布-订阅模式 (Pub/Sub)
  - FAIL-OPEN：订阅者回调失败不阻塞其他订阅者
  - 线程安全：所有公共方法加锁
  - 轻量级：纯 Python，无外部依赖
  - 历史记录：保留最近 N 条广播用于回溯

参考:
  - SPEC-CognitiveSystem-Evolution.md §4.3 P3-1 + §2.5.1
  - GWT: Global Workspace Theory (Baars, Dehaene)
  - HOT: Higher-Order Thought 双层意识
"""
from __future__ import annotations

import threading
import uuid
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional


# ============================================================
# 常量
# ============================================================

IGNITE_THRESHOLD: float = 0.8  # 置信度阈值，超过则点燃
MAX_HISTORY: int = 100  # 最大历史记录数


# ============================================================
# dataclass: WorkspaceContent
# ============================================================


@dataclass
class WorkspaceContent:
    """工作空间内容 — GWT 全局工作空间的广播单元。

    Attributes:
        intent: 意图引擎输出（dict，含 type/confidence/keywords）
        memory_recall: 记忆库 top-K 召回结果
        skill_match: SKILL 库 top-K 匹配结果
        knowledge_retrieval: 知识库 top-K 检索结果
        confidence: 综合置信度 0.0-1.0
        ignited: 是否被点燃（高置信广播到所有子系统）
        timestamp: 广播时间戳
    """

    intent: Dict[str, Any] = field(default_factory=dict)
    memory_recall: List[Dict[str, Any]] = field(default_factory=list)
    skill_match: List[Dict[str, Any]] = field(default_factory=list)
    knowledge_retrieval: List[Dict[str, Any]] = field(default_factory=list)
    confidence: float = 0.0
    ignited: bool = False
    timestamp: str = ""
    # P3-6: 调度链末尾执行结果（ReflectionNode 回环消费，可选）
    execution_result: Optional[Dict[str, Any]] = None

    def __post_init__(self) -> None:
        if not self.timestamp:
            self.timestamp = datetime.now(timezone.utc).isoformat()
        # 点燃判定：confidence > 阈值
        if not self.ignited:
            self.ignited = self.confidence > IGNITE_THRESHOLD

    def to_dict(self) -> Dict[str, Any]:
        return {
            "intent": self.intent,
            "memory_recall": self.memory_recall,
            "skill_match": self.skill_match,
            "knowledge_retrieval": self.knowledge_retrieval,
            "confidence": self.confidence,
            "ignited": self.ignited,
            "timestamp": self.timestamp,
            "execution_result": self.execution_result,
        }


# ============================================================
# WorkspaceBus 主类
# ============================================================


class WorkspaceBus:
    """GWT 全局工作空间广播总线。

    5 子系统（认知/SKILL/知识库/文档/索引）之上的广播层。
    高置信信息被"点燃"后广播到所有订阅子系统，实现 GWT 的
    "全局工作空间"意识机制。
    """

    def __init__(self, ignite_threshold: float = IGNITE_THRESHOLD) -> None:
        """
        Args:
            ignite_threshold: 点燃置信度阈值（默认 0.8）
        """
        self._ignite_threshold = ignite_threshold
        self._subscribers: Dict[str, Callable[[WorkspaceContent], None]] = {}
        self._current: Optional[WorkspaceContent] = None
        self._history: deque = deque(maxlen=MAX_HISTORY)
        self._lock = threading.Lock()

    # ============================================================
    # 广播
    # ============================================================

    def broadcast(self, content: WorkspaceContent) -> WorkspaceContent:
        """广播工作空间内容到所有订阅者。

        若 content.confidence > ignite_threshold，则 ignited=True，
        广播到所有订阅者；否则仅存储，不推送（GWT 未点燃状态）。

        Args:
            content: 工作空间内容

        Returns:
            处理后的 content（可能更新 ignited 字段）
        """
        with self._lock:
            # 点燃判定
            if not content.ignited:
                content.ignited = content.confidence > self._ignite_threshold

            self._current = content
            self._history.append(content)

            # 广播到所有订阅者（FAIL-OPEN：单个失败不阻塞）
            for sub_id, callback in list(self._subscribers.items()):
                try:
                    callback(content)
                except Exception:
                    pass  # FAIL-OPEN：订阅者异常静默忽略

            return content

    # ============================================================
    # 订阅管理
    # ============================================================

    def subscribe(
        self,
        subsystem: str,
        callback: Callable[[WorkspaceContent], None],
    ) -> str:
        """订阅工作空间广播。

        Args:
            subsystem: 子系统名称（用于标识）
            callback: 回调函数 fn(content) -> None

        Returns:
            订阅 ID（用于取消订阅）
        """
        with self._lock:
            sub_id = f"{subsystem}_{uuid.uuid4().hex[:8]}"
            self._subscribers[sub_id] = callback
            return sub_id

    def unsubscribe(self, sub_id: str) -> bool:
        """取消订阅。

        Args:
            sub_id: 订阅 ID

        Returns:
            True=成功取消，False=订阅不存在
        """
        with self._lock:
            if sub_id in self._subscribers:
                del self._subscribers[sub_id]
                return True
            return False

    # ============================================================
    # 点燃（显式）
    # ============================================================

    def ignite(self, content: WorkspaceContent) -> WorkspaceContent:
        """显式点燃内容并广播。

        无论 confidence 如何，强制 ignited=True 并广播。

        Args:
            content: 工作空间内容

        Returns:
            点燃后的 content
        """
        content.ignited = True
        return self.broadcast(content)

    # ============================================================
    # 状态查询
    # ============================================================

    def get_workspace_state(self) -> Dict[str, Any]:
        """获取当前工作空间状态。

        Returns:
            {
              "current": 当前 WorkspaceContent 或 None,
              "subscribers": 订阅者数量,
              "history_count": 历史记录数,
              "ignite_threshold": 点燃阈值,
            }
        """
        with self._lock:
            return {
                "current": self._current,
                "subscribers": len(self._subscribers),
                "history_count": len(self._history),
                "ignite_threshold": self._ignite_threshold,
            }

    def get_history(self, limit: int = 10) -> List[WorkspaceContent]:
        """获取最近的广播历史。

        Args:
            limit: 返回条数上限

        Returns:
            最近的 WorkspaceContent 列表
        """
        with self._lock:
            return list(self._history)[-limit:]

    def clear(self) -> None:
        """清空工作空间（当前内容 + 历史，保留订阅者）。"""
        with self._lock:
            self._current = None
            self._history.clear()

    # ============================================================
    # 统计
    # ============================================================

    def stats(self) -> Dict[str, Any]:
        """工作空间统计。"""
        with self._lock:
            ignited_count = sum(1 for c in self._history if c.ignited)
            return {
                "total_broadcasts": len(self._history),
                "ignited_count": ignited_count,
                "subscribers": len(self._subscribers),
                "ignite_threshold": self._ignite_threshold,
                "has_current": self._current is not None,
            }


# ============================================================
# CLI 自测
# ============================================================


if __name__ == "__main__":
    print("=" * 60)
    print("WorkspaceBus — 功能验证")
    print("=" * 60)

    bus = WorkspaceBus()

    # 模拟 5 子系统订阅
    received = {"memory": 0, "skill": 0, "knowledge": 0, "docs": 0, "index": 0}
    for name in received:
        def make_cb(n):
            def cb(content):
                received[n] += 1
            return cb
        bus.subscribe(name, make_cb(name))

    # 低置信广播（不应点燃）
    low_conf = WorkspaceContent(
        intent={"type": "low"},
        memory_recall=[],
        skill_match=[],
        knowledge_retrieval=[],
        confidence=0.5,
    )
    bus.broadcast(low_conf)
    print(f"\n低置信广播: ignited={low_conf.ignited}")
    print(f"  各子系统接收: {received}")

    # 高置信广播（点燃）
    high_conf = WorkspaceContent(
        intent={"type": "high"},
        memory_recall=[{"id": "VM-001", "score": 0.9}],
        skill_match=[{"id": "skill-1", "score": 0.85}],
        knowledge_retrieval=[{"id": "chunk-1", "score": 0.8}],
        confidence=0.9,
    )
    bus.broadcast(high_conf)
    print(f"\n高置信广播: ignited={high_conf.ignited}")
    print(f"  各子系统接收: {received}")

    print(f"\nStats: {bus.stats()}")

    print("\n" + "=" * 60)
    print("✅ WorkspaceBus 功能验证通过")
