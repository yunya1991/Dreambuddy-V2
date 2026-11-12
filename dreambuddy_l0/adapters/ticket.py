# -*- coding: utf-8 -*-
"""L0-P adapter：D2 Ticket 存储(append/read_all) → 通用 StorePort。

定位（W0 契约冻结，PROPOSAL-P0-D3 §4.10）：
  D2 的 `JsonlTicketStore` 是 append-only latest-wins 的私有接口
  (`append` / `read_all`)，与通用 L0 的 `StorePort`(read/write/query/health)
  不一致。本适配器做纯映射，使「云端 PG 以同接口注入」有可对齐的契约，
  同时不改 `router_loop` 八步语义（验收 A6）。

硬约束：
  - 只代理不复制：读写都落到被包装的 legacy store（ADR-2 单源）
  - latest-wins：同一 ticket_id 以文件最后一条为准
  - 写幂等：`idempotency_key` 缺省时按内容哈希推导。**不能直接用 ticket_id
    做幂等键**——latest-wins 下同一 Ticket 的后续状态更新会被误吞
  - FAIL-OPEN：坏输入 / IO 异常 → read 给 error_code、write 返回 False
"""

from __future__ import annotations

import hashlib
import json
import os
from typing import Any, Dict, List, Optional

from dreambuddy_l0.ports.principal import (  # D1 Principal 硬门禁
    ALLOWED_ROLES_STORE,
    require_principal,
)

TABLE = "dsh_tickets"

# 内容哈希时剔除的易变字段（由持久化层追加，重放时会变化）
_VOLATILE_FIELDS = ("stored_at",)

# 适配器内部字段前缀（显式幂等键持久化用），对外读取时剥离
_INTERNAL_PREFIX = "_"
_IDEM_FIELD = "_adapter_idem_key"


def _strip_internal(payload: Dict[str, Any]) -> Dict[str, Any]:
    return {k: v for k, v in payload.items() if not str(k).startswith(_INTERNAL_PREFIX)}


def _content_key(payload: Dict[str, Any]) -> str:
    """按内容推导幂等键（剔除 stored_at 等易变/内部字段）。"""
    body = {
        k: v
        for k, v in payload.items()
        if k not in _VOLATILE_FIELDS and not str(k).startswith(_INTERNAL_PREFIX)
    }
    raw = json.dumps(body, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()


class TicketStoreAdapter:
    """把 legacy Ticket store 适配为 StorePort。

    legacy 需具备 `append(record) -> bool` 与 `read_all() -> list[dict]`；
    适配器不 import 34 的模块，避免通用 L0 包反向依赖业务宿主。
    """

    def __init__(self, legacy: Any, table: str = TABLE) -> None:
        self.legacy = legacy
        self.table = table

    # ---------- 内部 ----------

    def _latest(self) -> Dict[str, Dict[str, Any]]:
        """读全部记录并按 ticket_id 取最后一条（latest-wins）。"""
        try:
            rows = self.legacy.read_all() or []
        except Exception:
            return {}
        latest: Dict[str, Dict[str, Any]] = {}
        for rec in rows:
            if isinstance(rec, dict) and rec.get("ticket_id"):
                latest[str(rec["ticket_id"])] = rec
        return latest

    def _seen_keys(self) -> set:
        """重建已写入内容的幂等键集合（跨重启有效）。"""
        seen = set()
        try:
            rows = self.legacy.read_all() or []
        except Exception:
            return seen
        for rec in rows:
            if not isinstance(rec, dict):
                continue
            seen.add(_content_key(rec))
            if rec.get(_IDEM_FIELD):
                seen.add(str(rec[_IDEM_FIELD]))
        return seen

    # ---------- StorePort ----------

    def read(
        self,
        table: str,
        *,
        key: str,
        cursor: Optional[str] = None,
        limit: int = 100,
    ) -> Dict[str, Any]:
        if table != self.table:
            return {"row": None, "error_code": "unknown_table"}
        try:
            row = self._latest().get(str(key))
        except Exception:
            return {"row": None, "error_code": "read_error"}
        return {"row": _strip_internal(row)} if row else {"row": None, "error_code": "not_found"}

    @require_principal(ALLOWED_ROLES_STORE)  # D1：写接口硬门禁
    def write(
        self,
        table: str,
        *,
        data: Dict[str, Any],
        idempotency_key: str = "",
        _principal: Optional[Dict[str, Any]] = None,
    ) -> bool:
        if table != self.table:
            return False
        if not isinstance(data, dict) or not data.get("ticket_id"):
            return False
        key = idempotency_key or _content_key(data)
        try:
            if key in self._seen_keys():
                return True
            payload = dict(data)
            if idempotency_key:
                payload[_IDEM_FIELD] = idempotency_key  # 持久化显式键，跨重启可去重
            return bool(self.legacy.append(payload))
        except Exception:
            return False

    def query(
        self,
        table: str,
        *,
        filters: Optional[Dict[str, Any]] = None,
        cursor: Optional[str] = None,
        limit: int = 100,
    ) -> Dict[str, Any]:
        if table != self.table:
            return {"rows": [], "cursor": None, "error_code": "unknown_table"}
        try:
            rows: List[Dict[str, Any]] = [_strip_internal(r) for r in self._latest().values()]
        except Exception:
            return {"rows": [], "cursor": None, "error_code": "read_error"}
        for field, expected in (filters or {}).items():
            rows = [r for r in rows if r.get(field) == expected]
        return {"rows": rows[:limit], "cursor": None}

    def health(self) -> Dict[str, Any]:
        path = str(getattr(self.legacy, "path", "") or "")
        return {
            "ok": bool(path) and os.path.exists(path),
            "dialect": "jsonl-ticket",
            "tables": 1,
            "path": path,
        }
