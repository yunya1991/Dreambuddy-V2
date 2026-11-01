"""L0-P adapter：JSONL 文件承载的 Store/Event 实现（跨平台、无 DB 驱动）。

用途：C9 job_runs 在 PG adapter（C4a）落地前的最小落库载体；
后续换 PG 只需替换 adapter，调度层零改动（只依赖 Store/Event port）。
"""

from __future__ import annotations

import json
import os
import time
from typing import Any, Dict, List, Optional


class _JsonlBase:
    def __init__(self, path: str) -> None:
        self.path = path
        parent = os.path.dirname(os.path.abspath(path))
        if parent:
            os.makedirs(parent, exist_ok=True)

    def _append(self, record: Dict[str, Any]) -> None:
        with open(self.path, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")

    def _read_all(self) -> List[Dict[str, Any]]:
        if not os.path.exists(self.path):
            return []
        out: List[Dict[str, Any]] = []
        with open(self.path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    out.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
        return out


class JsonlStore(_JsonlBase):
    """append-only JSONL，按 (table, id) 后写覆盖；idempotency_key 跨重启去重。"""

    def _state(self) -> Dict[str, Dict[str, Dict[str, Any]]]:
        tables: Dict[str, Dict[str, Dict[str, Any]]] = {}
        idem: Dict[str, str] = {}
        for rec in self._read_all():
            if rec.get("kind") != "store":
                continue
            table = rec.get("table", "")
            bucket = tables.setdefault(table, {})
            if rec.get("op") == "delete":
                for rid in rec.get("ids") or []:
                    bucket.pop(str(rid), None)
                continue
            data = rec.get("data") or {}
            rid = str(data.get("id", len(bucket)))
            bucket[rid] = data
            if rec.get("idempotency_key"):
                idem[str(rec["idempotency_key"])] = rid
        return {"tables": tables, "idem": idem}

    def read(
        self, table: str, *, key: str, cursor: Optional[str] = None, limit: int = 100
    ) -> Dict[str, Any]:
        row = (self._state()["tables"].get(table) or {}).get(str(key))
        return {"row": row} if row else {"row": None, "error_code": "not_found"}

    def write(self, table: str, *, data: Dict[str, Any], idempotency_key: str = "") -> bool:
        if idempotency_key:
            if idempotency_key in self._state()["idem"]:
                return True
        self._append(
            {
                "kind": "store",
                "op": "upsert",
                "table": table,
                "idempotency_key": idempotency_key,
                "data": data,
            }
        )
        return True

    def query(
        self,
        table: str,
        *,
        filters: Optional[Dict[str, Any]] = None,
        cursor: Optional[str] = None,
        limit: int = 100,
    ) -> Dict[str, Any]:
        rows = list((self._state()["tables"].get(table) or {}).values())
        for k, v in (filters or {}).items():
            rows = [r for r in rows if r.get(k) == v]
        return {"rows": rows[:limit], "cursor": None}

    def delete(self, table: str, *, ids: List[str]) -> int:
        existing = self._state()["tables"].get(table) or {}
        hit = [i for i in ids if str(i) in existing]
        if hit:
            self._append({"kind": "store", "op": "delete", "table": table, "ids": hit})
        return len(hit)

    def health(self) -> Dict[str, Any]:
        return {
            "ok": os.path.exists(self.path),
            "dialect": "jsonl",
            "tables": len(self._state()["tables"]),
            "path": self.path,
        }


class JsonlEvent(_JsonlBase):
    def publish(self, event_type: str, payload: Dict[str, Any], *, trace_id: str = "") -> bool:
        self._append(
            {
                "kind": "event",
                "event_type": event_type,
                "payload": payload,
                "trace_id": trace_id,
                "ts": time.time(),
            }
        )
        return True

    def consume(
        self, *, event_type: str = "", cursor: Optional[str] = None, limit: int = 100
    ) -> Dict[str, Any]:
        events = [
            {
                "type": r.get("event_type"),
                "payload": r.get("payload"),
                "trace_id": r.get("trace_id"),
                "ts": r.get("ts"),
            }
            for r in self._read_all()
            if r.get("kind") == "event" and (not event_type or r.get("event_type") == event_type)
        ]
        return {"events": events[:limit], "cursor": None}
