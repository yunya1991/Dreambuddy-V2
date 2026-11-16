# -*- coding: utf-8 -*-
"""S6 paper 记账（SPEC-20261116 §5.7 / T6-4）。

只把 `D-K03` 的信号与门控结论落盘，供后续复盘/反思消费：
  - 表内**没有** order/position/size/quantity/side/action 等交易字段；
  - 不接执行层、不下单、不调用 LLM；
  - `ledger_id` 由 (as_of, target, horizon, direction, decision) 派生，重复记账幂等。
"""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Mapping, Optional

SCHEMA_VERSION = "1.0"
MODULE_ROOT = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
LEDGER_FILE = os.path.join(MODULE_ROOT, "data", "signal_ledger.db")

_FORBIDDEN_COLUMNS = {
    "order",
    "orders",
    "position",
    "positions",
    "size",
    "quantity",
    "side",
    "action",
}

_SCHEMA = """
CREATE TABLE IF NOT EXISTS signal_journal (
  ledger_id TEXT PRIMARY KEY,
  schema_version TEXT NOT NULL,
  as_of TEXT NOT NULL,
  target TEXT NOT NULL,
  horizon INTEGER NOT NULL,
  direction INTEGER NOT NULL,
  strength TEXT NOT NULL,
  score REAL,
  decision TEXT NOT NULL,
  reasons_json TEXT NOT NULL,
  context_json TEXT NOT NULL,
  members_json TEXT NOT NULL,
  recorded_at TEXT NOT NULL
)
"""


def _ledger_id(signal: Mapping[str, Any], decision: str) -> str:
    raw = "|".join(
        [
            str(signal.get("as_of") or ""),
            str(signal.get("target") or ""),
            str(int(signal.get("horizon") or 0)),
            str(int(signal.get("direction") or 0)),
            decision,
        ]
    )
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]


def _rows(document: Mapping[str, Any]) -> Iterable[Dict[str, Any]]:
    for signal in document.get("allowed") or document.get("signals") or []:
        reasons = ((signal.get("gating") or {}).get("reasons")) or []
        yield {
            "signal": signal,
            "decision": "allowed",
            "reasons": list(reasons),
        }
    for signal in document.get("blocked") or []:
        reasons = ((signal.get("gating") or {}).get("reasons")) or []
        yield {"signal": signal, "decision": "blocked", "reasons": list(reasons)}


def record_signals(
    document: Mapping[str, Any],
    *,
    db_path: Optional[str] = None,
    recorded_at: str = "",
) -> Dict[str, Any]:
    """幂等写账；返回 inserted/duplicates，不抛异常到调用方之外。"""
    path = db_path or LEDGER_FILE
    directory = os.path.dirname(path)
    if directory:
        os.makedirs(directory, exist_ok=True)
    stamp = recorded_at or datetime.now(timezone.utc).isoformat(timespec="seconds")

    inserted = 0
    duplicates = 0
    with sqlite3.connect(path) as conn:
        conn.execute(_SCHEMA)
        for item in _rows(document):
            signal = item["signal"]
            ledger_id = _ledger_id(signal, item["decision"])
            try:
                conn.execute(
                    "INSERT INTO signal_journal (ledger_id, schema_version, as_of, target, horizon, "
                    "direction, strength, score, decision, reasons_json, context_json, members_json, "
                    "recorded_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        ledger_id,
                        SCHEMA_VERSION,
                        str(signal.get("as_of") or ""),
                        str(signal.get("target") or ""),
                        int(signal.get("horizon") or 0),
                        int(signal.get("direction") or 0),
                        str(signal.get("strength") or ""),
                        signal.get("score"),
                        item["decision"],
                        json.dumps(item["reasons"], ensure_ascii=False),
                        json.dumps(
                            ((signal.get("gating") or {}).get("context")) or {}, ensure_ascii=False
                        ),
                        json.dumps(list(signal.get("members") or []), ensure_ascii=False),
                        stamp,
                    ),
                )
                inserted += 1
            except sqlite3.IntegrityError:
                duplicates += 1
        conn.commit()
    return {
        "ok": True,
        "inserted": inserted,
        "duplicates": duplicates,
        "recorded_at": stamp,
        "schema_version": SCHEMA_VERSION,
    }


def read_journal(
    *,
    db_path: Optional[str] = None,
    decision: Optional[str] = None,
    target: Optional[str] = None,
    limit: int = 100,
) -> List[Dict[str, Any]]:
    path = db_path or LEDGER_FILE
    if not os.path.isfile(path):
        return []
    clauses: List[str] = []
    params: List[Any] = []
    if decision:
        clauses.append("decision = ?")
        params.append(str(decision))
    if target:
        clauses.append("target = ?")
        params.append(str(target))
    where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
    params.append(max(1, int(limit)))
    with sqlite3.connect(path) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            f"SELECT * FROM signal_journal{where} ORDER BY recorded_at DESC, ledger_id LIMIT ?",
            params,
        ).fetchall()
    out: List[Dict[str, Any]] = []
    for row in rows:
        item = dict(row)
        item["reasons"] = json.loads(item.pop("reasons_json") or "[]")
        item["context"] = json.loads(item.pop("context_json") or "{}")
        item["members"] = json.loads(item.pop("members_json") or "[]")
        out.append(item)
    return out


def journal_columns(*, db_path: Optional[str] = None) -> List[str]:
    path = db_path or LEDGER_FILE
    if not os.path.isfile(path):
        return []
    with sqlite3.connect(path) as conn:
        return [str(row[1]) for row in conn.execute("PRAGMA table_info(signal_journal)")]


def forbidden_columns(*, db_path: Optional[str] = None) -> List[str]:
    """返回表内误入的交易字段（正常应为空列表）。"""
    return sorted(set(journal_columns(db_path=db_path)) & _FORBIDDEN_COLUMNS)
