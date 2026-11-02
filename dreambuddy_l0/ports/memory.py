"""Memory port：recall / record / verify + bulk-read（export/list）。

bulk-read 语义（M4⑪）：跨系统批量读认知记忆不走逐条 recall（避免 N 次检索开销），
统一信封 `{"entries": [...], "cursor": str|None}` / `{"ids": [...], "cursor": str|None}`；
质量过滤按 S>A>B>C>D 等级序（禁止直接比较字母）、分页用 cursor，禁止返回全量。
"""

from typing import Any, Dict, List, Optional, Protocol, runtime_checkable


@runtime_checkable
class MemoryPort(Protocol):
    def recall(
        self, context: str, *, top_k: int = 5, min_quality: str = "C"
    ) -> List[Dict[str, Any]]: ...
    def record(
        self,
        content: str,
        *,
        tags: Optional[List[str]] = None,
        source: str = "",
        external_id: Optional[str] = None,
    ) -> str: ...
    def verify(self, memory_id: str, *, success: bool) -> bool: ...
    def export_entries(
        self,
        *,
        min_quality: str = "C",
        limit: int = 100,
        cursor: Optional[str] = None,
        since: Optional[str] = None,
        order: str = "desc",
    ) -> Dict[str, Any]: ...
    def list_ids(
        self, *, min_quality: str = "C", limit: int = 100, cursor: Optional[str] = None
    ) -> Dict[str, Any]: ...
