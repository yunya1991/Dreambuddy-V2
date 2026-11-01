"""L0-P adapter：MemoryPort → 认知闭环入口（同进程委托，不直连认知库）。

用途：C8 `job_runs` 终态回调、以及任何经 `Memory` port 的调度侧写入；
换存储只换 adapter，调度层零改动。

硬约束：
  - 认知目录按 G0-2 外置（`DREAMBUDDY_MEMORY_DIR`），`import` 在函数内完成，
    禁止模块级 `sys.path.insert`（SPEC-L0 §3.1 禁止④）；
  - `external_id` 原样透传，承接 G0-8 的唯一索引幂等。
"""

from __future__ import annotations

import importlib
import os
import sys
from typing import Any, Dict, List, Optional

_DEFAULT_MEMORY_DIR = os.path.join("4-MEMORY", "9-工具与接口")


class CognitiveMemoryAdapter:
    """把 `MemoryPort.record/recall/verify` 委托给 `CognitiveLoopEntry`。"""

    def __init__(self, entry: Any) -> None:
        self._entry = entry

    def recall(
        self, context: str, *, top_k: int = 5, min_quality: str = "C"
    ) -> List[Dict[str, Any]]:
        return list(self._entry.recall(context, top_k=top_k, min_quality=min_quality) or [])

    def record(
        self,
        content: str,
        *,
        tags: Optional[List[str]] = None,
        source: str = "",
        external_id: Optional[str] = None,
    ) -> str:
        return str(
            self._entry.record(
                content,
                quality_level="C",
                tags=list(tags or []),
                source=source or "l0.scheduler",
                external_id=external_id,
            )
        )

    def verify(self, memory_id: str, *, success: bool) -> bool:
        res = self._entry.verify(memory_id, success=success)
        if isinstance(res, dict):
            return bool(res.get("success", True))
        return bool(res)


def from_cognitive_loop(
    *, storage_path: Optional[str] = None, memory_dir: Optional[str] = None
) -> CognitiveMemoryAdapter:
    """构造适配器；认知入口模块按需 import（路径外置，G0-2）。"""
    root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
    path = (
        memory_dir
        or os.environ.get("DREAMBUDDY_MEMORY_DIR")
        or os.path.join(root, _DEFAULT_MEMORY_DIR)
    )
    if path not in sys.path:
        sys.path.insert(0, path)
    module = importlib.import_module("cognitive_loop_entry")
    entry = module.CognitiveLoopEntry(storage_path=storage_path)
    return CognitiveMemoryAdapter(entry)
