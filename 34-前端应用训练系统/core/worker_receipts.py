# -*- coding: utf-8 -*-
"""Worker 回执消费(T-DSH-P0 D2 闭环,SPEC-53 R14)。

定位: Router 只写 `dsh_worker_inbox.jsonl` 派单,执行方(Worker)把结果 append 到
`dsh_worker_receipts.jsonl`。本模块把回执映射为 Ticket 状态迁移,是
`completed_refs` 的唯一可持续来源(替代调用方注入,DD-D2-3)。

回执行契约(append-only,latest-wins by ticket_id):
    {"ticket_id": "TK-R1", "status": "done" | "failed",
     "failure_class": "retryable" | "manual", "evidence": {...}, "at": 1700000000}

硬约束(PROPOSAL-P0-D3 §4.4 W0 契约冻结):
  done                    → ended(终态,释放 Worker 槽,依赖闸可解除)
  failed + retryable      → paused + waiting_job(自动退避重试,不占人工)
  failed + manual         → waitsForPerson(重试耗尽/权限错误,需人工)
  failed 缺 failure_class → 按 manual 兼容(旧回执)
  坏行/未知状态            → 跳过并计入 ignored,不影响本轮 pass(FAIL-OPEN)
"""

from __future__ import annotations

import json
import os
import time
from typing import Any, Dict, List, Optional, Tuple

_RECEIPTS_REL_PATH = os.path.join("34-前端应用训练系统", "dsh_worker_receipts.jsonl")

_ENDED_STATUSES = ("done", "success")
_FAILED_STATUSES = ("failed", "error")


def _resolve_target(status: str, failure_class: Any) -> Optional[Tuple[str, Optional[str]]]:
    """status + failure_class → (目标状态, paused_reason);未知 status → None。"""
    if status in _ENDED_STATUSES:
        return ("ended", None)
    if status in _FAILED_STATUSES:
        fc = str(failure_class or "").strip().lower()
        if fc == "retryable":
            return ("paused", "waiting_job")
        return ("waitsForPerson", None)  # manual / 缺省 / 未知值(旧回执兼容)
    return None


def receipts_path(store: Any) -> Optional[str]:
    """从 TicketStore 推导回执文件路径(与 dsh_tickets.jsonl 同目录)。"""
    try:
        return os.path.join(os.path.dirname(str(store.path)), os.path.basename(_RECEIPTS_REL_PATH))
    except Exception:
        return None


def read_receipts(path: Optional[str]) -> Tuple[Dict[str, Dict[str, Any]], int]:
    """读回执文件 → ({ticket_id: 最新回执}, 坏行数)。文件不存在 → ({}, 0)。"""
    if not path or not os.path.exists(path):
        return {}, 0
    latest: Dict[str, Dict[str, Any]] = {}
    bad = 0
    try:
        with open(path, "r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except Exception:
                    bad += 1
                    continue
                if not isinstance(rec, dict) or not rec.get("ticket_id"):
                    bad += 1
                    continue
                latest[str(rec["ticket_id"])] = rec
    except Exception:
        return latest, bad
    return latest, bad


def apply_receipts(
    tickets: Dict[str, Dict[str, Any]],
    store: Any,
    now: Optional[float] = None,
) -> Dict[str, Any]:
    """把回执应用到内存快照并写回 L0。返回 {applied: [...], ignored: N}。

    幂等: 已 ended 的 Ticket 再次收到回执 → 忽略(不重写)。
    """
    from .ticket_state import transition_ticket
    from .ticket_store import save_ticket

    path = receipts_path(store)
    receipts, bad = read_receipts(path)
    applied: List[Dict[str, Any]] = []
    ignored = bad
    ts = float(now) if now is not None else time.time()

    for ticket_id, rec in receipts.items():
        ticket = tickets.get(ticket_id)
        if ticket is None:
            ignored += 1
            continue
        if str(ticket.get("state")) == "ended":
            continue  # 终态不可转出,幂等
        status = str(rec.get("status") or "").lower()
        failure_class = str(rec.get("failure_class") or "").strip().lower() or None
        target = _resolve_target(status, failure_class)
        if target is None:
            ignored += 1
            continue
        # 回执重放幂等: 同一内容回执只应用一次(文件每轮重读,人工恢复后
        # 旧 failed 不得再次把 Ticket 打回 paused)
        key = json.dumps(rec, sort_keys=True, ensure_ascii=False)
        if ticket.get("last_receipt_key") == key:
            continue
        to_state, paused_reason = target
        moved = transition_ticket(ticket, to_state, paused_reason=paused_reason, now=ts)
        if moved is None:
            ignored += 1
            continue
        moved["last_receipt"] = {
            "status": status,
            "failure_class": failure_class,
            "at": ts,
        }
        moved["last_receipt_key"] = key
        if rec.get("evidence") is not None:
            moved["receipt_evidence"] = rec.get("evidence")
        if save_ticket(moved, store) is None:
            ignored += 1
            continue
        tickets[ticket_id] = moved
        applied.append({"ticket_id": ticket_id, "from": str(ticket.get("state")), "to": to_state})

    return {"applied": applied, "ignored": ignored}
