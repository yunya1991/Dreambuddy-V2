# -*- coding: utf-8 -*-
"""S7 反思记账（SPEC-20261116 §5.8 / T7-1 / CR-13）。

纪律：
  - 建议必须是结构化对象，**必带 `suggestion_id` + `ab_slot`**，缺一不可入账；
  - 只写建议与回填结果，不改参数、不改门禁、不调用 LLM；
  - 下期 `outcomes.json` 按 `suggestion_id` 回填，A/B 槽位不一致直接拒绝。
"""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Mapping, Optional

SCHEMA_VERSION = "1.0"
AB_SLOTS = ("A", "B")
SUGGESTION_TYPES = (
    "conflict_followup",
    "gate_relax",
    "gate_tighten",
    "evidence_bar",
)
STATUSES = ("pending", "evaluated", "rejected")
MODULE_ROOT = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
DB_FILE = os.path.join(MODULE_ROOT, "data", "reflection_suggestions.db")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS reflection_suggestion (
  suggestion_id TEXT PRIMARY KEY,
  schema_version TEXT NOT NULL,
  as_of TEXT NOT NULL,
  type TEXT NOT NULL,
  ab_slot TEXT NOT NULL,
  status TEXT NOT NULL,
  evidence_json TEXT NOT NULL,
  expected_effect TEXT NOT NULL,
  created_at TEXT NOT NULL,
  evaluated_at TEXT,
  outcome_json TEXT
)
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _suggestion(
    as_of: str, type_: str, ab_slot: str, evidence: Mapping[str, Any], expected: str
) -> Dict[str, Any]:
    digest = hashlib.sha1(
        f"{as_of}|{type_}|{ab_slot}|{json.dumps(evidence, sort_keys=True)}".encode("utf-8")
    ).hexdigest()[:8]
    return {
        "suggestion_id": f"SUG-{type_}-{as_of or 'na'}-{digest}",
        "as_of": as_of,
        "type": type_,
        "ab_slot": ab_slot,
        "status": "pending",
        "evidence": dict(evidence),
        "expected_effect": expected,
    }


def build_suggestions(
    document: Mapping[str, Any],
    *,
    as_of: str = "",
    ab_slot: str = "B",
    ma_against_min: int = 2,
    extreme_min: int = 2,
) -> Dict[str, Any]:
    """从门控结果生成规则化建议；不产生自由文本，只出模板句。"""
    if ab_slot not in AB_SLOTS:
        raise ValueError(f"ab_slot 必须是 {AB_SLOTS} 之一")
    by_reason = (document.get("ablation") or {}).get("by_reason") or {}
    allowed = document.get("allowed") or []
    conflicts = document.get("conflicts") or []
    suggestions: List[Dict[str, Any]] = []

    if conflicts:
        suggestions.append(
            _suggestion(
                as_of,
                "conflict_followup",
                ab_slot,
                {"conflicts": len(conflicts)},
                "先补冲突归因（方法/变换分歧），再决定是否允许双向信号。",
            )
        )
    ma_against = int(by_reason.get("ma_against") or 0)
    if ma_against >= int(ma_against_min):
        suggestions.append(
            _suggestion(
                as_of,
                "gate_relax",
                ab_slot,
                {"ma_against": ma_against},
                "MA 门控拦截集中，用消融对照评估放宽 `ma_state` 后是否仍有正超额。",
            )
        )
    extreme = int(by_reason.get("vol_extreme") or 0) + int(by_reason.get("crowded") or 0)
    if extreme >= int(extreme_min):
        suggestions.append(
            _suggestion(
                as_of,
                "gate_tighten",
                ab_slot,
                {"extreme_blocked": extreme},
                "极端波动/拥挤拦截集中，维持或上调分位阈值，不做放宽。",
            )
        )
    if allowed and all(str(item.get("strength")) == "weak" for item in allowed):
        suggestions.append(
            _suggestion(
                as_of,
                "evidence_bar",
                ab_slot,
                {"weak_allowed": len(allowed)},
                "当期仅有弱证据通过，建议等待 strong/medium 再计入实践样本。",
            )
        )

    return {
        "schema_version": SCHEMA_VERSION,
        "as_of": as_of,
        "ab_slot": ab_slot,
        "suggestion_count": len(suggestions),
        "suggestions": suggestions,
    }


def validate_suggestions(document: Mapping[str, Any]) -> List[str]:
    errors: List[str] = []
    if document.get("schema_version") != SCHEMA_VERSION:
        errors.append(f"schema_version 必须为 {SCHEMA_VERSION}")
    suggestions = document.get("suggestions")
    if not isinstance(suggestions, list):
        return errors + ["suggestions 必须是列表"]
    seen: set[str] = set()
    for index, item in enumerate(suggestions):
        prefix = f"suggestions[{index}]"
        for key in (
            "suggestion_id",
            "as_of",
            "type",
            "ab_slot",
            "status",
            "evidence",
            "expected_effect",
        ):
            if key not in item:
                errors.append(f"{prefix} 缺字段 {key}")
        if not str(item.get("suggestion_id") or "").strip():
            errors.append(f"{prefix} suggestion_id 不能为空")
        if str(item.get("suggestion_id")) in seen:
            errors.append(f"{prefix} suggestion_id 重复：{item.get('suggestion_id')}")
        seen.add(str(item.get("suggestion_id")))
        if item.get("ab_slot") not in AB_SLOTS:
            errors.append(f"{prefix} ab_slot 必须是 A/B（缺槽位的建议不进入反思消费）")
        if item.get("type") not in SUGGESTION_TYPES:
            errors.append(f"{prefix} type 非法")
        if item.get("status") not in STATUSES:
            errors.append(f"{prefix} status 非法")
        if not isinstance(item.get("evidence"), dict) or not item.get("evidence"):
            errors.append(f"{prefix} evidence 必须是非空对象")
    return errors


def record_suggestions(
    document: Mapping[str, Any],
    *,
    db_path: Optional[str] = None,
    created_at: str = "",
) -> Dict[str, Any]:
    errors = validate_suggestions(document)
    if errors:
        return {"ok": False, "errors": errors, "inserted": 0, "duplicates": 0}
    path = db_path or DB_FILE
    directory = os.path.dirname(path)
    if directory:
        os.makedirs(directory, exist_ok=True)
    stamp = created_at or _now()
    inserted = duplicates = 0
    with sqlite3.connect(path) as conn:
        conn.execute(_SCHEMA)
        for item in document["suggestions"]:
            try:
                conn.execute(
                    "INSERT INTO reflection_suggestion (suggestion_id, schema_version, as_of, type, "
                    "ab_slot, status, evidence_json, expected_effect, created_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        item["suggestion_id"],
                        SCHEMA_VERSION,
                        str(item.get("as_of") or ""),
                        item["type"],
                        item["ab_slot"],
                        item["status"],
                        json.dumps(item["evidence"], ensure_ascii=False, sort_keys=True),
                        item["expected_effect"],
                        stamp,
                    ),
                )
                inserted += 1
            except sqlite3.IntegrityError:
                duplicates += 1
        conn.commit()
    return {
        "ok": True,
        "errors": [],
        "inserted": inserted,
        "duplicates": duplicates,
        "created_at": stamp,
    }


def apply_outcomes(
    outcomes: Iterable[Mapping[str, Any]],
    *,
    db_path: Optional[str] = None,
    evaluated_at: str = "",
) -> Dict[str, Any]:
    """用下期 outcomes.json 回填；只更新 pending，A/B 槽位不一致记 rejected。"""
    path = db_path or DB_FILE
    if not os.path.isfile(path):
        return {
            "ok": False,
            "reason": "ledger_missing",
            "matched": 0,
            "unknown": 0,
            "ab_slot_mismatch": 0,
        }
    stamp = evaluated_at or _now()
    matched = unknown = mismatch = 0
    with sqlite3.connect(path) as conn:
        conn.row_factory = sqlite3.Row
        conn.execute(_SCHEMA)
        for outcome in outcomes:
            suggestion_id = str(outcome.get("suggestion_id") or "")
            row = conn.execute(
                "SELECT ab_slot, status FROM reflection_suggestion WHERE suggestion_id = ?",
                (suggestion_id,),
            ).fetchone()
            if row is None:
                unknown += 1
                continue
            if outcome.get("ab_slot") and str(outcome["ab_slot"]) != str(row["ab_slot"]):
                conn.execute(
                    "UPDATE reflection_suggestion SET status = 'rejected', evaluated_at = ?, outcome_json = ? "
                    "WHERE suggestion_id = ?",
                    (
                        stamp,
                        json.dumps(dict(outcome), ensure_ascii=False, sort_keys=True),
                        suggestion_id,
                    ),
                )
                mismatch += 1
                continue
            conn.execute(
                "UPDATE reflection_suggestion SET status = 'evaluated', evaluated_at = ?, outcome_json = ? "
                "WHERE suggestion_id = ?",
                (
                    stamp,
                    json.dumps(dict(outcome), ensure_ascii=False, sort_keys=True),
                    suggestion_id,
                ),
            )
            matched += 1
        conn.commit()
    return {
        "ok": True,
        "matched": matched,
        "unknown": unknown,
        "ab_slot_mismatch": mismatch,
        "evaluated_at": stamp,
    }


def read_suggestions(
    *,
    db_path: Optional[str] = None,
    status: Optional[str] = None,
    limit: int = 100,
) -> List[Dict[str, Any]]:
    path = db_path or DB_FILE
    if not os.path.isfile(path):
        return []
    clauses: List[str] = []
    params: List[Any] = []
    if status:
        clauses.append("status = ?")
        params.append(str(status))
    where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
    params.append(max(1, int(limit)))
    with sqlite3.connect(path) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            f"SELECT * FROM reflection_suggestion{where} ORDER BY created_at DESC, suggestion_id LIMIT ?",
            params,
        ).fetchall()
    out: List[Dict[str, Any]] = []
    for row in rows:
        item = dict(row)
        item["evidence"] = json.loads(item.pop("evidence_json") or "{}")
        cached = item.pop("outcome_json", None)
        item["outcome"] = json.loads(cached) if cached else None
        out.append(item)
    return out
