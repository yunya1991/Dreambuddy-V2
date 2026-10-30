"""Memory port：recall / record / verify（认知能力）。"""
from typing import Any, Dict, List, Optional, Protocol, runtime_checkable


@runtime_checkable
class MemoryPort(Protocol):
    def recall(self, context: str, *, top_k: int = 5,
               min_quality: str = "C") -> List[Dict[str, Any]]: ...
    def record(self, content: str, *, tags: Optional[List[str]] = None,
               source: str = "", external_id: Optional[str] = None) -> str: ...
    def verify(self, memory_id: str, *, success: bool) -> bool: ...
