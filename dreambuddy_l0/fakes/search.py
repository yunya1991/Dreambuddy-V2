"""Search port 内存 fake：search/index。"""
from typing import Any, Dict, List, Optional


class FakeSearch:
    def __init__(self):
        self._items: List[Dict[str, Any]] = []

    def search(self, query: str, *, sources: Optional[List[str]] = None, top_k: int = 5, cursor: Optional[str] = None) -> Dict[str, Any]:
        hits = [i for i in self._items if query.lower() in str(i.get("text", "")).lower()]
        return {"hits": hits[:top_k], "cursor": None, "degraded_sources": []}

    def index(self, items: List[Dict[str, Any]], *, source: str = "") -> int:
        self._items.extend(items)
        return len(items)
