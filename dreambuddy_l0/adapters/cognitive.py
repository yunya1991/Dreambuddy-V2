"""L0-P adapter：MemoryPort → 认知闭环入口（同进程委托，不直连认知库）。

用途：C8 `job_runs` 终态回调、以及任何经 `Memory` port 的调度侧写入；
换存储只换 adapter，调度层零改动。M4⑪ 增 bulk-read（export/list）委托。

硬约束：
  - 认知目录按 G0-2 外置（`DREAMBUDDY_MEMORY_DIR`），`import` 在函数内完成，
    禁止模块级 `sys.path.insert`（SPEC-L0 §3.1 禁止④）；
  - `external_id` 原样透传，承接 G0-8 的唯一索引幂等；
  - 方言细节（SQL/表名/字段名）只出现在认知引擎（adapter 合法区），本文件零直连。
"""

from __future__ import annotations

import importlib
import os
import sys
from typing import Any, Dict, List, Optional

_DEFAULT_MEMORY_DIR = os.path.join("4-MEMORY", "9-工具与接口")


def _load_engine_module(module_name: str, memory_dir: Optional[str] = None) -> Any:
    """按 G0-2 外置路径加载认知引擎模块（函数级 sys.path 注入）。"""
    root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
    path = (
        memory_dir
        or os.environ.get("DREAMBUDDY_MEMORY_DIR")
        or os.path.join(root, _DEFAULT_MEMORY_DIR)
    )
    if path not in sys.path:
        sys.path.insert(0, path)
    return importlib.import_module(module_name)


class CognitiveMemoryAdapter:
    """把 `MemoryPort` 的读写方法委托给 `CognitiveLoopEntry`。"""

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

    def export_entries(
        self,
        *,
        min_quality: str = "C",
        limit: int = 100,
        cursor: Optional[str] = None,
        since: Optional[str] = None,
        order: str = "desc",
    ) -> Dict[str, Any]:
        return self._entry.export_entries(
            min_quality=min_quality, limit=limit, cursor=cursor, since=since, order=order
        )

    def list_ids(
        self,
        *,
        min_quality: str = "C",
        limit: int = 100,
        cursor: Optional[str] = None,
    ) -> Dict[str, Any]:
        return self._entry.list_ids(min_quality=min_quality, limit=limit, cursor=cursor)


class MemoryReadAdapter:
    """轻量只读 adapter：仅 bulk-read（export/list），供跨界消费方使用。

    与 `CognitiveMemoryAdapter` 的区别：直接委托 `VectorMemoryInterface`，
    不拉起蒸馏/固化/版本控制等整套认知引擎（消费方只需批量读）。
    """

    def __init__(self, vm: Any) -> None:
        self._vm = vm

    def export_entries(
        self,
        *,
        min_quality: str = "C",
        limit: int = 100,
        cursor: Optional[str] = None,
        since: Optional[str] = None,
        order: str = "desc",
    ) -> Dict[str, Any]:
        return self._vm.export_entries(
            min_quality=min_quality, limit=limit, cursor=cursor, since=since, order=order
        )

    def list_ids(
        self,
        *,
        min_quality: str = "C",
        limit: int = 100,
        cursor: Optional[str] = None,
    ) -> Dict[str, Any]:
        return self._vm.list_ids(min_quality=min_quality, limit=limit, cursor=cursor)

    def close(self) -> None:
        self._vm.close()


def load_vector_memory(
    *, storage_path: Optional[str] = None, memory_dir: Optional[str] = None
) -> Any:
    """构造 `VectorMemoryInterface`（认知引擎按需 import，路径外置）。"""
    module = _load_engine_module("vector_memory_interface", memory_dir)
    return module.VectorMemoryInterface(storage_path=storage_path)


def from_vector_memory(
    *, storage_path: Optional[str] = None, memory_dir: Optional[str] = None
) -> MemoryReadAdapter:
    """构造只读 bulk-read adapter（跨界消费方收编入口）。"""
    return MemoryReadAdapter(load_vector_memory(storage_path=storage_path, memory_dir=memory_dir))


def from_cognitive_loop(
    *, storage_path: Optional[str] = None, memory_dir: Optional[str] = None
) -> CognitiveMemoryAdapter:
    """构造适配器；认知入口模块按需 import（路径外置，G0-2）。"""
    module = _load_engine_module("cognitive_loop_entry", memory_dir)
    entry = module.CognitiveLoopEntry(storage_path=storage_path)
    return CognitiveMemoryAdapter(entry)
