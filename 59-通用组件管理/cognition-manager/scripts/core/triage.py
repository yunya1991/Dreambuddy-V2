"""会话与待定分拣。

契约见 references/triage.md：
- 默认演练：只列出过期会话（未分拣且已过 expires_at）与 pending.state='open'；
- `--expire-sessions`：把过期会话标记为已回收（triaged_at 置为当前时间）；
- `--drop-pending`：review_count >= 3 的待定项置 dropped，其余 review_count += 1；
- 不启动后台守护进程，所有动作都是前台一次性执行。
"""

from __future__ import annotations

import time

from . import store

PENDING_DROP_REVIEWS = 3
ITEM_LIMIT = 20


def _session_items(rows) -> list:
    return [
        {
            "id": row["id"],
            "content_ref": row["content_ref"],
            "created_at": row["created_at"],
            "expires_at": row["expires_at"],
            "overdue_hours": round((row["expires_at"] - row["created_at"]) / 3600, 1),
        }
        for row in rows[:ITEM_LIMIT]
    ]


def _pending_items(rows) -> list:
    return [
        {
            "id": row["id"],
            "kind": row["kind"],
            "payload_ref": row["payload_ref"],
            "review_count": int(row["review_count"] or 0),
            "age_hours": round((time.time() - float(row["created_at"] or 0)) / 3600, 1),
        }
        for row in rows[:ITEM_LIMIT]
    ]


def triage(root, config: dict, conn, *, expire_sessions: bool = False,
           drop_pending: bool = False) -> dict:
    """列出并（可选）处理过期会话与待定项。"""
    now = time.time()

    expired_rows = conn.execute(
        "SELECT id, content_ref, created_at, expires_at FROM sessions "
        "WHERE triaged_at IS NULL AND expires_at IS NOT NULL AND expires_at < ? "
        "ORDER BY expires_at ASC",
        (now,),
    ).fetchall()

    pending_rows = conn.execute(
        "SELECT id, kind, payload_ref, created_at, review_count FROM pending "
        "WHERE state = 'open' ORDER BY created_at ASC"
    ).fetchall()

    marked_expired = 0
    if expire_sessions and expired_rows:
        ids = [row["id"] for row in expired_rows]
        placeholders = ",".join("?" for _ in ids)
        marked_expired = conn.execute(
            "UPDATE sessions SET triaged_at = ? WHERE id IN ({})".format(placeholders),
            (now, *ids),
        ).rowcount or 0

    dropped, incremented = [], []
    if drop_pending:
        for row in pending_rows:
            count = int(row["review_count"] or 0)
            if count >= PENDING_DROP_REVIEWS:
                conn.execute(
                    "UPDATE pending SET state = 'dropped' WHERE id = ?", (row["id"],)
                )
                dropped.append(row["payload_ref"] or str(row["id"]))
            else:
                conn.execute(
                    "UPDATE pending SET review_count = review_count + 1 WHERE id = ?",
                    (row["id"],),
                )
                incremented.append(row["payload_ref"] or str(row["id"]))

    if expire_sessions or drop_pending:
        conn.commit()

    ttl_days = int(config.get("session_ttl_days", 7))
    notes = []
    if not expired_rows and not pending_rows:
        notes.append("没有需要分拣的会话或待定项")
    if expire_sessions:
        notes.append("已回收 {} 条过期会话".format(marked_expired))
    if drop_pending:
        notes.append("丢弃 {} 条、复核 {} 条待定项".format(len(dropped), len(incremented)))
    if not expire_sessions and not drop_pending:
        notes.append("演练模式：未修改任何状态（加 --expire-sessions / --drop-pending 才执行）")

    return {
        "schema_version": "1.0",
        "command": "triage",
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "dry_run": not (expire_sessions or drop_pending),
        "session_ttl_days": ttl_days,
        "sessions": {
            "expired": len(expired_rows),
            "marked_expired": marked_expired,
            "items": _session_items(expired_rows),
        },
        "pending": {
            "open": len(pending_rows),
            "drop_threshold": PENDING_DROP_REVIEWS,
            "dropped": len(dropped),
            "incremented": len(incremented),
            "dropped_refs": dropped[:ITEM_LIMIT],
            "items": _pending_items(pending_rows),
        },
        "notes": notes,
    }
