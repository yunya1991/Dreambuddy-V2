#!/usr/bin/env python3
"""
图执行检查点管理器 (Graph Checkpointer) - Python 侧

位置: experiments/ab-trading/core/graph_checkpointer.py

功能:
1. 每个节点执行后自动保存 checkpoint
2. 支持回滚到任意节点重新执行
3. 支持列出所有历史检查点
4. 与 TS 侧 GraphCheckpointer 格式兼容

对齐 TS 侧 6-图结构上下文压缩/graph-checkpointer.ts
"""

import json
import time
import os
import threading
from pathlib import Path
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field, asdict


DEFAULT_STORAGE_DIR = Path(__file__).parent.parent / "data" / "graph-checkpoints"


@dataclass
class CheckpointRecord:
    """检查点记录"""
    snapshot_id: str
    node_id: str
    timestamp: float
    node_name: str
    token_used: int
    confidence: float
    state: Dict[str, Any]

    def to_dict(self) -> Dict:
        return {
            "snapshotId": self.snapshot_id,
            "nodeId": self.node_id,
            "timestamp": self.timestamp,
            "nodeName": self.node_name,
            "tokenUsed": self.token_used,
            "confidence": self.confidence,
            "state": self.state,
        }

    @classmethod
    def from_dict(cls, data: Dict) -> "CheckpointRecord":
        return cls(
            snapshot_id=data.get("snapshotId", ""),
            node_id=data.get("nodeId", ""),
            timestamp=data.get("timestamp", 0),
            node_name=data.get("nodeName", ""),
            token_used=data.get("tokenUsed", 0),
            confidence=data.get("confidence", 0.0),
            state=data.get("state", {}),
        )


@dataclass
class CheckpointStore:
    """检查点存储"""
    id: str
    execution_id: str
    checkpoints: List[CheckpointRecord] = field(default_factory=list)
    created_at: float = field(default_factory=time.time)
    last_updated: float = field(default_factory=time.time)

    def to_dict(self) -> Dict:
        return {
            "id": self.id,
            "executionId": self.execution_id,
            "checkpoints": [cp.to_dict() for cp in self.checkpoints],
            "createdAt": self.created_at,
            "lastUpdated": self.last_updated,
        }

    @classmethod
    def from_dict(cls, data: Dict) -> "CheckpointStore":
        return cls(
            id=data.get("id", ""),
            execution_id=data.get("executionId", ""),
            checkpoints=[
                CheckpointRecord.from_dict(cp)
                for cp in data.get("checkpoints", [])
            ],
            created_at=data.get("createdAt", time.time()),
            last_updated=data.get("lastUpdated", time.time()),
        )


class GraphCheckpointer:
    """
    图执行检查点管理器
    
    为 A 层执行提供断点持久化能力，支持回滚到任意节点重新执行
    与 TS 侧 GraphCheckpointer 格式兼容
    """

    def __init__(
        self,
        execution_id: str,
        node_order: Optional[List[str]] = None,
        node_names: Optional[Dict[str, str]] = None,
        storage_dir: Optional[Path] = None,
        auto_save: bool = True,
        max_checkpoints: int = 50,
    ):
        self.execution_id = execution_id
        self.node_order = node_order or []
        self.node_names = node_names or {}
        self.storage_dir = storage_dir or DEFAULT_STORAGE_DIR
        self.auto_save = auto_save
        self.max_checkpoints = max_checkpoints

        self._lock = threading.RLock()
        self._store: CheckpointStore
        self._file_path: Path

        self._ensure_storage_dir()
        self._file_path = self.storage_dir / f"{execution_id}.json"
        self._store = self._load_or_create_store()

    def _ensure_storage_dir(self) -> None:
        """确保存储目录存在"""
        self.storage_dir.mkdir(parents=True, exist_ok=True)

    def _load_or_create_store(self) -> CheckpointStore:
        """加载已有存储或创建新存储"""
        if self._file_path.exists():
            try:
                with open(self._file_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                return CheckpointStore.from_dict(data)
            except Exception as e:
                print(f"[GraphCheckpointer] 加载检查点失败，创建新存储: {e}")

        return CheckpointStore(
            id=f"store_{int(time.time())}_{os.urandom(4).hex()}",
            execution_id=self.execution_id,
        )

    def save_checkpoint(
        self,
        node_id: str,
        state: Dict[str, Any],
        confidence: float = 0.0,
        token_used: int = 0,
        snapshot_id: Optional[str] = None,
    ) -> CheckpointRecord:
        """
        保存检查点
        
        Args:
            node_id: 节点ID
            state: 状态数据
            confidence: 置信度
            token_used: Token消耗
            snapshot_id: 快照ID（可选，自动生成）
            
        Returns:
            检查点记录
        """
        with self._lock:
            if snapshot_id is None:
                snapshot_id = f"snap_{int(time.time())}_{os.urandom(3).hex()}"

            node_name = self.node_names.get(node_id, node_id)

            record = CheckpointRecord(
                snapshot_id=snapshot_id,
                node_id=node_id,
                timestamp=time.time(),
                node_name=node_name,
                token_used=token_used,
                confidence=confidence,
                state=state,
            )

            self._store.checkpoints.append(record)
            self._store.last_updated = time.time()

            if len(self._store.checkpoints) > self.max_checkpoints:
                self._store.checkpoints = self._store.checkpoints[-self.max_checkpoints:]

            if self.auto_save:
                self._persist()

            return record

    def _persist(self) -> None:
        """持久化到磁盘"""
        try:
            with open(self._file_path, 'w', encoding='utf-8') as f:
                json.dump(self._store.to_dict(), f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"[GraphCheckpointer] 持久化失败: {e}")

    def revert_to_node(self, node_id: str) -> Optional[Dict[str, Any]]:
        """
        回滚到指定节点
        
        语义：回到该节点执行完成后的状态
        - 如果该节点有保存的快照，返回该节点最新的快照
        - 否则返回该节点之前最新的快照
        
        Args:
            node_id: 节点ID
            
        Returns:
            状态数据，没有则返回None
        """
        with self._lock:
            self_checkpoint = self.get_latest_checkpoint_for_node(node_id)
            if self_checkpoint:
                return self_checkpoint.state

            checkpoint = self._find_latest_checkpoint_before_node(node_id)
            if not checkpoint:
                return None
            return checkpoint.state

    def _find_latest_checkpoint_before_node(self, node_id: str) -> Optional[CheckpointRecord]:
        """找到指定节点之前的最新检查点"""
        if not self.node_order:
            return None

        try:
            target_index = self.node_order.index(node_id)
        except ValueError:
            return None

        if target_index <= 0:
            return None

        valid_node_ids = set(self.node_order[:target_index])
        checkpoints_before = [
            cp for cp in self._store.checkpoints
            if cp.node_id in valid_node_ids
        ]

        if not checkpoints_before:
            return None

        return checkpoints_before[-1]

    def get_latest_checkpoint(self) -> Optional[CheckpointRecord]:
        """获取最新检查点"""
        with self._lock:
            if not self._store.checkpoints:
                return None
            return self._store.checkpoints[-1]

    def get_latest_checkpoint_for_node(self, node_id: str) -> Optional[CheckpointRecord]:
        """获取指定节点的最新检查点"""
        with self._lock:
            checkpoints = [cp for cp in self._store.checkpoints if cp.node_id == node_id]
            if not checkpoints:
                return None
            return checkpoints[-1]

    def list_checkpoints(self) -> List[CheckpointRecord]:
        """获取所有检查点"""
        with self._lock:
            return list(self._store.checkpoints)

    def get_checkpoints_after_node(self, node_id: str) -> List[CheckpointRecord]:
        """获取指定节点之后的检查点（用于重跑）"""
        with self._lock:
            if not self.node_order:
                return []

            try:
                target_index = self.node_order.index(node_id)
            except ValueError:
                return []

            nodes_after = set(self.node_order[target_index + 1:])
            return [cp for cp in self._store.checkpoints if cp.node_id in nodes_after]

    def clear_checkpoints_after_node(self, node_id: str) -> None:
        """清除指定节点之后的所有检查点"""
        with self._lock:
            if not self.node_order:
                return

            try:
                target_index = self.node_order.index(node_id)
            except ValueError:
                return

            nodes_to_remove = set(self.node_order[target_index + 1:])
            self._store.checkpoints = [
                cp for cp in self._store.checkpoints
                if cp.node_id not in nodes_to_remove
            ]
            self._store.last_updated = time.time()

            if self.auto_save:
                self._persist()

    def get_checkpoint_count(self) -> int:
        """获取检查点总数"""
        with self._lock:
            return len(self._store.checkpoints)

    def get_execution_summary(self) -> Dict:
        """获取执行摘要"""
        with self._lock:
            latest = self.get_latest_checkpoint()
            return {
                "execution_id": self.execution_id,
                "total_checkpoints": len(self._store.checkpoints),
                "first_checkpoint": (
                    self._store.checkpoints[0].timestamp
                    if self._store.checkpoints else 0
                ),
                "last_checkpoint": (
                    self._store.checkpoints[-1].timestamp
                    if self._store.checkpoints else 0
                ),
                "latest_confidence": latest.confidence if latest else 0.0,
                "latest_token_used": latest.token_used if latest else 0,
            }

    def delete(self) -> None:
        """删除检查点存储文件"""
        with self._lock:
            if self._file_path.exists():
                try:
                    self._file_path.unlink()
                except Exception as e:
                    print(f"[GraphCheckpointer] 删除失败: {e}")

    def get_file_path(self) -> Path:
        """获取当前存储的文件路径"""
        return self._file_path

    def get_execution_order(self) -> List[str]:
        """获取节点执行顺序"""
        return list(self.node_order)

    def set_node_order(self, node_order: List[str], node_names: Optional[Dict[str, str]] = None) -> None:
        """设置节点执行顺序"""
        with self._lock:
            self.node_order = list(node_order)
            if node_names:
                self.node_names.update(node_names)

    def persist(self) -> None:
        """手动持久化"""
        with self._lock:
            self._persist()


def create_checkpointer(
    execution_id: str,
    node_order: Optional[List[str]] = None,
    node_names: Optional[Dict[str, str]] = None,
    storage_dir: Optional[Path] = None,
    auto_save: bool = True,
    max_checkpoints: int = 50,
) -> GraphCheckpointer:
    """创建检查点管理器"""
    return GraphCheckpointer(
        execution_id=execution_id,
        node_order=node_order,
        node_names=node_names,
        storage_dir=storage_dir,
        auto_save=auto_save,
        max_checkpoints=max_checkpoints,
    )


def list_checkpoint_files(storage_dir: Optional[Path] = None) -> List[Path]:
    """列出所有检查点文件"""
    directory = storage_dir or DEFAULT_STORAGE_DIR
    if not directory.exists():
        return []
    return sorted(directory.glob("*.json"))


__all__ = [
    "CheckpointRecord",
    "CheckpointStore",
    "GraphCheckpointer",
    "create_checkpointer",
    "list_checkpoint_files",
    "DEFAULT_STORAGE_DIR",
]
