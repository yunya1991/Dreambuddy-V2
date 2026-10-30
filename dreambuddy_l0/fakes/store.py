"""Store port 内存 fake：read/write/query/health + 方言能力集声明。"""
from typing import Any, Dict, List, Optional

# 方言能力集（SPEC-C §3.1 adapter 规定）：操作符 + 类型与语义映射
DIALECT_CAPABILITIES = {
    "operators": {"upsert": True, "returning": False, "txn": False,
                  "skip_locked": False, "jsonb_filter": False},
    "type_mapping": {"datetime": "text", "json": "text", "numeric": "float"},
    "isolation": "serializable", "cursor_pagination": True,
}


class FakeStore:
    def __init__(self):
        self._tables: Dict[str, Dict[str, Dict[str, Any]]] = {}
        self._idem: Dict[str, str] = {}

    def read(self, table: str, *, key: str, cursor: Optional[str] = None, limit: int = 100) -> Dict[str, Any]:
        row = self._tables.get(table, {}).get(key)
        return {"row": row} if row else {"row": None, "error_code": "not_found"}

    def write(self, table: str, *, data: Dict[str, Any], idempotency_key: str = "") -> bool:
        if idempotency_key and idempotency_key in self._idem:
            return True
        key = str(data.get("id", len(self._tables.get(table, {}))))
        self._tables.setdefault(table, {})[key] = data
        if idempotency_key:
            self._idem[idempotency_key] = key
        return True

    def query(self, table: str, *, filters: Optional[Dict[str, Any]] = None, cursor: Optional[str] = None, limit: int = 100) -> Dict[str, Any]:
        rows = list(self._tables.get(table, {}).values())
        for k, v in (filters or {}).items():
            rows = [r for r in rows if r.get(k) == v]
        return {"rows": rows[:limit], "cursor": None}

    def health(self) -> Dict[str, Any]:
        return {"ok": True, "tables": len(self._tables), "dialect": "memory"}
