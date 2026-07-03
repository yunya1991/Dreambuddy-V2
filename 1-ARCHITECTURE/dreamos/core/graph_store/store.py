"""
DreamOS G层 — 图存储主入口 (GraphStore)

G 层统一入口，整合:
    - Checkpointer:     状态检查点
    - ContextCompressor: 上下文压缩
    - HistoryReplay:     历史回放

职责:
    1. 在 C 层执行过程中自动保存检查点
    2. 当 State 过大时自动压缩
    3. 执行完成后记录历史
    4. 提供历史查询和模式识别

用法:
    store = GraphStore()
    # C 层执行中调用
    store.checkpoint(state, node_id="A1")
    # 执行完成后
    store.record(state, report)
    # 查询历史
    patterns = store.find_patterns()
"""

from __future__ import annotations

from typing import Dict, List, Optional, Any

from dreamos.shared.state import State

from .types import Checkpoint, CompressedState, HistoryEntry, ReplayResult
from .checkpointer import Checkpointer
from .compressor import ContextCompressor
from .history import HistoryReplay


class GraphStore:
    """图存储 — G 层主入口

    用法:
        store = GraphStore()

        # 执行中保存检查点
        cp_id = store.checkpoint(state, node_id="A1")

        # 执行完成后记录历史
        store.record(state, report.to_dict())

        # 查询历史模式
        patterns = store.find_patterns()

        # 回滚
        state = store.rollback(cp_id)
    """

    def __init__(self,
                 max_checkpoints: int = 50,
                 max_history: int = 200,
                 auto_compress: bool = True,
                 compress_threshold: int = 10000,
                 storage_dir: Optional[str] = None):
        self._checkpointer = Checkpointer(
            max_checkpoints=max_checkpoints,
            storage_dir=storage_dir,
        )
        self._compressor = ContextCompressor()
        self._history = HistoryReplay(max_entries=max_history)
        self._auto_compress = auto_compress
        self._compress_threshold = compress_threshold

    # ── 检查点 ───────────────────────────────────────

    def checkpoint(self, state: State, node_id: str = "",
                   metadata: Optional[Dict[str, Any]] = None) -> str:
        """保存检查点

        如果 auto_compress=True 且 State 过大，会先压缩再保存。
        """
        if self._auto_compress and self._compressor.should_compress(state, self._compress_threshold):
            self._compressor.compress(state)

        return self._checkpointer.save(state, node_id, metadata)

    def rollback(self, checkpoint_id: str) -> Optional[State]:
        """回滚到检查点"""
        return self._checkpointer.load(checkpoint_id)

    def list_checkpoints(self, cycle_id: Optional[str] = None) -> List[Dict[str, Any]]:
        """列出检查点"""
        return self._checkpointer.list_checkpoints(cycle_id)

    def delete_checkpoint(self, checkpoint_id: str) -> bool:
        """删除检查点"""
        return self._checkpointer.delete(checkpoint_id)

    # ── 压缩 ─────────────────────────────────────────

    def compress(self, state: State,
                 keep_recent_trace: Optional[int] = None) -> CompressedState:
        """手动压缩 State"""
        return self._compressor.compress(state, keep_recent_trace)

    def should_compress(self, state: State) -> bool:
        """判断是否需要压缩"""
        return self._compressor.should_compress(state, self._compress_threshold)

    # ── 历史 ─────────────────────────────────────────

    def record(self, state: State, report: Optional[Dict[str, Any]] = None) -> HistoryEntry:
        """记录一次执行到历史"""
        return self._history.record(state, report)

    def query_history(self, **kwargs) -> List[HistoryEntry]:
        """查询历史记录"""
        return self._history.query(**kwargs)

    def find_patterns(self) -> Dict[str, Any]:
        """识别历史模式"""
        return self._history.find_patterns()

    def get_similar(self, state: State, limit: int = 5) -> List[HistoryEntry]:
        """获取相似历史记录"""
        return self._history.get_similar(state, limit)

    def replay(self, cycle_id: str) -> Optional[HistoryEntry]:
        """回放指定 cycle"""
        return self._history.replay(cycle_id)

    # ── 统计 ─────────────────────────────────────────

    def summary(self) -> Dict[str, Any]:
        """存储摘要"""
        return {
            "checkpoints": self._checkpointer.count,
            "history_entries": self._history.total,
            "auto_compress": self._auto_compress,
            "compress_threshold": self._compress_threshold,
        }

    @property
    def checkpointer(self) -> Checkpointer:
        """直接访问检查点管理器"""
        return self._checkpointer

    @property
    def compressor(self) -> ContextCompressor:
        """直接访问压缩器"""
        return self._compressor

    @property
    def history(self) -> HistoryReplay:
        """直接访问历史管理器"""
        return self._history
