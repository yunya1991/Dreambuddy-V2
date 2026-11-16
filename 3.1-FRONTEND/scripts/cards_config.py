#!/usr/bin/env python3
"""cards_config.py — 卡片看板参数的服务端唯一事实源（SPEC-54 R3b）。

`19-数据访问层/data/visual_cards.db` 独立库，不碰既有 mm_metrics / 业务库。
`user_id` 只由 Next 路由从 session 注入，脚本本身不鉴权（信任边界在路由层）。

用法：
  python3 scripts/cards_config.py --op get --user U [--tab T]
  python3 scripts/cards_config.py --op put --payload '{"user":"U","tab":"all","panels":[...]}'
"""

import argparse
import json
import os
import sqlite3
import sys
import time
from typing import Any, Dict, List, Optional

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.normpath(os.path.join(_SCRIPT_DIR, "..", ".."))
DB_PATH = os.environ.get("VISUAL_CARDS_DB") or os.path.join(
    _REPO_ROOT, "19-数据访问层", "data", "visual_cards.db"
)

MAX_ARGS_BYTES = 64 * 1024  # 单条 args_json
MAX_PANELS = 200  # 单用户面板总数
MAX_TOTAL_BYTES = 1024 * 1024  # 单用户 args 总量
MAX_ID_LEN = 200

SCHEMA = """
CREATE TABLE IF NOT EXISTS card_config (
  user_id          TEXT NOT NULL,
  tab_id           TEXT NOT NULL,
  panel_key        TEXT NOT NULL,
  capability_id    TEXT NOT NULL,
  title            TEXT,
  kind             TEXT,
  args_json        TEXT NOT NULL,
  data_provenance  TEXT NOT NULL DEFAULT 'pool',
  updated_at       INTEGER NOT NULL,
  PRIMARY KEY (user_id, tab_id, panel_key)
);
CREATE INDEX IF NOT EXISTS idx_card_config_tab ON card_config(user_id, tab_id);
"""

# 兼容 v0.6 之前建的表（只有 args_json，无 title/kind）
_OPTIONAL_COLUMNS = {"title": "TEXT", "kind": "TEXT"}


def _result(code: str, **extra: Any) -> Dict[str, Any]:
    return {"ok": code == "ok", "code": code, **extra}


def _connect(create: bool = True) -> sqlite3.Connection:
    if create:
        os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=10)
    if create:
        conn.executescript(SCHEMA)
        existing = {row[1] for row in conn.execute("PRAGMA table_info(card_config)")}
        for column, ddl in _OPTIONAL_COLUMNS.items():
            if column not in existing:
                conn.execute(f"ALTER TABLE card_config ADD COLUMN {column} {ddl}")
        conn.commit()
    return conn


def _clean_id(value: Any, field: str) -> str:
    text = str(value or "").strip()
    if not text or len(text) > MAX_ID_LEN:
        raise ValueError(f"{field} 不能为空且长度 ≤ {MAX_ID_LEN}")
    return text


def get_config(user: str, tab: Optional[str] = None) -> Dict[str, Any]:
    if not os.path.isfile(DB_PATH):
        return _result("ok", items=[], count=0)
    conn = _connect(create=False)
    try:
        sql = (
            "SELECT tab_id, panel_key, capability_id, title, kind, args_json, "
            "data_provenance, updated_at FROM card_config WHERE user_id = ?"
        )
        params: List[Any] = [user]
        if tab:
            sql += " AND tab_id = ?"
            params.append(tab)
        sql += " ORDER BY tab_id, panel_key"
        rows = conn.execute(sql, params).fetchall()
    finally:
        conn.close()
    items = []
    for tab_id, panel_key, capability_id, title, kind, args_json, provenance, updated_at in rows:
        try:
            args = json.loads(args_json)
        except (TypeError, ValueError):
            args = {}
        items.append(
            {
                "tab_id": tab_id,
                "panel_key": panel_key,
                "capability_id": capability_id,
                "title": title or capability_id,
                "kind": kind or "",
                "args": args if isinstance(args, dict) else {},
                "data_provenance": provenance,
                "updated_at": updated_at,
            }
        )
    return _result("ok", items=items, count=len(items))


def put_config(payload: Dict[str, Any]) -> Dict[str, Any]:
    """整页快照替换：该 (user, tab) 下不存在的 panel_key 即被删除。"""
    try:
        user = _clean_id(payload.get("user"), "user")
        tab = _clean_id(payload.get("tab"), "tab")
    except ValueError as exc:
        return _result("invalid_params", reason=str(exc))

    raw_panels = payload.get("panels")
    if not isinstance(raw_panels, list):
        return _result("invalid_params", reason="panels 必须是数组")

    now = int(time.time())
    rows = []
    total_bytes = 0
    for item in raw_panels:
        if not isinstance(item, dict):
            return _result("invalid_params", reason="panels 元素必须是对象")
        try:
            panel_key = _clean_id(item.get("panel_key"), "panel_key")
            capability_id = _clean_id(item.get("capability_id"), "capability_id")
        except ValueError as exc:
            return _result("invalid_params", reason=str(exc))
        args = item.get("args")
        if args is not None and not isinstance(args, dict):
            return _result("invalid_params", reason=f"{panel_key}: args 必须是对象")
        args_json = json.dumps(args or {}, ensure_ascii=False, separators=(",", ":"))
        size = len(args_json.encode("utf-8"))
        if size > MAX_ARGS_BYTES:
            return _result(
                "payload_too_large", reason=f"{panel_key}: args_json {size}B > {MAX_ARGS_BYTES}B"
            )
        total_bytes += size
        provenance = str(item.get("data_provenance") or "pool")[:32]
        title = str(item.get("title") or capability_id)[:200]
        kind = str(item.get("kind") or "")[:32]
        rows.append((user, tab, panel_key, capability_id, title, kind, args_json, provenance, now))

    if len(rows) > MAX_PANELS or total_bytes > MAX_TOTAL_BYTES:
        return _result(
            "payload_too_large",
            reason=f"面板数 {len(rows)}/{MAX_PANELS}，args 总量 {total_bytes}B/{MAX_TOTAL_BYTES}B",
        )

    conn = _connect()
    try:
        conn.execute("DELETE FROM card_config WHERE user_id = ? AND tab_id = ?", (user, tab))
        conn.executemany(
            "INSERT INTO card_config "
            "(user_id, tab_id, panel_key, capability_id, title, kind, args_json, "
            "data_provenance, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            rows,
        )
        existing = conn.execute(
            "SELECT COUNT(*) FROM card_config WHERE user_id = ?", (user,)
        ).fetchone()[0]
        conn.commit()
    finally:
        conn.close()
    if existing > MAX_PANELS:
        return _result("payload_too_large", reason=f"单用户面板总数 {existing} > {MAX_PANELS}")
    return _result("ok", tab_id=tab, count=len(rows))


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="卡片配置持久化")
    parser.add_argument("--op", required=True, choices=["get", "put"])
    parser.add_argument("--user", default="")
    parser.add_argument("--tab", default="")
    parser.add_argument("--payload", default="")
    parser.add_argument("--payload-file", dest="payload_file", default="")
    args = parser.parse_args(argv)

    try:
        if args.op == "get":
            user = args.user.strip()
            if not user:
                result = _result("invalid_params", reason="user 不能为空")
            else:
                result = get_config(user, args.tab.strip() or None)
        else:
            raw = "{}"
            if args.payload_file:
                with open(args.payload_file, "r", encoding="utf-8") as handle:
                    raw = handle.read()
            elif args.payload:
                raw = args.payload
            payload = json.loads(raw or "{}")
            if not isinstance(payload, dict):
                raise ValueError("payload must be object")
            result = put_config(payload)
    except (json.JSONDecodeError, ValueError) as exc:
        result = _result("invalid_params", reason=f"payload: {exc}")
    except Exception as exc:  # noqa: BLE001 — FAIL-OPEN，由路由降级
        result = _result("error", reason=f"{type(exc).__name__}: {exc}")

    sys.stdout.write(json.dumps(result, ensure_ascii=False) + "\n")
    sys.stdout.flush()
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
