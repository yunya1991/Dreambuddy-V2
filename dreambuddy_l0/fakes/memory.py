"""Memory port 内存 fake：recall/record/verify + bulk-read（export/list）。

bulk-read 语义与真实 adapter 对齐：统一信封、S>A>B>C>D 质量序、cursor 分页、since 增量。
"""

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

# 质量等级序（数字越大越好；禁止按字母直接比较，A 会误排在 C 之后）
QUALITY_RANK = {"S": 4, "A": 3, "B": 2, "C": 1, "D": 0}


class FakeMemory:
    def __init__(self):
        self._mem: Dict[str, Dict[str, Any]] = {}
        self._ext: Dict[str, str] = {}

    def recall(
        self, context: str, *, top_k: int = 5, min_quality: str = "C"
    ) -> List[Dict[str, Any]]:
        items = [m for m in self._mem.values() if m["quality"] >= min_quality]
        return items[:top_k]

    def record(
        self,
        content: str,
        *,
        tags: Optional[List[str]] = None,
        source: str = "",
        external_id: Optional[str] = None,
        quality: str = "C",
        created_at: str = "",
    ) -> str:
        if external_id and external_id in self._ext:
            return self._ext[external_id]
        mid = f"FM-{len(self._mem)}"
        now = created_at or datetime.now(timezone.utc).isoformat()
        self._mem[mid] = {
            "id": mid,
            "content": content,
            "tags": list(tags or []),
            "source": source,
            "quality": quality,
            "confidence": 0.0,
            "memory_type": "experience",
            "created_at": now,
            "updated_at": now,
            "verify_count": 0,
            "level": "observation",
            "known_gaps": [],
            "observations": [],
        }
        if external_id:
            self._ext[external_id] = mid
        return mid

    def verify(self, memory_id: str, *, success: bool) -> bool:
        return memory_id in self._mem

    def export_entries(
        self,
        *,
        min_quality: str = "C",
        limit: int = 100,
        cursor: Optional[str] = None,
        since: Optional[str] = None,
        order: str = "desc",
    ) -> Dict[str, Any]:
        rows = self._select(min_quality, since, order)
        page, next_cursor = _paginate(rows, limit, cursor)
        entries = [
            {
                "id": m["id"],
                "content": m["content"],
                "quality_level": m["quality"],
                "confidence": m["confidence"],
                "tags": list(m["tags"]),
                "memory_type": m["memory_type"],
                "source": m["source"],
                "created_at": m["created_at"],
                "updated_at": m["updated_at"],
                "verify_count": m["verify_count"],
                "level": m["level"],
                "known_gaps": list(m["known_gaps"]),
                "observations": list(m["observations"]),
            }
            for m in page
        ]
        return {"entries": entries, "cursor": next_cursor}

    def list_ids(
        self, *, min_quality: str = "C", limit: int = 100, cursor: Optional[str] = None
    ) -> Dict[str, Any]:
        rows = self._select(min_quality, None, "desc")
        page, next_cursor = _paginate(rows, limit, cursor)
        return {"ids": [m["id"] for m in page], "cursor": next_cursor}

    def _select(self, min_quality: str, since: Optional[str], order: str) -> List[Dict[str, Any]]:
        threshold = QUALITY_RANK.get(str(min_quality).upper(), QUALITY_RANK["C"])
        rows = [m for m in self._mem.values() if QUALITY_RANK.get(m["quality"], -1) >= threshold]
        if since:
            rows = [m for m in rows if m["created_at"] > since]
        reverse = str(order).lower() != "asc"
        return sorted(rows, key=lambda m: (m["created_at"], m["id"]), reverse=reverse)


def _paginate(rows: List[Dict[str, Any]], limit: int, cursor: Optional[str]):
    """cursor = 已消费条数的偏移量（字符串）；返回 (本页, 下一页 cursor)。"""
    limit = max(1, int(limit))
    offset = int(cursor or 0)
    page = rows[offset : offset + limit]
    next_cursor = str(offset + limit) if offset + limit < len(rows) else None
    return page, next_cursor
