"""Search port：search / index（检索能力，C7 unified_search 的分发通道）。"""
from typing import Any, Dict, List, Optional, Protocol, runtime_checkable


@runtime_checkable
class SearchPort(Protocol):
    def search(self, query: str, *, sources: Optional[List[str]] = None,
               top_k: int = 5, cursor: Optional[str] = None) -> Dict[str, Any]: ...
    def index(self, items: List[Dict[str, Any]], *, source: str = "") -> int: ...
