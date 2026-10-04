#!/usr/bin/env python3
"""
用户层记忆 HTTP Adapter — 自包含 SQLite 操作（与 cognitive_memory.db 物理隔离）。

用法:
  python3 user_memory_adapter.py get_prefs '{"user_id":"default"}'
  python3 user_memory_adapter.py set_pref '{"user_id":"default","key":"risk_tolerance","value":"low"}'
  python3 user_memory_adapter.py list_notes '{"user_id":"default"}'
  python3 user_memory_adapter.py create_note '{"user_id":"default","title":"x","content":"y","tags":"a,b"}'
  python3 user_memory_adapter.py delete_note '{"id":"user:note:xxx"}'

stdout: 单行 JSON {"ok": true, "data": {...}} 或 {"ok": false, "error": "..."}
stderr: 错误日志（不污染 stdout）

设计:
  - 复刻 P0 cognitive_adapter.py stdout→stderr 重定向模式 (VM-1789618914215)
  - FAIL-OPEN: 异常返回 {ok: false, error, traceback}, 不崩溃
  - 与 cognitive_memory.db 物理隔离（独立文件 user_memory.db）
  - SQLite WAL 模式 + 自动 schema 初始化
  - 不改 4-MEMORY 后端, 仅在 3.1-FRONTEND 接入层

硬约束 (VM-1786242777697 用户/认知边界):
  - 用户层只存用户偏好/笔记/会话（用户权威）
  - ❌ 禁止写 cognitive_memory.db
  - ❌ 用户笔记不可自动升级为 VM（P3 人工审批流）
"""
import sys
import os
import json
import time
import sqlite3
import traceback
from pathlib import Path


DB_PATH = Path(__file__).resolve().parent.parent / "data" / "user_memory.db"


SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS user_preferences (
  user_id TEXT NOT NULL,
  pref_key TEXT NOT NULL,
  pref_value TEXT,
  updated_at INTEGER,
  PRIMARY KEY (user_id, pref_key)
);

CREATE TABLE IF NOT EXISTS user_sessions (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id TEXT NOT NULL,
  session_id TEXT,
  topic TEXT,
  summary TEXT,
  created_at INTEGER
);

CREATE TABLE IF NOT EXISTS user_notes (
  id TEXT PRIMARY KEY,
  user_id TEXT NOT NULL,
  title TEXT,
  content TEXT,
  tags TEXT,
  promoted_to TEXT,
  created_at INTEGER,
  updated_at INTEGER
);

CREATE INDEX IF NOT EXISTS idx_user_notes_user_id ON user_notes(user_id);
CREATE INDEX IF NOT EXISTS idx_user_sessions_user_id ON user_sessions(user_id);
"""


def _safe_print(payload):
    """唯一向 stdout 输出的入口，确保单行 JSON。"""
    sys.stdout = sys.__stdout__
    sys.stdout.write(json.dumps(payload, ensure_ascii=False) + '\n')
    sys.stdout.flush()


def _get_conn():
    """获取 SQLite 连接（WAL 模式 + 自动 schema 初始化）。"""
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    # WAL 模式：允许并发读 + 单写
    try:
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA synchronous=NORMAL;")
    except Exception:
        pass  # FAIL-OPEN
    # 自动初始化 schema
    conn.executescript(SCHEMA_SQL)
    conn.commit()
    return conn


def _row_to_dict(row):
    return {k: row[k] for k in row.keys()} if row else None


# ============================================================
# 命令处理
# ============================================================

def cmd_get_prefs(args):
    user_id = args.get("user_id", "default")
    conn = _get_conn()
    try:
        rows = conn.execute(
            "SELECT user_id, pref_key, pref_value, updated_at FROM user_preferences WHERE user_id = ? ORDER BY pref_key",
            (user_id,)
        ).fetchall()
        return {"ok": True, "data": {"preferences": [_row_to_dict(r) for r in rows], "count": len(rows)}}
    finally:
        conn.close()


def cmd_set_pref(args):
    user_id = args.get("user_id", "default")
    key = args.get("key")
    value = args.get("value")
    if not key:
        return {"ok": False, "error": "missing required field: key"}
    conn = _get_conn()
    try:
        now = int(time.time())
        conn.execute(
            "INSERT INTO user_preferences(user_id, pref_key, pref_value, updated_at) VALUES(?,?,?,?) "
            "ON CONFLICT(user_id, pref_key) DO UPDATE SET pref_value=excluded.pref_value, updated_at=excluded.updated_at",
            (user_id, key, value, now)
        )
        conn.commit()
        return {"ok": True, "data": {"user_id": user_id, "key": key, "value": value, "updated_at": now}}
    finally:
        conn.close()


def cmd_list_notes(args):
    user_id = args.get("user_id", "default")
    limit = int(args.get("limit", 100))
    conn = _get_conn()
    try:
        rows = conn.execute(
            "SELECT id, user_id, title, content, tags, promoted_to, created_at, updated_at "
            "FROM user_notes WHERE user_id = ? ORDER BY updated_at DESC LIMIT ?",
            (user_id, limit)
        ).fetchall()
        return {"ok": True, "data": {"notes": [_row_to_dict(r) for r in rows], "count": len(rows)}}
    finally:
        conn.close()


def cmd_create_note(args):
    user_id = args.get("user_id", "default")
    title = args.get("title", "")
    content = args.get("content", "")
    tags = args.get("tags", "")
    if not content:
        return {"ok": False, "error": "missing required field: content"}
    note_id = f"user:note:{int(time.time()*1000)}:{os.getpid()}"
    conn = _get_conn()
    try:
        now = int(time.time())
        conn.execute(
            "INSERT INTO user_notes(id, user_id, title, content, tags, promoted_to, created_at, updated_at) "
            "VALUES(?,?,?,?,?,NULL,?,?)",
            (note_id, user_id, title, content, tags, now, now)
        )
        conn.commit()
        return {"ok": True, "data": {"id": note_id, "user_id": user_id, "title": title, "created_at": now}}
    finally:
        conn.close()


def cmd_delete_note(args):
    note_id = args.get("id")
    if not note_id:
        return {"ok": False, "error": "missing required field: id"}
    conn = _get_conn()
    try:
        cur = conn.execute("DELETE FROM user_notes WHERE id = ?", (note_id,))
        conn.commit()
        deleted = cur.rowcount
        return {"ok": True, "data": {"id": note_id, "deleted": deleted}}
    finally:
        conn.close()


def cmd_mark_promoted(args):
    """P3 沉淀流：将 user:note:* 标记为已沉淀到 VM-xxx（不删除原记录）。"""
    note_id = args.get("id")
    promoted_to = args.get("promoted_to")
    if not note_id or not promoted_to:
        return {"ok": False, "error": "missing required fields: id, promoted_to"}
    conn = _get_conn()
    try:
        now = int(time.time())
        cur = conn.execute(
            "UPDATE user_notes SET promoted_to = ?, updated_at = ? WHERE id = ?",
            (promoted_to, now, note_id)
        )
        conn.commit()
        return {"ok": True, "data": {"id": note_id, "promoted_to": promoted_to, "updated": cur.rowcount}}
    finally:
        conn.close()


def cmd_health(args):
    """健康检查 + 物理隔离验证。"""
    conn = _get_conn()
    try:
        # 验证 user_notes 表存在且不含 VM- 前缀记录
        cur = conn.execute("SELECT COUNT(*) AS c FROM user_notes WHERE id LIKE 'VM-%'")
        vm_leak = cur.fetchone()["c"]
        cur2 = conn.execute("SELECT COUNT(*) AS c FROM user_preferences")
        pref_count = cur2.fetchone()["c"]
        cur3 = conn.execute("SELECT COUNT(*) AS c FROM user_notes")
        note_count = cur3.fetchone()["c"]
        return {
            "ok": True,
            "data": {
                "status": "healthy",
                "db_path": str(DB_PATH),
                "physical_isolation": vm_leak == 0,
                "preferences_count": pref_count,
                "notes_count": note_count,
                "vm_leak_count": vm_leak,
            }
        }
    finally:
        conn.close()


COMMANDS = {
    "get_prefs": cmd_get_prefs,
    "set_pref": cmd_set_pref,
    "list_notes": cmd_list_notes,
    "create_note": cmd_create_note,
    "delete_note": cmd_delete_note,
    "mark_promoted": cmd_mark_promoted,
    "health": cmd_health,
}


def main():
    if len(sys.argv) < 2:
        _safe_print({"ok": False, "error": "missing command argument"})
        return

    command = sys.argv[1]
    args_raw = sys.argv[2] if len(sys.argv) > 2 else '{}'
    try:
        args = json.loads(args_raw) if args_raw else {}
    except json.JSONDecodeError as e:
        _safe_print({"ok": False, "error": f"invalid args JSON: {e}"})
        return

    # === 关键: import 和 handler 执行期间把 stdout 重定向到 stderr ===
    sys.stdout = sys.stderr

    if command not in COMMANDS:
        _safe_print({
            "ok": False,
            "error": f"unknown command: {command}. available: {sorted(COMMANDS.keys())}",
        })
        return

    try:
        result = COMMANDS[command](args)
        _safe_print(result)
    except Exception as e:
        _safe_print({
            "ok": False,
            "error": f"handler_error: {type(e).__name__}: {e}",
            "traceback": traceback.format_exc(),
        })


if __name__ == "__main__":
    main()
