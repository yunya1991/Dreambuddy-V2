# -*- coding: utf-8 -*-
"""P0-D3C: DSH 死信队列与租约。

职责:
  - 记录 DSH 终态 manual / 路由未命中 / 长尾 paused 的断路事务；
  - 提供租约领取与完成回写，供 Hermes 场外助手消费；
  - 不修改 Ticket、不写 receipt。

依据: SPEC-P0-D3C §5。
"""

from __future__ import annotations

import json
import os
import tempfile
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class DeadLetterEntry:
    entry_id: str
    ticket_id: str
    trace_id: str
    trigger: str
    payload: Dict[str, Any] = field(default_factory=dict)
    created_at: float = 0.0
    status: str = "pending"
    claimed_by: str = ""
    lease_until: float = 0.0
    result: Optional[Dict[str, Any]] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "entry_id": self.entry_id,
            "ticket_id": self.ticket_id,
            "trace_id": self.trace_id,
            "trigger": self.trigger,
            "payload": dict(self.payload or {}),
            "created_at": self.created_at,
            "status": self.status,
            "claimed_by": self.claimed_by,
            "lease_until": self.lease_until,
            "result": self.result,
        }

    @classmethod
    def from_dict(cls, data: Any) -> Optional["DeadLetterEntry"]:
        if not isinstance(data, dict):
            return None
        entry_id = str(data.get("entry_id") or "")
        ticket_id = str(data.get("ticket_id") or "")
        if not entry_id or not ticket_id:
            return None
        return cls(
            entry_id=entry_id,
            ticket_id=ticket_id,
            trace_id=str(data.get("trace_id") or ""),
            trigger=str(data.get("trigger") or ""),
            payload=data.get("payload") if isinstance(data.get("payload"), dict) else {},
            created_at=float(data.get("created_at") or 0.0),
            status=str(data.get("status") or "pending"),
            claimed_by=str(data.get("claimed_by") or ""),
            lease_until=float(data.get("lease_until") or 0.0),
            result=data.get("result") if isinstance(data.get("result"), dict) else None,
        )


class DeadLetterStore:
    """线程安全的 JSONL 死信存储；path=None 时仅内存。"""

    def __init__(self, path: Optional[str] = None) -> None:
        self._path = path
        self._lock = threading.RLock()
        self._entries: List[Dict[str, Any]] = self._load()

    def _load(self) -> List[Dict[str, Any]]:
        out: List[Dict[str, Any]] = []
        if not self._path:
            return out
        try:
            if not os.path.exists(self._path):
                return out
            with open(self._path, "r", encoding="utf-8") as handle:
                for line in handle:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        item = json.loads(line)
                    except (TypeError, ValueError):
                        continue
                    if isinstance(item, dict) and item.get("entry_id"):
                        out.append(item)
        except OSError:
            return []
        return out

    def _persist_locked(self) -> None:
        if not self._path:
            return
        try:
            os.makedirs(os.path.dirname(os.path.abspath(self._path)), exist_ok=True)
            fd, tmp_path = tempfile.mkstemp(
                prefix="deadletter-",
                suffix=".tmp",
                dir=os.path.dirname(os.path.abspath(self._path)),
            )
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as handle:
                    for item in self._entries:
                        handle.write(json.dumps(item, ensure_ascii=False) + "\n")
                os.replace(tmp_path, self._path)
            finally:
                if os.path.exists(tmp_path):
                    try:
                        os.unlink(tmp_path)
                    except OSError:
                        pass
        except OSError:
            pass  # FAIL-OPEN：持久化失败不影响内存状态

    def append(self, entry: Any) -> bool:
        try:
            if not isinstance(entry, DeadLetterEntry):
                return False
            if not entry.entry_id or not entry.ticket_id:
                return False
            with self._lock:
                if any(item.get("entry_id") == entry.entry_id for item in self._entries):
                    return False
                self._entries.append(entry.to_dict())
                self._persist_locked()
            return True
        except Exception:  # FAIL-OPEN
            return False

    def claim(
        self,
        worker_id: str,
        now: Optional[float] = None,
        lease_ttl_s: float = 300.0,
    ) -> Optional[Dict[str, Any]]:
        try:
            if not worker_id:
                return None
            now_ts = float(now if now is not None else time.time())
            with self._lock:
                for item in self._entries:
                    status = item.get("status")
                    lease_until = float(item.get("lease_until") or 0.0)
                    claimable = status == "pending" or (
                        status == "claimed" and lease_until <= now_ts
                    )
                    if not claimable:
                        continue
                    item["status"] = "claimed"
                    item["claimed_by"] = worker_id
                    item["lease_until"] = now_ts + float(lease_ttl_s)
                    self._persist_locked()
                    return dict(item)
            return None
        except Exception:  # FAIL-OPEN
            return None

    def complete(
        self,
        entry_id: str,
        result: Optional[Dict[str, Any]] = None,
        now: Optional[float] = None,
    ) -> bool:
        try:
            with self._lock:
                for item in self._entries:
                    if item.get("entry_id") != entry_id:
                        continue
                    item["status"] = "completed"
                    item["result"] = dict(result) if isinstance(result, dict) else None
                    item["lease_until"] = 0.0
                    item["completed_at"] = float(now if now is not None else time.time())
                    self._persist_locked()
                    return True
            return False
        except Exception:  # FAIL-OPEN
            return False

    def list_pending(self) -> List[Dict[str, Any]]:
        with self._lock:
            return [dict(item) for item in self._entries if item.get("status") == "pending"]

    def get(self, entry_id: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            for item in self._entries:
                if item.get("entry_id") == entry_id:
                    return dict(item)
        return None
