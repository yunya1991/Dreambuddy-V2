"""
DreamOS G层 — 检查点管理器

职责:
    1. 在关键执行节点保存 State 快照
    2. 支持回滚到任意检查点
    3. 支持从检查点恢复执行
    4. 管理检查点的生命周期（创建/查询/清理）

存储策略:
    - 内存存储（默认，适用于单次执行）
    - 可选文件存储（持久化）
    - 最大检查点数量限制（FIFO 淘汰）
"""

from __future__ import annotations

from typing import Dict, List, Optional, Any
from collections import OrderedDict
import json
import os

from dreamos.shared.state import State
from dreamos.shared.utils import gen_cycle_id, safe_json

from .types import Checkpoint


class Checkpointer:
    """检查点管理器

    用法:
        cp = Checkpointer()
        # 保存检查点
        cp_id = cp.save(state, node_id="A1")
        # 回滚
        state = cp.load(cp_id)
        # 列出检查点
        cps = cp.list_checkpoints()
    """

    # 默认最大检查点数
    DEFAULT_MAX_CHECKPOINTS = 50

    def __init__(self,
                 max_checkpoints: int = DEFAULT_MAX_CHECKPOINTS,
                 storage_dir: Optional[str] = None):
        self._max = max_checkpoints
        self._storage_dir = storage_dir
        self._checkpoints: OrderedDict[str, Checkpoint] = OrderedDict()

        if storage_dir and not os.path.exists(storage_dir):
            os.makedirs(storage_dir, exist_ok=True)

    def save(self, state: State, node_id: str = "",
             metadata: Optional[Dict[str, Any]] = None) -> str:
        """保存检查点

        Args:
            state: 要保存的状态
            node_id: 触发检查点的节点 ID
            metadata: 额外元信息

        Returns:
            checkpoint_id: 检查点 ID
        """
        cp_id = gen_cycle_id("ckpt")
        snapshot = state.to_dict()

        cp = Checkpoint(
            checkpoint_id=cp_id,
            cycle_id=state.cycle_id,
            node_id=node_id,
            state_snapshot=snapshot,
            metadata=metadata or {},
        )

        # 内存存储
        self._checkpoints[cp_id] = cp
        if len(self._checkpoints) > self._max:
            self._checkpoints.popitem(last=False)  # FIFO 淘汰

        # 文件存储（可选）
        if self._storage_dir:
            self._save_to_file(cp)

        return cp_id

    def load(self, checkpoint_id: str) -> Optional[State]:
        """从检查点恢复状态

        Args:
            checkpoint_id: 检查点 ID

        Returns:
            State: 恢复的状态，或 None
        """
        cp = self._get_checkpoint(checkpoint_id)
        if cp is None:
            return None

        return State.from_dict(cp.state_snapshot)

    def rollback(self, checkpoint_id: str) -> Optional[State]:
        """回滚到指定检查点（load 的别名，语义更清晰）"""
        return self.load(checkpoint_id)

    def list_checkpoints(self, cycle_id: Optional[str] = None) -> List[Dict[str, Any]]:
        """列出检查点

        Args:
            cycle_id: 可选，按 cycle_id 过滤

        Returns:
            检查点列表
        """
        result = []
        for cp in self._checkpoints.values():
            if cycle_id and cp.cycle_id != cycle_id:
                continue
            result.append({
                "checkpoint_id": cp.checkpoint_id,
                "cycle_id": cp.cycle_id,
                "node_id": cp.node_id,
                "created_at": cp.created_at,
            })
        return result

    def get_checkpoint(self, checkpoint_id: str) -> Optional[Checkpoint]:
        """获取检查点详情"""
        return self._get_checkpoint(checkpoint_id)

    def delete(self, checkpoint_id: str) -> bool:
        """删除检查点"""
        if checkpoint_id in self._checkpoints:
            del self._checkpoints[checkpoint_id]
            if self._storage_dir:
                filepath = os.path.join(self._storage_dir, f"{checkpoint_id}.json")
                if os.path.exists(filepath):
                    os.remove(filepath)
            return True
        return False

    def clear(self, cycle_id: Optional[str] = None) -> int:
        """清理检查点

        Args:
            cycle_id: 指定则只清理该 cycle 的检查点

        Returns:
            清理数量
        """
        if cycle_id is None:
            count = len(self._checkpoints)
            self._checkpoints.clear()
            return count

        to_remove = [k for k, v in self._checkpoints.items() if v.cycle_id == cycle_id]
        for k in to_remove:
            del self._checkpoints[k]
        return len(to_remove)

    @property
    def count(self) -> int:
        """当前检查点数量"""
        return len(self._checkpoints)

    # ── 内部方法 ───────────────────────────────────────

    def _get_checkpoint(self, checkpoint_id: str) -> Optional[Checkpoint]:
        """获取检查点（先查内存，再查文件）"""
        if checkpoint_id in self._checkpoints:
            return self._checkpoints[checkpoint_id]

        if self._storage_dir:
            return self._load_from_file(checkpoint_id)

        return None

    def _save_to_file(self, cp: Checkpoint) -> None:
        """保存到文件"""
        filepath = os.path.join(self._storage_dir, f"{cp.checkpoint_id}.json")
        with open(filepath, "w") as f:
            f.write(safe_json(cp.to_dict()))

    def _load_from_file(self, checkpoint_id: str) -> Optional[Checkpoint]:
        """从文件加载"""
        filepath = os.path.join(self._storage_dir, f"{checkpoint_id}.json")
        if not os.path.exists(filepath):
            return None
        try:
            with open(filepath, "r") as f:
                data = json.load(f)
            return Checkpoint(
                checkpoint_id=data["checkpoint_id"],
                cycle_id=data["cycle_id"],
                node_id=data["node_id"],
                state_snapshot=data["state_snapshot"],
                metadata=data.get("metadata", {}),
                created_at=data.get("created_at", ""),
            )
        except Exception:
            return None
