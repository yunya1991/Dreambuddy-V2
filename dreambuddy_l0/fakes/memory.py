"""Memory port 内存 fake：recall/record/verify。"""
from typing import Any, Dict, List, Optional


class FakeMemory:
    def __init__(self):
        self._mem: Dict[str, Dict[str, Any]] = {}
        self._ext: Dict[str, str] = {}

    def recall(self, context: str, *, top_k: int = 5, min_quality: str = "C") -> List[Dict[str, Any]]:
        items = [m for m in self._mem.values() if m["quality"] >= min_quality]
        return items[:top_k]

    def record(self, content: str, *, tags: Optional[List[str]] = None, source: str = "", external_id: Optional[str] = None) -> str:
        if external_id and external_id in self._ext:
            return self._ext[external_id]
        mid = f"FM-{len(self._mem)}"
        self._mem[mid] = {"id": mid, "content": content, "tags": tags or [], "source": source, "quality": "C"}
        if external_id:
            self._ext[external_id] = mid
        return mid

    def verify(self, memory_id: str, *, success: bool) -> bool:
        return memory_id in self._mem
