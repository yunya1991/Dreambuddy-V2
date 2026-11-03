# -*- coding: utf-8 -*-
"""Ticket 状态 L0 持久化(T-DSH-P1 P1-1)。

依据: DESIGN-DSH-ARCH-UPGRADE v0.2 ADR-2(状态单一事实源=L0;禁止 DSH 内
维护第二套权威状态,DSH storages 仅作运行时缓存) + 验收 V5(重启后 Ticket
可从 L0 恢复)。

定位: ticket_state.py 是纯函数状态机(不持存储);本模块负责把每次迁移结果
追加写入 L0 快照(append-only, latest-wins),并提供恢复能力。存储后端可注入:
默认 JsonlTicketStore(本地/测试);云端 PG 后端以同接口(append/read_all)
注入,不在本模块范围。DSH 运行时不得另持权威副本——每次需要状态时从 L0 读。

硬约束:
  HC-1 FAIL-OPEN: 坏输入/坏行/IO 异常 → None/[]/{},不抛错
  HC-2 开关 enable_ticket_store 默认 False,关断时调用方不得加载本模块
"""

from __future__ import annotations

import json
import os
import time
from typing import Any, Dict, List, Optional

# 模块化开关(HC-2,默认 False)
TICKET_STORE_SWITCH = "enable_ticket_store"

# L0 根下快照相对路径(与 l1_case_store.jsonl 同域)
_STORE_REL_PATH = os.path.join("34-前端应用训练系统", "dsh_tickets.jsonl")


def is_ticket_store_enabled(flags: Optional[Dict[str, Any]] = None) -> bool:
    """模块化开关读取(HC-2)。flags 非 dict / 缺键 → False(默认关)。"""
    try:
        if not isinstance(flags, dict):
            return False
        return bool(flags.get(TICKET_STORE_SWITCH, False))
    except Exception:
        return False


class JsonlTicketStore:
    """L0 本地 jsonl 快照后端(append-only, latest-wins)。

    与 L0Foundation 相同的 root 约定: root/<34-前端应用训练系统>/dsh_tickets.jsonl。
    每行一个完整 Ticket 记录(含 history),同一 ticket_id 以最后一行为准。
    """

    def __init__(self, root: str) -> None:
        self.path = os.path.join(str(root), _STORE_REL_PATH)

    def append(self, record: Dict[str, Any]) -> bool:
        try:
            os.makedirs(os.path.dirname(self.path), exist_ok=True)
            with open(self.path, "a", encoding="utf-8") as f:
                f.write(json.dumps(record, ensure_ascii=False) + "\n")
            return True
        except Exception:
            return False

    def read_all(self) -> List[Dict[str, Any]]:
        try:
            if not os.path.exists(self.path):
                return []
            out: List[Dict[str, Any]] = []
            with open(self.path, encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        rec = json.loads(line)
                    except Exception:
                        continue  # 坏行跳过(FAIL-OPEN)
                    if isinstance(rec, dict) and rec.get("ticket_id"):
                        out.append(rec)
            return out
        except Exception:
            return []


def save_ticket(ticket: Any, store: Any) -> Optional[Dict[str, Any]]:
    """把 Ticket 当前状态追加写入 L0(latest-wins)。返回写入记录;非法 → None。"""
    try:
        if not isinstance(ticket, dict) or not ticket.get("ticket_id"):
            return None
        if store is None or not hasattr(store, "append"):
            return None
        record = dict(ticket)
        record["stored_at"] = time.time()
        if not store.append(record):
            return None
        return record
    except Exception:
        return None


def recover_tickets(store: Any) -> Dict[str, Dict[str, Any]]:
    """从 L0 恢复全部 Ticket(latest-wins)→ {ticket_id: ticket}。V5 重启恢复入口。"""
    try:
        if store is None or not hasattr(store, "read_all"):
            return {}
        latest: Dict[str, Dict[str, Any]] = {}
        for rec in store.read_all():
            latest[str(rec["ticket_id"])] = rec
        return latest
    except Exception:
        return {}


def load_ticket(ticket_id: Any, store: Any) -> Optional[Dict[str, Any]]:
    """读单个 Ticket 最新状态;不存在/坏输入 → None。"""
    try:
        if not ticket_id:
            return None
        return recover_tickets(store).get(str(ticket_id))
    except Exception:
        return None


def list_tickets(store: Any, state: Optional[str] = None) -> List[Dict[str, Any]]:
    """列出全部 Ticket(可按 state 过滤)。坏输入 → []。"""
    try:
        tickets = list(recover_tickets(store).values())
        if state is not None:
            tickets = [t for t in tickets if t.get("state") == state]
        return tickets
    except Exception:
        return []
