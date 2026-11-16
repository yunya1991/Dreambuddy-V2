# -*- coding: utf-8 -*-
"""H4：paused Ticket 的可选恢复点（checkpoint sidecar）。

冲突处理（相对现有 `core/ticket_resume.py` 与 Ticket 四态状态机）：
    - 现有续跑依赖 `paused_reason` + `waiting_on` 事件唤醒，**不要求** checkpoint；
    - 本模块不修改 Ticket schema / `recover_resumable` / `resume_on_event`；
    - checkpoint 是**可选 sidecar**：仅当 Ticket 挂了 `checkpoint_id` 时才做
      hash/过期守卫；未挂 checkpoint 的 Ticket 保持原有续跑语义。
    - 强制「paused 必引用 checkpoint」属 P2 enforce，本阶段不开启。

契约：56/contracts/checkpoint.schema.json（v1.0）。
"""

from __future__ import annotations

import json
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, Optional

CHECKPOINT_SCHEMA_VERSION = "1.0"
RESUME_MAX_AGE_S = 604800  # 7 天，必须与 resume_guard.max_age_s 一致

_HASH_PATTERN = re.compile(r"^sha256:[0-9a-f]{64}$")
_ID_PATTERN = re.compile(r"^[A-Za-z0-9._:-]{3,64}$")


class CheckpointError(ValueError):
    """checkpoint 不合法（fail-closed，不静默降级）"""


def _parse_ts(value: Any) -> datetime:
    try:
        stamp = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError) as exc:
        raise CheckpointError(f"时间字段不是合法 RFC3339: {value!r}") from exc
    return stamp if stamp.tzinfo else stamp.replace(tzinfo=timezone.utc)


def build_checkpoint(
    *,
    session_id: str,
    ticket_id: str,
    content_hash: str,
    git: Dict[str, Any],
    artifacts: Iterable[Dict[str, Any]] = (),
    created_at: Optional[str] = None,
    checkpoint_id: Optional[str] = None,
) -> Dict[str, Any]:
    """生成 v1.0 checkpoint；只存引用与 hash，不存凭据/大对象。"""
    if not isinstance(session_id, str) or not _ID_PATTERN.match(session_id):
        raise CheckpointError(f"session_id 不符合契约 pattern: {session_id!r}")
    if not isinstance(ticket_id, str) or not (1 <= len(ticket_id) <= 64):
        raise CheckpointError(f"ticket_id 不符合契约长度: {ticket_id!r}")
    if not isinstance(content_hash, str) or not _HASH_PATTERN.match(content_hash):
        raise CheckpointError(f"content_hash 非法: {content_hash!r}")

    if not isinstance(git, dict):
        raise CheckpointError("git 必须是对象")
    for key in ("repo", "commit", "dirty"):
        if key not in git:
            raise CheckpointError(f"git 缺少 {key}")
    if not isinstance(git.get("dirty"), bool):
        raise CheckpointError("git.dirty 必须是布尔值")

    normalized_artifacts = []
    for item in artifacts or []:
        if not isinstance(item, dict) or not item.get("path"):
            raise CheckpointError("artifacts 每项必须含 path")
        if not _HASH_PATTERN.match(str(item.get("hash"))):
            raise CheckpointError(f"artifacts hash 非法: {item.get('hash')!r}")
        normalized_artifacts.append({"path": str(item["path"]), "hash": str(item["hash"])})

    if git["dirty"] and not normalized_artifacts:
        raise CheckpointError("git.dirty=true 时必须在 artifacts 列出未提交文件")

    stamp = _parse_ts(created_at or datetime.now(timezone.utc).isoformat())

    return {
        "schema_version": CHECKPOINT_SCHEMA_VERSION,
        "checkpoint_id": checkpoint_id or f"ckpt-{uuid.uuid4().hex[:12]}",
        "session_id": session_id,
        "ticket_id": ticket_id,
        "state": "paused",
        "content_hash": content_hash,
        "git": {"repo": str(git["repo"]), "commit": str(git["commit"]), "dirty": git["dirty"]},
        "artifacts": normalized_artifacts,
        "created_at": stamp.isoformat(),
        "resume_guard": {"requires_same_hash": True, "max_age_s": RESUME_MAX_AGE_S},
    }


def bind_ticket(ticket: Dict[str, Any], checkpoint: Dict[str, Any]) -> Dict[str, Any]:
    """把 checkpoint_id 挂到 paused Ticket（返回新对象，不改原 Ticket）。"""
    if not isinstance(ticket, dict) or not isinstance(checkpoint, dict):
        raise CheckpointError("ticket / checkpoint 必须是 dict")
    if ticket.get("state") != "paused":
        raise CheckpointError("只有 paused Ticket 可以绑定 checkpoint")
    if ticket.get("ticket_id") != checkpoint.get("ticket_id"):
        raise CheckpointError("ticket_id 与 checkpoint.ticket_id 不一致")
    out = dict(ticket)
    out["checkpoint_id"] = str(checkpoint["checkpoint_id"])
    return out


def validate_resume(
    checkpoint: Dict[str, Any],
    *,
    current_content_hash: str,
    now: Optional[Any] = None,
) -> Dict[str, Any]:
    """resume 前守卫：hash 不一致或超过 7 天 → needs_review，禁止静默续跑。"""
    if not isinstance(checkpoint, dict):
        raise CheckpointError("checkpoint 必须是 dict")
    guard = checkpoint.get("resume_guard") or {}
    if guard.get("requires_same_hash") is not True:
        raise CheckpointError("resume_guard.requires_same_hash 必须为 true")
    max_age_s = guard.get("max_age_s")
    if max_age_s != RESUME_MAX_AGE_S:
        raise CheckpointError(f"resume_guard.max_age_s 必须为 {RESUME_MAX_AGE_S}")

    if not isinstance(current_content_hash, str) or not _HASH_PATTERN.match(current_content_hash):
        raise CheckpointError(f"current_content_hash 非法: {current_content_hash!r}")

    current_ts = _parse_ts(now or datetime.now(timezone.utc).isoformat())
    created_ts = _parse_ts(checkpoint.get("created_at"))
    age_s = (current_ts - created_ts).total_seconds()
    if age_s > max_age_s:
        return {
            "ok": False,
            "status": "needs_review",
            "reason": "checkpoint_expired",
            "age_s": age_s,
        }
    if checkpoint.get("content_hash") != current_content_hash:
        return {
            "ok": False,
            "status": "needs_review",
            "reason": "checkpoint_hash_mismatch",
            "expected": checkpoint.get("content_hash"),
            "actual": current_content_hash,
        }
    return {"ok": True, "status": "resume", "reason": None, "age_s": age_s}


def write_checkpoint(checkpoint: Dict[str, Any], path: Path) -> Path:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(checkpoint, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return target


def read_checkpoint(path: Path) -> Dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


__all__ = [
    "CHECKPOINT_SCHEMA_VERSION",
    "CheckpointError",
    "RESUME_MAX_AGE_S",
    "bind_ticket",
    "build_checkpoint",
    "read_checkpoint",
    "validate_resume",
    "write_checkpoint",
]
