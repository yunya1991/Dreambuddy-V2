"""
DreamOS G层 — GraphStore 图存储层

职责:
    - 执行状态检查点 (Checkpoint)
    - 上下文压缩 (Context Compression)
    - 历史回放 (History Replay)
    - 持久化

子模块:
    - types.py          类型定义 (Checkpoint / CompressedState / HistoryEntry)
    - checkpointer.py   检查点管理
    - compressor.py     上下文压缩
    - history.py        历史回放
    - store.py          存储主入口

快速上手:
    from dreamos.core.graph_store import GraphStore

    store = GraphStore()
    cp_id = store.checkpoint(state, node_id="A1")
    store.record(state, report)
    patterns = store.find_patterns()
"""

from dreamos.shared.state import State

from .types import Checkpoint, CompressedState, HistoryEntry, ReplayResult
from .checkpointer import Checkpointer
from .compressor import ContextCompressor
from .history import HistoryReplay
from .store import GraphStore

__all__ = [
    # types
    "Checkpoint", "CompressedState", "HistoryEntry", "ReplayResult",
    # components
    "Checkpointer", "ContextCompressor", "HistoryReplay", "GraphStore",
]
